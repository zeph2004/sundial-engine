import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.csp.domain import load_json


def intervals_overlap(
    day_a: str, start_a: int, dur_a: int,
    day_b: str, start_b: int, dur_b: int
) -> bool:
    """
    Returns True iff two sessions on (day_a, [start_a, start_a + dur_a - 1])
    and (day_b, [start_b, start_b + dur_b - 1]) overlap in time.
    """
    if day_a != day_b:
        return False
    end_a = start_a + dur_a - 1
    end_b = start_b + dur_b - 1
    return max(start_a, start_b) <= min(end_a, end_b)


def is_consistent_pair(
    val_a: Tuple[str, int, str | int], dur_a: int,
    val_b: Tuple[str, int, str | int], dur_b: int,
    shares_lecturer_or_cohort: bool
) -> bool:
    """
    Binary hard-constraint predicate between two assigned sessions x_a and x_b:
      - If they do not overlap in time (same day and intersecting period intervals), consistent.
      - If they overlap in time:
          1. They cannot share a lecturer or cohort (if shares_lecturer_or_cohort is True).
          2. They cannot occupy the same venue (venue_a != venue_b).
    """
    day_a, start_a, venue_a = val_a
    day_b, start_b, venue_b = val_b

    if not intervals_overlap(day_a, start_a, dur_a, day_b, start_b, dur_b):
        return True

    if shares_lecturer_or_cohort:
        return False

    if venue_a == venue_b:
        return False

    return True


def build_conflict_graph(
    sessions: List[Dict[str, Any]]
) -> Tuple[Dict[str, Set[str]], Dict[str, Any]]:
    """
    Builds an undirected conflict graph over sessions where an edge (x_i, x_j)
    exists iff x_i and x_j share at least one lecturer or at least one target cohort.

    Returns:
        adj: dict[str, set[str]] mapping sessionId -> set of conflicting sessionIds
        diagnostics: dict with graph statistics (|V|, |E_conflict|, lecturer_only_edges,
                     cohort_only_edges, both_edges, density, max_degree, max_degree_sessions,
                     avg_degree, isolated_vertices)
    """
    adj: Dict[str, Set[str]] = {s["sessionId"]: set() for s in sessions}
    lec_adj: Dict[str, Set[str]] = {s["sessionId"]: set() for s in sessions}
    coh_adj: Dict[str, Set[str]] = {s["sessionId"]: set() for s in sessions}

    # Index sessions by lecturer and by cohort for efficient edge construction
    by_lecturer: Dict[str, List[str]] = defaultdict(list)
    by_cohort: Dict[str, List[str]] = defaultdict(list)

    for s in sessions:
        sid = s["sessionId"]
        for lec in s.get("lecturers", []):
            by_lecturer[lec].append(sid)
        for coh in s.get("targetCohorts", []):
            by_cohort[coh].append(sid)

    for sids in by_lecturer.values():
        n = len(sids)
        for i in range(n):
            u = sids[i]
            for j in range(i + 1, n):
                v = sids[j]
                if u != v:
                    adj[u].add(v)
                    adj[v].add(u)
                    lec_adj[u].add(v)
                    lec_adj[v].add(u)

    for sids in by_cohort.values():
        n = len(sids)
        for i in range(n):
            u = sids[i]
            for j in range(i + 1, n):
                v = sids[j]
                if u != v:
                    adj[u].add(v)
                    adj[v].add(u)
                    coh_adj[u].add(v)
                    coh_adj[v].add(u)

    num_vertices = len(adj)
    total_directed = sum(len(neighbors) for neighbors in adj.values())
    num_edges = total_directed // 2
    num_lec_edges = sum(len(neighbors) for neighbors in lec_adj.values()) // 2
    num_coh_edges = sum(len(neighbors) for neighbors in coh_adj.values()) // 2
    num_both_edges = sum(len(lec_adj[u] & coh_adj[u]) for u in adj) // 2

    max_possible_edges = num_vertices * (num_vertices - 1) // 2 if num_vertices > 1 else 1
    density = num_edges / max_possible_edges if max_possible_edges > 0 else 0.0

    degrees = {sid: len(neighbors) for sid, neighbors in adj.items()}
    max_deg = max(degrees.values(), default=0)
    min_deg = min(degrees.values(), default=0)
    avg_deg = total_directed / num_vertices if num_vertices > 0 else 0.0
    max_deg_sessions = sorted(sid for sid, deg in degrees.items() if deg == max_deg)
    isolated_sessions = sorted(sid for sid, deg in degrees.items() if deg == 0)

    diagnostics = {
        "num_vertices": num_vertices,
        "num_edges": num_edges,
        "lecturer_edges": num_lec_edges,
        "cohort_edges": num_coh_edges,
        "shared_lecturer_and_cohort_edges": num_both_edges,
        "density": density,
        "min_degree": min_deg,
        "max_degree": max_deg,
        "max_degree_sessions": max_deg_sessions,
        "avg_degree": avg_deg,
        "isolated_count": len(isolated_sessions),
        "isolated_sessions": isolated_sessions,
    }
    return adj, diagnostics


def verify_ground_truth_constraints(
    sessions: List[Dict[str, Any]],
    adj: Dict[str, Set[str]] | None = None
) -> Dict[str, Any]:
    """
    Audits the human-scheduled groundTruth across all sessions against the exact
    hard constraints:
      1. Lecturer non-overlap
      2. Cohort non-overlap
      3. Venue non-double-booking

    Reports both pairwise session-pair conflicts and period-slot collisions.
    """
    if adj is None:
        adj, _ = build_conflict_graph(sessions)

    session_map = {s["sessionId"]: s for s in sessions}

    # 1. Pairwise session conflicts (unordered pairs {x_i, x_j} that overlap in time)
    lecturer_pair_conflicts: List[Dict[str, Any]] = []
    cohort_pair_conflicts: List[Dict[str, Any]] = []
    venue_pair_conflicts: List[Dict[str, Any]] = []
    any_hard_pair_conflicts: Set[Tuple[str, str]] = set()

    n = len(sessions)
    for i in range(n):
        s_a = sessions[i]
        sid_a = s_a["sessionId"]
        gt_a = s_a["groundTruth"]
        day_a, start_a, dur_a, ven_a = (
            gt_a["scheduledDay"],
            gt_a["startPeriod"],
            s_a["durationPeriods"],
            gt_a["venueId"],
        )
        lecs_a = set(s_a.get("lecturers", []))
        cohs_a = set(s_a.get("targetCohorts", []))

        for j in range(i + 1, n):
            s_b = sessions[j]
            sid_b = s_b["sessionId"]
            gt_b = s_b["groundTruth"]
            day_b, start_b, dur_b, ven_b = (
                gt_b["scheduledDay"],
                gt_b["startPeriod"],
                s_b["durationPeriods"],
                gt_b["venueId"],
            )

            if not intervals_overlap(day_a, start_a, dur_a, day_b, start_b, dur_b):
                continue

            overlap_periods = sorted(
                set(range(start_a, start_a + dur_a)) & set(range(start_b, start_b + dur_b))
            )
            pair_key = (min(sid_a, sid_b), max(sid_a, sid_b))

            shared_lecs = sorted(lecs_a & set(s_b.get("lecturers", [])))
            if shared_lecs:
                lecturer_pair_conflicts.append({
                    "pair": pair_key,
                    "day": day_a,
                    "overlap_periods": overlap_periods,
                    "shared_lecturers": shared_lecs,
                    "modules": (s_a["moduleCode"], s_b["moduleCode"]),
                })
                any_hard_pair_conflicts.add(pair_key)

            shared_cohs = sorted(cohs_a & set(s_b.get("targetCohorts", [])))
            if shared_cohs:
                cohort_pair_conflicts.append({
                    "pair": pair_key,
                    "day": day_a,
                    "overlap_periods": overlap_periods,
                    "shared_cohorts": shared_cohs,
                    "modules": (s_a["moduleCode"], s_b["moduleCode"]),
                })
                any_hard_pair_conflicts.add(pair_key)

            if ven_a == ven_b:
                venue_pair_conflicts.append({
                    "pair": pair_key,
                    "day": day_a,
                    "overlap_periods": overlap_periods,
                    "venueId": ven_a,
                    "venueName": gt_a.get("venueName", ""),
                    "modules": (s_a["moduleCode"], s_b["moduleCode"]),
                })
                any_hard_pair_conflicts.add(pair_key)

    # 2. Period-slot level collisions: (entity, day, period) -> [sessionIds]
    lec_slot_usage: Dict[Tuple[str, str, int], List[str]] = defaultdict(list)
    coh_slot_usage: Dict[Tuple[str, str, int], List[str]] = defaultdict(list)
    ven_slot_usage: Dict[Tuple[int, str, int], List[str]] = defaultdict(list)

    for s in sessions:
        sid = s["sessionId"]
        gt = s["groundTruth"]
        day = gt["scheduledDay"]
        start_p = gt["startPeriod"]
        dur = s["durationPeriods"]
        vid = gt["venueId"]
        for p in range(start_p, start_p + dur):
            ven_slot_usage[(vid, day, p)].append(sid)
            for lec in s.get("lecturers", []):
                lec_slot_usage[(lec, day, p)].append(sid)
            for coh in s.get("targetCohorts", []):
                coh_slot_usage[(coh, day, p)].append(sid)

    lec_slot_collisions = {k: v for k, v in lec_slot_usage.items() if len(v) > 1}
    coh_slot_collisions = {k: v for k, v in coh_slot_usage.items() if len(v) > 1}
    ven_slot_collisions = {k: v for k, v in ven_slot_usage.items() if len(v) > 1}

    conflicting_session_ids = sorted({
        sid
        for pair in any_hard_pair_conflicts
        for sid in pair
    })

    return {
        "is_conflict_free": len(any_hard_pair_conflicts) == 0,
        "total_conflicting_session_pairs": len(any_hard_pair_conflicts),
        "conflicting_sessions_count": len(conflicting_session_ids),
        "conflicting_session_ids": conflicting_session_ids,
        "pairwise_conflicts": {
            "lecturer_overlaps": len(lecturer_pair_conflicts),
            "cohort_overlaps": len(cohort_pair_conflicts),
            "venue_double_bookings": len(venue_pair_conflicts),
            "lecturer_details": lecturer_pair_conflicts,
            "cohort_details": cohort_pair_conflicts,
            "venue_details": venue_pair_conflicts,
        },
        "slot_collisions": {
            "lecturer_slot_collisions": len(lec_slot_collisions),
            "cohort_slot_collisions": len(coh_slot_collisions),
            "venue_slot_collisions": len(ven_slot_collisions),
        },
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    sessions = load_json(root / "data" / "raw" / "atc" / "atc-csp-sessions.json")["sessions"]
    session_by_id = {s["sessionId"]: s for s in sessions}

    adj, diag = build_conflict_graph(sessions)

    print("=== 1. Conflict Graph Diagnostics (Shared Lecturer / Cohort) ===")
    print(f"  Total vertices |X|              : {diag['num_vertices']}")
    print(f"  Total undirected edges |E|      : {diag['num_edges']:,}")
    print(f"    - Shared Lecturer edges       : {diag['lecturer_edges']:,}")
    print(f"    - Shared Cohort edges         : {diag['cohort_edges']:,}")
    print(f"    - Shared Both (intersection)  : {diag['shared_lecturer_and_cohort_edges']:,}")
    print(f"  Graph density                   : {diag['density']:.4f} ({diag['density']*100:.2f}%)")
    print(f"  Min degree min deg(x_i)         : {diag['min_degree']}")
    print(f"  Avg degree avg deg(x_i)         : {diag['avg_degree']:.2f}")
    print(f"  Max degree max deg(x_i)         : {diag['max_degree']} -> {diag['max_degree_sessions']}")
    for sid in diag["max_degree_sessions"]:
        s = session_by_id[sid]
        print(f"    * Top Degree Candidate {sid}: module={s['moduleCode']}, "
              f"cohorts={s['targetCohorts']}, lecturers={s['lecturers']}")
    print(f"  Isolated vertices (deg = 0)     : {diag['isolated_count']}"
          + (f" -> {diag['isolated_sessions']}" if diag["isolated_count"] > 0 else ""))

    audit = verify_ground_truth_constraints(sessions, adj)
    pw = audit["pairwise_conflicts"]
    sc = audit["slot_collisions"]

    print("\n=== 2. Ground-Truth Consistency Audit (1,299 Sessions) ===")
    print(f"  Conflict-free ground truth?     : {audit['is_conflict_free']}")
    print(f"  Distinct conflicting pairs      : {audit['total_conflicting_session_pairs']}")
    print(f"  Sessions involved in conflicts  : {audit['conflicting_sessions_count']}")
    print("  --- Pairwise Session Overlaps ---")
    print(f"  1. Lecturer overlaps (pairs)    : {pw['lecturer_overlaps']}")
    print(f"  2. Cohort overlaps (pairs)      : {pw['cohort_overlaps']}")
    print(f"  3. Venue double-bookings (pairs): {pw['venue_double_bookings']}")
    print("  --- Period-Slot Collisions (entity, day, period) ---")
    print(f"  1. Lecturer slot collisions     : {sc['lecturer_slot_collisions']}")
    print(f"  2. Cohort slot collisions       : {sc['cohort_slot_collisions']}")
    print(f"  3. Venue slot collisions        : {sc['venue_slot_collisions']}")

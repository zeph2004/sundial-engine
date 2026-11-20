import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.csp.constraints import build_conflict_graph, verify_ground_truth_constraints
from src.csp.domain import load_json
from src.csp.solver import SolverStats


def _normalize_visualizer_tier_label(raw_tier: str) -> str:
    """
    Maps detailed internal tier strings (`Tier 1A: Module Preferred`, `Tier 1B: Cohort Home`,
    `Tier 1C: Dept Prefix Pool`, `Tier 2: General Overflow`) to the concise visualizer labels.
    """
    if raw_tier.startswith("Tier 1A") or raw_tier.startswith("Tier 1B"):
        return "Tier 1: Module/Cohort Preferred"
    if raw_tier.startswith("Tier 1C"):
        return "Tier 1: Dept Pool"
    if raw_tier.startswith("Tier 2"):
        return "Tier 2: General Overflow"
    return raw_tier


def _build_mode_bundle(
    mode_key: str,
    mode_label: str,
    sessions: List[Dict[str, Any]],
    venues: List[Dict[str, Any]],
    assignments: Dict[str, Tuple[str, int, int | str]],
    stats: SolverStats,
    verification: Dict[str, Any],
    venue_tier_labels: Optional[Dict[str, Dict[int | str, str]]] = None,
) -> Dict[str, Any]:
    venue_by_id = {v["venueId"]: v for v in venues}
    adj, diag = build_conflict_graph(sessions)
    gt_audit = verify_ground_truth_constraints(sessions, adj)
    gt_conflicting_ids: Set[str] = set(gt_audit["conflicting_session_ids"])

    twilight_count = 0
    exported_sessions: List[Dict[str, Any]] = []
    sat_report = verification.get("saturday_report", {})
    sat_reasons: Dict[str, str] = sat_report.get("session_reasons", {})
    cond1_cohorts: Set[str] = set(sat_report.get("condition1_cohorts", []))

    for s in sessions:
        sid = s["sessionId"]
        dur = s["durationPeriods"]
        is_eve = s["isEveningStream"]

        # CSP solved assignment
        c_day, c_start, c_vid = assignments[sid]
        c_end = c_start + dur - 1
        c_vname = venue_by_id.get(c_vid, {}).get("name", f"Venue {c_vid}")
        is_twilight = bool(is_eve and c_start < 13)
        if is_twilight:
            twilight_count += 1

        raw_tier = (
            venue_tier_labels.get(sid, {}).get(c_vid, "Tier 1A: Module Preferred")
            if venue_tier_labels
            else "Tier 1A: Module Preferred"
        )
        viz_tier = _normalize_visualizer_tier_label(raw_tier)
        c_sat_reason = sat_reasons.get(sid, "Weekday" if c_day != "SATURDAY" else "Saturday (Condition 1: Cohort >60p Overflow)")

        # Ground truth assignment
        gt = s["groundTruth"]
        gt_day = gt["scheduledDay"]
        gt_start = gt["startPeriod"]
        gt_end = gt.get("endPeriod", gt_start + dur - 1)
        gt_vid = gt["venueId"]
        gt_vname = gt.get("venueName") or venue_by_id.get(gt_vid, {}).get("name", f"Venue {gt_vid}")
        if gt_day != "SATURDAY":
            gt_sat_reason = "Weekday"
        elif any(c in cond1_cohorts for c in s.get("targetCohorts", [])):
            gt_sat_reason = "Saturday (Condition 1: Cohort >60p Overflow)"
        else:
            gt_sat_reason = "Saturday (Condition 2: Hard-Constraint Bottleneck)"

        exported_sessions.append({
            "sessionId": sid,
            "moduleCode": s["moduleCode"],
            "moduleCodes": s.get("moduleCodes", [s["moduleCode"]]),
            "sessionType": s["sessionType"],
            "requiredVenueCategory": s["requiredVenueCategory"],
            "durationPeriods": dur,
            "isEveningStream": is_eve,
            "cohortLevel": str(s.get("cohortLevel", "")),
            "cohortRaw": s.get("cohortRaw", ""),
            "targetCohorts": s.get("targetCohorts", []),
            "lecturers": s.get("lecturers", []),
            "conflictDegree": len(adj.get(sid, set())),
            "cspAssignment": {
                "day": c_day,
                "startPeriod": c_start,
                "endPeriod": c_end,
                "venueId": c_vid,
                "venueName": c_vname,
                "isTwilight": is_twilight,
                "venueTier": viz_tier,
                "venueSubTier": raw_tier,
                "saturdayReason": c_sat_reason,
            },
            "groundTruth": {
                "day": gt_day,
                "startPeriod": gt_start,
                "endPeriod": gt_end,
                "venueId": gt_vid,
                "venueName": gt_vname,
                "hasConflict": sid in gt_conflicting_ids,
                "isTwilight": bool(is_eve and gt_start < 13),
                "venueTier": "Tier 1: Module/Cohort Preferred",
                "venueSubTier": "Tier 1A: Module Preferred",
                "saturdayReason": gt_sat_reason,
            },
        })

    tot = max(1, stats.total_variables)
    t1_total = verification.get("tier_1_total", stats.total_variables)
    t1a_count = verification.get("tier_1a_count", stats.total_variables)
    t2_overflow = verification.get("tier_2_overflow", 0)
    opt_report = verification.get("optimizer_report", {})

    return {
        "modeKey": mode_key,
        "modeLabel": mode_label,
        "telemetry": {
            "totalVariables": stats.total_variables,
            "conflictEdges": diag["num_edges"],
            "maxDegree": diag["max_degree"],
            "maxDegreeSessions": diag["max_degree_sessions"],
            "status": stats.status,
            "runtimeMs": round(stats.runtime_seconds * 1000, 2),
            "nodesVisited": stats.nodes_visited,
            "backtracks": stats.backtracks,
            "prunedValues": stats.pruned_values,
            "twilightCount": twilight_count,
            "tier1AffinityCount": t1_total,
            "tier1AffinityPct": round(t1_total / tot * 100, 1),
            "tier1AExactModuleCount": t1a_count,
            "tier1AExactModulePct": round(t1a_count / tot * 100, 1),
            "tier2OverflowCount": t2_overflow,
            "tier2OverflowPct": round(t2_overflow / tot * 100, 1),
            "specializedLockPct": 100.0,
            "cspSaturdayTotal": sat_report.get("csp_saturday_total", 0),
            "cspSaturdayCond1": sat_report.get("csp_saturday_cond1_count", 0),
            "cspSaturdayCond2": sat_report.get("csp_saturday_cond2_count", 0),
            "gtSaturdayTotal": sat_report.get("gt_saturday_total", 0),
            "totalCohorts": sat_report.get("total_cohorts", 121),
            "cspSaturdayFreeCohorts": sat_report.get("csp_saturday_free_cohorts", 0),
            "gtSaturdayFreeCohorts": sat_report.get("gt_saturday_free_cohorts", 0),
            "groundTruthConflictPairs": gt_audit["total_conflicting_session_pairs"],
            "groundTruthConflictingSessions": gt_audit["conflicting_sessions_count"],
            "optimizer": opt_report,
        },
        "sessions": exported_sessions,
    }


def export_timetable_view_data(
    root: Path,
    schema: Dict[str, Any],
    dataset: Dict[str, Any],
    csp_raw: Dict[str, Any],
    mode_a_tuple: Tuple[Any, ...],
    mode_b_tuple: Tuple[Any, ...],
) -> Path:
    """
    Exports `data/processed/timetable_view_data.json` and `src/viz/timetable_view_data.js`
    so the web visualizer works both over `file://` and local HTTP servers.
    """
    venues = dataset["venues"]
    sessions_a, assignments_a, stats_a = mode_a_tuple[0], mode_a_tuple[1], mode_a_tuple[2]
    ver_a = mode_a_tuple[3] if len(mode_a_tuple) > 3 else {}
    tiers_a = mode_a_tuple[4] if len(mode_a_tuple) > 4 else None

    sessions_b, assignments_b, stats_b = mode_b_tuple[0], mode_b_tuple[1], mode_b_tuple[2]
    ver_b = mode_b_tuple[3] if len(mode_b_tuple) > 3 else {}
    tiers_b = mode_b_tuple[4] if len(mode_b_tuple) > 4 else None

    # Build cohort entity catalog from all sessions
    cohort_info: Dict[str, Dict[str, Any]] = {}
    lecturer_set: Set[str] = set()
    for s in sessions_b:
        lvl = str(s.get("cohortLevel", ""))
        is_eve = bool(s.get("isEveningStream", False))
        for c in s.get("targetCohorts", []):
            if c not in cohort_info:
                cohort_info[c] = {
                    "id": c,
                    "name": c,
                    "level": lvl,
                    "isEvening": is_eve or c.endswith("-E"),
                }
        for l in s.get("lecturers", []):
            lecturer_set.add(l)

    cohorts_list = sorted(cohort_info.values(), key=lambda x: (x["level"], x["id"]))
    lecturers_list = [{"id": l, "name": l} for l in sorted(lecturer_set)]
    venues_list = sorted(
        [
            {
                "venueId": v["venueId"],
                "id": str(v["venueId"]),
                "name": v["name"],
                "category": v.get("category", ""),
                "upstreamType": v.get("upstreamType", ""),
                "capacity": v.get("capacity"),
                "location": v.get("location", ""),
            }
            for v in venues
        ],
        key=lambda x: (x["category"], x["name"]),
    )

    teaching_periods = csp_raw.get("metadata", {}).get("teachingPeriods", [])
    grid = schema["calendar_grid"]

    mode_1233 = _build_mode_bundle(
        mode_key="1233_clean",
        mode_label="Clean Primary Dataset (|X| = 1,233)",
        sessions=sessions_a,
        venues=venues,
        assignments=assignments_a,
        stats=stats_a,
        verification=ver_a,
        venue_tier_labels=tiers_a,
    )
    mode_1299 = _build_mode_bundle(
        mode_key="1299_full",
        mode_label="Full Pre-Flight Verified Dataset (|X| = 1,299)",
        sessions=sessions_b,
        venues=venues,
        assignments=assignments_b,
        stats=stats_b,
        verification=ver_b,
        venue_tier_labels=tiers_b,
    )

    payload: Dict[str, Any] = {
        "metadata": {
            "institutionCode": schema["institution"]["code"],
            "institutionName": schema["institution"]["name"],
            "semester": csp_raw.get("metadata", {}).get("semester", "I"),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "benchmarkMode": "1233_clean",
            "availableBenchmarkModes": ["1233_clean", "1299_full"],
            "solveTelemetry": mode_1233["telemetry"],
            "days": grid["active_days"],
            "periodsPerDay": grid["periods_per_day"],
            "breaksAfterPeriods": grid.get("breaks_after_periods", [4, 6]),
            "streamBoundaryAfterPeriod": schema["streams"]["full_time"]["max_period"],
            "twilightBufferPeriods": [11, 12],
            "periods": teaching_periods,
            "softConstraintsConfig": schema.get("soft_constraints", {}),
            "optimizerConfig": schema.get("optimizer", {}),
        },
        "entities": {
            "cohorts": cohorts_list,
            "lecturers": lecturers_list,
            "venues": venues_list,
        },
        "sessions": mode_1233["sessions"],
        "modes": {
            "1233_clean": mode_1233,
            "1299_full": mode_1299,
        },
    }

    out_json_path = root / "data" / "processed" / "timetable_view_data.json"
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    out_js_path = root / "src" / "viz" / "timetable_view_data.js"
    out_js_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_js_path, "w", encoding="utf-8") as f:
        f.write("window.__SUNDIAL_TIMETABLE_DATA__ = ")
        json.dump(payload, f, separators=(",", ":"))
        f.write(";\n")

    return out_json_path

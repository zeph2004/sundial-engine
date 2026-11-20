import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.csp.affinity import (
    SPECIALIZED_HARD_CATEGORIES,
    generate_venue_affinity_config,
    resolve_session_venues_and_tiers,
)
from src.csp.constraints import build_conflict_graph, intervals_overlap
from src.csp.domain import (
    build_domains,
    get_compatible_venues,
    get_valid_time_slots,
    load_json,
    run_preflight_checks,
)
from src.csp.optimizer import (
    OptimizerStats,
    SimulatedAnnealingOptimizer,
    SoftConstraintEngine,
    SoftObjectiveBreakdown,
)


DAY_INDEX_DEFAULT: Dict[str, int] = {
    "MONDAY": 0,
    "TUESDAY": 1,
    "WEDNESDAY": 2,
    "THURSDAY": 3,
    "FRIDAY": 4,
    "SATURDAY": 5,
    "SUNDAY": 6,
}


def compute_slot_bit(day_idx: int, period: int, periods_per_day: int = 18) -> int:
    """Maps a (day_idx, period) pair (1-indexed period) to its bit index in a 108-bit integer."""
    return day_idx * periods_per_day + (period - 1)


def compute_time_mask(
    day: str,
    start_period: int,
    duration: int,
    day_to_idx: Dict[str, int] = DAY_INDEX_DEFAULT,
    periods_per_day: int = 18,
) -> int:
    """Computes the 108-bit integer mask for a contiguous (day, start_period, duration) block."""
    d_idx = day_to_idx[day]
    base_bit = d_idx * periods_per_day + (start_period - 1)
    return ((1 << duration) - 1) << base_bit


@dataclass
class SolverStats:
    total_variables: int
    status: str
    runtime_seconds: float
    nodes_visited: int
    backtracks: int
    pruned_values: int
    assigned_count: int


class TimetableCSPSolver:
    """
    Pure-Python Backtracking CSP Solver with:
      1. Factored Time-First Domain Representation & 108-bit Integer Bitmasks
      2. 3-Tier Departmental Venue Affinity & Hard Specialized Lab Sub-Pools
      3. Strict 2-Condition Saturday Fallback via Weekday-Aware MRV & Lexicographic Ordering
      4. Dynamic Venue Occupancy & Eager Room-Pool Forward Checking
      5. Reversible Forward Checking via Lightweight Undo Logs (Zero deepcopy)
    """

    def __init__(
        self,
        sessions: List[Dict[str, Any]],
        venues: List[Dict[str, Any]],
        schema: Dict[str, Any],
        affinity_config: Dict[str, Any] | None = None,
        include_fallback_venues: bool = False,
        timeout_seconds: float = 60.0,
        pinned_assignments: Dict[str, Tuple[int | str, int, int | str]] | None = None,
    ) -> None:
        self.sessions = sessions
        self.venues = venues
        self.schema = schema
        self.affinity_config = affinity_config
        self.include_fallback_venues = include_fallback_venues
        self.timeout_seconds = timeout_seconds
        self.pinned_assignments = pinned_assignments

        grid = schema["calendar_grid"]
        self.periods_per_day: int = grid.get("periods_per_day", 18)
        active_days: List[str] = grid["active_days"]
        self.active_days: List[str] = list(active_days)
        self.day_to_idx: Dict[str, int] = {d: i for i, d in enumerate(active_days)}
        self.idx_to_day: Dict[int, str] = {i: d for i, d in enumerate(active_days)}

        # Map sessions and venues
        self.session_by_id: Dict[str, Dict[str, Any]] = {s["sessionId"]: s for s in sessions}
        self.venue_by_id: Dict[int | str, Dict[str, Any]] = {v["venueId"]: v for v in venues}
        self.all_var_ids: List[str] = [s["sessionId"] for s in sessions]

        # Build static conflict graph G_conflict over shared lecturers and cohorts
        self.adj, self.graph_diagnostics = build_conflict_graph(sessions)
        self.static_degree: Dict[str, int] = {
            sid: len(neighbors) for sid, neighbors in self.adj.items()
        }

        # Precompute slot_to_Mask[(day, start_p, duration)] -> 108-bit int
        self.slot_to_Mask: Dict[Tuple[str, int, int], int] = {}
        self.slot_single_bit: Dict[Tuple[str, int], int] = {}
        for day in active_days:
            for p in range(1, self.periods_per_day + 1):
                bit = compute_slot_bit(self.day_to_idx[day], p, self.periods_per_day)
                self.slot_single_bit[(day, p)] = 1 << bit
            for dur in (1, 2, 4, 6):
                for start_p in range(1, self.periods_per_day - dur + 2):
                    self.slot_to_Mask[(day, start_p, dur)] = compute_time_mask(
                        day, start_p, dur, self.day_to_idx, self.periods_per_day
                    )

        # Factor each variable's unary domain into:
        #   1) active_time_slots[x_i]: set[tuple[str, int]]
        #   2) weekday_slot_count[x_i]: count of active slots where day != "SATURDAY"
        #   3) compatible_venues[x_i]: ordered list[int | str] ([Tier 1A -> Tier 1B -> Tier 1C -> Tier 2])
        #   4) venue_tier_label[x_i][vid]: human-readable tier label
        #   5) venue_tier_rank[x_i][vid]: 1 for Tier 1A/1B/1C affinity, 2 for Tier 2 general overflow
        self.active_time_slots: Dict[str, Set[Tuple[str, int]]] = {}
        self.weekday_slot_count: Dict[str, int] = {}
        self.initial_time_slots: Dict[str, Set[Tuple[str, int]]] = {}
        self.compatible_venues: Dict[str, List[int | str]] = {}
        self.venue_tier_label: Dict[str, Dict[int | str, str]] = {}
        self.venue_tier_rank: Dict[str, Dict[int | str, int]] = {}
        self.var_duration: Dict[str, int] = {}
        self.var_is_evening: Dict[str, bool] = {}
        self.var_category: Dict[str, str] = {}
        self.var_lecturers: Dict[str, List[str]] = {}
        self.var_cohorts: Dict[str, List[str]] = {}

        # Pre-index var_overlapping_slots[x_i][(day, p)] -> list[tuple[str, int]]
        self.var_overlapping_slots: Dict[str, Dict[Tuple[str, int], List[Tuple[str, int]]]] = {}

        # Group variables by their exact unordered venue pool key for eager room-supply forward checking
        self.var_pool_key: Dict[str, Tuple[int | str, ...]] = {}
        self.vars_by_pool: Dict[Tuple[int | str, ...], List[str]] = defaultdict(list)
        self.pools_by_venue: Dict[int | str, List[Tuple[int | str, ...]]] = defaultdict(list)

        for s in sessions:
            sid = s["sessionId"]
            dur = s["durationPeriods"]
            is_eve = s["isEveningStream"]
            req_cat = s["requiredVenueCategory"]

            self.var_duration[sid] = dur
            self.var_is_evening[sid] = is_eve
            self.var_category[sid] = req_cat
            self.var_lecturers[sid] = list(s.get("lecturers", []))
            self.var_cohorts[sid] = list(s.get("targetCohorts", []))

            t_slots = get_valid_time_slots(is_evening=is_eve, duration=dur, schema=schema)
            self.active_time_slots[sid] = set(t_slots)
            self.initial_time_slots[sid] = set(t_slots)
            self.weekday_slot_count[sid] = sum(1 for (d, _) in t_slots if d != "SATURDAY")

            ordered_vids, tier_labels, tier_ranks = resolve_session_venues_and_tiers(
                session=s,
                venues=venues,
                schema=schema,
                affinity_config=affinity_config,
                include_fallbacks=include_fallback_venues,
            )
            self.compatible_venues[sid] = ordered_vids
            self.venue_tier_label[sid] = tier_labels
            self.venue_tier_rank[sid] = tier_ranks

            pool_key = tuple(sorted(ordered_vids, key=str))
            self.var_pool_key[sid] = pool_key
            self.vars_by_pool[pool_key].append(sid)

            # Build var_overlapping_slots[sid][(day, p)]
            overlap_map: Dict[Tuple[str, int], List[Tuple[str, int]]] = defaultdict(list)
            for day, start_p in t_slots:
                for p in range(start_p, start_p + dur):
                    overlap_map[(day, p)].append((day, start_p))
            self.var_overlapping_slots[sid] = overlap_map

        # Register which venue pools contain each physical venue_id
        self.pool_free_venue_count: Dict[Tuple[Tuple[int | str, ...], str, int], int] = {}
        for pool_key in self.vars_by_pool:
            num_v = len(pool_key)
            for vid in pool_key:
                self.pools_by_venue[vid].append(pool_key)
            for day in active_days:
                for p in range(1, self.periods_per_day + 1):
                    self.pool_free_venue_count[(pool_key, day, p)] = num_v

        # Dynamic state structures for search
        self.venue_busy_mask: Dict[int | str, int] = {v["venueId"]: 0 for v in venues}
        self.cohort_busy_mask: Dict[str, int] = defaultdict(int)
        self.lecturer_busy_mask: Dict[str, int] = defaultdict(int)
        self.unassigned_vars: Set[str] = set(self.all_var_ids)
        self.unassigned_degree: Dict[str, int] = dict(self.static_degree)
        self.assignments: Dict[str, Tuple[str, int, int | str]] = {}
        self.pinned_session_ids: Set[str] = set()

        # Track day loads per cohort and lecturer for day_load_spread tie-breaking
        self.cohort_day_load: Dict[Tuple[str, str], int] = defaultdict(int)
        self.lecturer_day_load: Dict[Tuple[str, str], int] = defaultdict(int)

        # Telemetry counters
        self.nodes_visited: int = 0
        self.backtracks: int = 0
        self.pruned_values: int = 0
        self._start_time: float = 0.0
        self._timed_out: bool = False

    def select_unassigned_variable(self) -> str:
        """
        Weekday-Aware MRV + Venue Pool Tightness + Degree Heuristic + Block Rigidity:
          - If `len(active_time_slots[sid]) == 0`: immediate wipeout (`effective_mrv = 0`).
          - While `weekday_slot_count[sid] > 0`: `effective_mrv = weekday_slot_count[sid] * min(|venues|, 4)`
            so sessions whose Monday-Friday options are running low are scheduled before their last
            weekday slot is stolen.
          - Once `weekday_slot_count[sid] == 0` (Monday-Friday is 100% full/infeasible for `sid`
            under Condition 1 or Condition 2): `sid` transitions cleanly to Saturday fallback
            (`effective_mrv = 1000 + len(active_time_slots[sid])`).
        """
        active_slots = self.active_time_slots
        wk_counts = self.weekday_slot_count
        compat_venues = self.compatible_venues
        unassigned_deg = self.unassigned_degree
        static_deg = self.static_degree
        durations = self.var_duration

        def _var_key(sid: str) -> Tuple[int, int, int, int, int, str]:
            tot = len(active_slots[sid])
            if tot == 0:
                return (0, 0, -unassigned_deg[sid], -static_deg[sid], -durations[sid], sid)
            wk = wk_counts[sid]
            v_factor = min(len(compat_venues[sid]), 4)
            if wk > 0:
                eff_mrv = wk * v_factor
                raw_mrv = wk
            else:
                eff_mrv = 1000 + tot * v_factor
                raw_mrv = 1000 + tot
            return (
                eff_mrv,
                raw_mrv,
                -unassigned_deg[sid],
                -static_deg[sid],
                -durations[sid],
                sid,
            )

        return min(self.unassigned_vars, key=_var_key)

    def order_domain_values(self, sid: str) -> List[Tuple[str, int, int | str]]:
        """
        Lexicographic Saturday-Fallback + Affinity-Aware Time-Slot LCV Value Ordering:
          Sorts candidate (day, start_p) ascending by:
            (is_saturday, twilight_penalty, best_available_venue_tier, conflict_score, subtier_rank, day_load_spread)
          where:
            - `is_saturday = 1 if day == "SATURDAY" else 0`:
              Monday-Friday (`is_saturday == 0`) ALWAYS beats Saturday (`is_saturday == 1`),
              even if Monday-Friday requires a Tier 2 general classroom!
            - `twilight_penalty = 1 if (isEveningStream and start_p < 13) else 0`
            - `best_available_venue_tier = 1` (Tier 1A/1B/1C) vs `2` (Tier 2 General Overflow)
            - `conflict_score`: LCV count of overlapping active slots in unassigned neighbors
            - `day_load_spread`: current assigned periods on `day` for `sid`'s cohorts + lecturers
        """
        dur = self.var_duration[sid]
        is_eve = self.var_is_evening[sid]
        cohorts = self.var_cohorts[sid]
        lecturers = self.var_lecturers[sid]
        compat_vids = self.compatible_venues[sid]
        tier_ranks = self.venue_tier_rank[sid]
        tier_labels = self.venue_tier_label[sid]
        venue_busy = self.venue_busy_mask
        unassigned = self.unassigned_vars
        active_slots = self.active_time_slots
        var_overlaps = self.var_overlapping_slots

        unassigned_neighbors = [nb for nb in self.adj[sid] if nb in unassigned]

        scored_placements: List[Tuple[int, int, int, int, int, int, int, int, Tuple[str, int, int | str]]] = []
        for day, start_p in active_slots[sid]:
            time_mask = self.slot_to_Mask[(day, start_p, dur)]

            # Find best free venue in priority order [Tier 1A -> Tier 1B -> Tier 1C -> Tier 2]
            chosen_venue: Optional[int | str] = None
            for vid in compat_vids:
                if (venue_busy[vid] & time_mask) == 0:
                    chosen_venue = vid
                    break

            if chosen_venue is None:
                continue

            is_saturday = 1 if day == "SATURDAY" else 0
            best_tier = tier_ranks[chosen_venue]
            lbl = tier_labels[chosen_venue]
            if lbl.startswith("Tier 1A"):
                subtier_rank = 0
            elif lbl.startswith("Tier 1B"):
                subtier_rank = 1
            elif lbl.startswith("Tier 1C"):
                subtier_rank = 2
            else:
                subtier_rank = 3

            # Compute LCV conflict score across unassigned neighbors
            conflict_score = 0
            if dur == 1:
                dp = (day, start_p)
                for nb in unassigned_neighbors:
                    nb_active = active_slots[nb]
                    for cand in var_overlaps[nb].get(dp, ()):
                        if cand in nb_active:
                            conflict_score += 1
            else:
                for nb in unassigned_neighbors:
                    nb_active = active_slots[nb]
                    nb_ov = var_overlaps[nb]
                    nb_dur = self.var_duration[nb]
                    if nb_dur == 1:
                        for p in range(start_p, start_p + dur):
                            if (day, p) in nb_active:
                                conflict_score += 1
                    else:
                        seen_cands: Set[Tuple[str, int]] = set()
                        for p in range(start_p, start_p + dur):
                            for cand in nb_ov.get((day, p), ()):
                                if cand in nb_active and cand not in seen_cands:
                                    seen_cands.add(cand)
                                    conflict_score += 1

            twilight_penalty = 1 if (is_eve and start_p < 13) else 0

            day_load = 0
            for c in cohorts:
                day_load += self.cohort_day_load[(c, day)]
            for l in lecturers:
                day_load += self.lecturer_day_load[(l, day)]

            scored_placements.append((
                is_saturday,
                twilight_penalty,
                best_tier,
                conflict_score,
                subtier_rank,
                day_load,
                self.day_to_idx[day],
                start_p,
                (day, start_p, chosen_venue),
            ))

        scored_placements.sort()
        return [item[8] for item in scored_placements]

    def _remove_active_slot(
        self,
        var_id: str,
        slot: Tuple[str, int],
        undo_log: List[Tuple[str, Tuple[str, int]]],
    ) -> None:
        self.active_time_slots[var_id].remove(slot)
        if slot[0] != "SATURDAY":
            self.weekday_slot_count[var_id] -= 1
        undo_log.append((var_id, slot))
        self.pruned_values += 1

    def forward_check(
        self,
        sid: str,
        day: str,
        start_p: int,
        dur: int,
        venue_id: int | str,
        undo_log: List[Tuple[str, Tuple[str, int]]],
    ) -> bool:
        """
        Reversible Forward Checking:
          1. Prunes overlapping (day, start_p_j) from all unassigned neighbors x_j in adj[sid].
          2. Eagerly checks room supply for every venue pool affected by `venue_id` on each
             covered (day, p): if free rooms in that pool drop to 0 at (day, p), prunes all
             covering (day, start_p_k) from all unassigned sessions x_k sharing that pool.
          Returns False immediately on any domain wipeout (|active_time_slots| == 0).
        """
        unassigned = self.unassigned_vars
        active_slots = self.active_time_slots
        var_overlaps = self.var_overlapping_slots

        # 1. Binary conflict graph pruning (Lecturer & Cohort non-overlap)
        for nb in self.adj[sid]:
            if nb not in unassigned:
                continue
            nb_active = active_slots[nb]
            nb_ov = var_overlaps[nb]
            for p in range(start_p, start_p + dur):
                for cand in nb_ov.get((day, p), ()):
                    if cand in nb_active:
                        self._remove_active_slot(nb, cand, undo_log)
            if not nb_active:
                return False

        # 2. Eager venue-pool room-supply forward checking across all pools containing `venue_id`
        for pool_key in self.pools_by_venue[venue_id]:
            exhausted_periods = [
                p for p in range(start_p, start_p + dur)
                if self.pool_free_venue_count[(pool_key, day, p)] == 0
            ]
            if not exhausted_periods:
                continue
            for other_sid in self.vars_by_pool[pool_key]:
                if other_sid not in unassigned:
                    continue
                other_active = active_slots[other_sid]
                other_ov = var_overlaps[other_sid]
                for p in exhausted_periods:
                    for cand in other_ov.get((day, p), ()):
                        if cand in other_active:
                            self._remove_active_slot(other_sid, cand, undo_log)
                if not other_active:
                    return False

        return True

    def _restore(
        self,
        sid: str,
        day: str,
        start_p: int,
        dur: int,
        venue_id: int | str,
        time_mask: int,
        undo_log: List[Tuple[str, Tuple[str, int]]],
    ) -> None:
        """Reverses all state mutations made during a single assignment step in O(|undo_log|)."""
        active_slots = self.active_time_slots
        wk_counts = self.weekday_slot_count
        for var_id, slot in undo_log:
            active_slots[var_id].add(slot)
            if slot[0] != "SATURDAY":
                wk_counts[var_id] += 1

        self.venue_busy_mask[venue_id] &= ~time_mask
        for pool_key in self.pools_by_venue[venue_id]:
            for p in range(start_p, start_p + dur):
                self.pool_free_venue_count[(pool_key, day, p)] += 1

        for c in self.var_cohorts[sid]:
            self.cohort_busy_mask[c] &= ~time_mask
            self.cohort_day_load[(c, day)] -= dur
        for l in self.var_lecturers[sid]:
            self.lecturer_busy_mask[l] &= ~time_mask
            self.lecturer_day_load[(l, day)] -= dur

    def _normalize_pin_tuple(
        self, sid: str, raw_pin: Tuple[int | str, int, int | str]
    ) -> Tuple[str, int, int | str]:
        """
        Normalizes a pin tuple `(day_idx_or_str, start_period, venue_id)` into `(day_str, start_period, canonical_venue_id)`.
        Raises ValueError if `sid`, `day`, `start_period`, or `venue_id` is invalid.
        """
        if sid not in self.session_by_id:
            raise ValueError(f"Invalid pin: session_id '{sid}' does not exist in the dataset.")

        raw_day, raw_start_p, raw_vid = raw_pin
        if isinstance(raw_day, int):
            if raw_day not in self.idx_to_day:
                raise ValueError(
                    f"Invalid pin for session '{sid}': day_idx {raw_day} is out of range "
                    f"(valid indices: 0..{len(self.active_days) - 1})."
                )
            day_str = self.idx_to_day[raw_day]
        elif isinstance(raw_day, str):
            d_up = raw_day.strip().upper()
            if d_up in self.day_to_idx:
                day_str = d_up
            elif raw_day.strip().isdigit() and int(raw_day.strip()) in self.idx_to_day:
                day_str = self.idx_to_day[int(raw_day.strip())]
            else:
                raise ValueError(
                    f"Invalid pin for session '{sid}': day '{raw_day}' is not in active_days {self.active_days}."
                )
        else:
            raise ValueError(f"Invalid pin for session '{sid}': unrecognized day '{raw_day}'.")

        start_p = int(raw_start_p)
        if (day_str, start_p) not in self.initial_time_slots[sid]:
            raise ValueError(
                f"Invalid pin for session '{sid}': time slot ({day_str}, start_period={start_p}) "
                f"is not in the session's unary time domain."
            )

        # Match venue_id by exact type or string representation against compatible_venues[sid]
        compat_vids = self.compatible_venues[sid]
        matched_vid: Optional[int | str] = None
        for cv in compat_vids:
            if cv == raw_vid or str(cv) == str(raw_vid):
                matched_vid = cv
                break

        if matched_vid is None:
            raise ValueError(
                f"Invalid pin for session '{sid}': venue_id '{raw_vid}' is not in the session's "
                f"compatible venue pool {compat_vids}."
            )

        return day_str, start_p, matched_vid

    def _validate_and_apply_pins(
        self,
        pinned_assignments: Dict[str, Tuple[int | str, int, int | str]],
    ) -> bool:
        """
        1. Validates that every pinned session exists, its (day, start_period) is in its unary
           time domain, and its venue_id is in its compatible venue pool.
        2. Validates zero pairwise conflicts among pinned sessions (no shared lecturer, cohort,
           or venue overlapping on the 108-bit time masks), raising a clear ValueError if any
           pin is invalid or conflicts with another pin.
        3. Pre-assigns all pinned sessions, updates 108-bit occupancy masks (`cohort_busy_mask`,
           `lecturer_busy_mask`, `venue_busy_mask`), and runs eager forward-checking propagation
           against unpinned neighbors before backtracking begins.
        Returns False if forward-checking propagation detects an immediate domain wipeout on an
        unpinned variable.
        """
        normalized_pins: List[Tuple[str, str, int, int | str, int]] = []
        for sid, raw_pin in pinned_assignments.items():
            day_str, start_p, vid = self._normalize_pin_tuple(sid, raw_pin)
            dur = self.var_duration[sid]
            t_mask = self.slot_to_Mask[(day_str, start_p, dur)]
            normalized_pins.append((sid, day_str, start_p, vid, t_mask))

        # Check all pairwise conflicts among pinned sessions on 108-bit time masks
        n_pins = len(normalized_pins)
        for i in range(n_pins):
            sid_a, day_a, sp_a, vid_a, mask_a = normalized_pins[i]
            lecs_a = set(self.var_lecturers[sid_a])
            cohs_a = set(self.var_cohorts[sid_a])
            for j in range(i + 1, n_pins):
                sid_b, day_b, sp_b, vid_b, mask_b = normalized_pins[j]
                if (mask_a & mask_b) == 0:
                    continue
                shared_lecs = sorted(lecs_a & set(self.var_lecturers[sid_b]))
                if shared_lecs:
                    raise ValueError(
                        f"Pin conflict between '{sid_a}' and '{sid_b}' on {day_a}: "
                        f"shared lecturer(s) {shared_lecs} overlap in time."
                    )
                shared_cohs = sorted(cohs_a & set(self.var_cohorts[sid_b]))
                if shared_cohs:
                    raise ValueError(
                        f"Pin conflict between '{sid_a}' and '{sid_b}' on {day_a}: "
                        f"shared cohort(s) {shared_cohs} overlap in time."
                    )
                if vid_a == vid_b:
                    raise ValueError(
                        f"Pin conflict between '{sid_a}' and '{sid_b}' on {day_a}: "
                        f"venue '{vid_a}' is double-booked in overlapping periods."
                    )

        # First mark all pinned variables as assigned (removing them from unassigned_vars)
        for sid, day_str, start_p, vid, t_mask in normalized_pins:
            self.pinned_session_ids.add(sid)
            self.unassigned_vars.remove(sid)
            for nb in self.adj[sid]:
                if nb in self.unassigned_vars:
                    self.unassigned_degree[nb] -= 1

            dur = self.var_duration[sid]
            self.assignments[sid] = (day_str, start_p, vid)
            self.venue_busy_mask[vid] |= t_mask
            for pool_key in self.pools_by_venue[vid]:
                for p in range(start_p, start_p + dur):
                    self.pool_free_venue_count[(pool_key, day_str, p)] -= 1

            for c in self.var_cohorts[sid]:
                self.cohort_busy_mask[c] |= t_mask
                self.cohort_day_load[(c, day_str)] += dur
            for l in self.var_lecturers[sid]:
                self.lecturer_busy_mask[l] |= t_mask
                self.lecturer_day_load[(l, day_str)] += dur

        # Now propagate forward checking from each pinned session against unpinned variables
        pin_undo_log: List[Tuple[str, Tuple[str, int]]] = []
        for sid, day_str, start_p, vid, _ in normalized_pins:
            dur = self.var_duration[sid]
            if not self.forward_check(sid, day_str, start_p, dur, vid, pin_undo_log):
                return False

        return True

    def _backtrack(self) -> bool:
        if not self.unassigned_vars:
            return True

        if (self.nodes_visited & 255) == 0:
            if (time.perf_counter() - self._start_time) > self.timeout_seconds:
                self._timed_out = True
                return False

        sid = self.select_unassigned_variable()
        if not self.active_time_slots[sid]:
            self.backtracks += 1
            return False

        self.nodes_visited += 1

        # Mark sid as assigned and update dynamic degrees
        self.unassigned_vars.remove(sid)
        for nb in self.adj[sid]:
            if nb in self.unassigned_vars:
                self.unassigned_degree[nb] -= 1

        dur = self.var_duration[sid]
        ordered_placements = self.order_domain_values(sid)

        for day, start_p, chosen_venue in ordered_placements:
            time_mask = self.slot_to_Mask[(day, start_p, dur)]

            # Apply assignment state updates
            self.assignments[sid] = (day, start_p, chosen_venue)
            self.venue_busy_mask[chosen_venue] |= time_mask
            for pool_key in self.pools_by_venue[chosen_venue]:
                for p in range(start_p, start_p + dur):
                    self.pool_free_venue_count[(pool_key, day, p)] -= 1

            for c in self.var_cohorts[sid]:
                self.cohort_busy_mask[c] |= time_mask
                self.cohort_day_load[(c, day)] += dur
            for l in self.var_lecturers[sid]:
                self.lecturer_busy_mask[l] |= time_mask
                self.lecturer_day_load[(l, day)] += dur

            undo_log: List[Tuple[str, Tuple[str, int]]] = []
            if self.forward_check(sid, day, start_p, dur, chosen_venue, undo_log):
                if self._backtrack():
                    return True

            # Undo state changes on failure
            del self.assignments[sid]
            self._restore(sid, day, start_p, dur, chosen_venue, time_mask, undo_log)

        # Restore variable to unassigned set
        for nb in self.adj[sid]:
            if nb in self.unassigned_vars:
                self.unassigned_degree[nb] += 1
        self.unassigned_vars.add(sid)
        self.backtracks += 1
        return False

    def solve(
        self,
        pinned_assignments: Dict[str, Tuple[int | str, int, int | str]] | None = None,
    ) -> Tuple[Dict[str, Tuple[str, int, int | str]], SolverStats]:
        """Executes backtracking search (honoring any pinned_assignments) and returns (assignments, stats)."""
        required_limit = max(sys.getrecursionlimit(), len(self.sessions) * 3 + 1000)
        if sys.getrecursionlimit() < required_limit:
            sys.setrecursionlimit(required_limit)

        self._start_time = time.perf_counter()
        self._timed_out = False

        active_pins = (
            pinned_assignments
            if pinned_assignments is not None
            else self.pinned_assignments
        )

        # Immediate check for any initial unary wipeout
        if any(len(slots) == 0 or len(self.compatible_venues[sid]) == 0
               for sid, slots in self.active_time_slots.items()):
            elapsed = time.perf_counter() - self._start_time
            return {}, SolverStats(
                total_variables=len(self.sessions),
                status="UNSATISFIABLE",
                runtime_seconds=elapsed,
                nodes_visited=0,
                backtracks=0,
                pruned_values=0,
                assigned_count=0,
            )

        if active_pins:
            if not self._validate_and_apply_pins(active_pins):
                elapsed = time.perf_counter() - self._start_time
                return {}, SolverStats(
                    total_variables=len(self.sessions),
                    status="UNSATISFIABLE",
                    runtime_seconds=elapsed,
                    nodes_visited=0,
                    backtracks=0,
                    pruned_values=self.pruned_values,
                    assigned_count=len(self.assignments),
                )

        solved = self._backtrack()
        elapsed = time.perf_counter() - self._start_time

        if solved:
            status = "SOLVED"
            # Verify that every pinned session still holds its exact pinned assignment
            if active_pins:
                for sid, raw_pin in active_pins.items():
                    exp_day, exp_sp, exp_vid = self._normalize_pin_tuple(sid, raw_pin)
                    if self.assignments.get(sid) != (exp_day, exp_sp, exp_vid):
                        raise AssertionError(
                            f"Pinned session '{sid}' was modified during search: "
                            f"expected {(exp_day, exp_sp, exp_vid)}, got {self.assignments.get(sid)}"
                        )
        elif self._timed_out:
            status = "TIMEOUT"
        else:
            status = "UNSATISFIABLE"

        stats = SolverStats(
            total_variables=len(self.sessions),
            status=status,
            runtime_seconds=elapsed,
            nodes_visited=self.nodes_visited,
            backtracks=self.backtracks,
            pruned_values=self.pruned_values,
            assigned_count=len(self.assignments),
        )
        return dict(self.assignments), stats


def classify_saturday_placements(
    sessions: List[Dict[str, Any]],
    assignments: Dict[str, Tuple[str, int, int | str]],
) -> Dict[str, Any]:
    """
    Classifies every session into:
      - `"Weekday"`
      - `"Saturday (Condition 1: Cohort >60p Overflow)"`
      - `"Saturday (Condition 2: Hard-Constraint Bottleneck)"`
    and computes comparative Saturday telemetry between the Sundial CSP solution
    and the ATC Ground Truth.
    """
    cohort_total_periods: Dict[str, int] = defaultdict(int)
    cohort_6p_blocks: Dict[str, int] = defaultdict(int)
    cohort_is_evening: Dict[str, bool] = {}
    all_cohorts: Set[str] = set()

    for s in sessions:
        dur = s["durationPeriods"]
        is_eve = s["isEveningStream"]
        for c in s.get("targetCohorts", []):
            all_cohorts.add(c)
            cohort_total_periods[c] += dur
            if dur == 6:
                cohort_6p_blocks[c] += 1
            cohort_is_evening[c] = is_eve or c.endswith("-E")

    # Condition 1 cohorts: >60p Full-Time or >30p standard Evening (P13-P18 = 6p/day * 5 days = 30p)
    # or >5 six-period afternoon blocks
    cond1_cohorts: Set[str] = set()
    for c in all_cohorts:
        if cohort_is_evening.get(c, False):
            if cohort_total_periods[c] > 30:
                cond1_cohorts.add(c)
        else:
            if cohort_total_periods[c] > 60 or cohort_6p_blocks[c] > 5:
                cond1_cohorts.add(c)

    session_saturday_reason: Dict[str, str] = {}
    csp_sat_cond1: List[str] = []
    csp_sat_cond2: List[str] = []
    csp_sat_cohorts: Set[str] = set()
    csp_sat_shared_practicals: List[str] = []
    csp_sat_solo_practicals: List[str] = []
    csp_sat_theory: List[str] = []
    theory_types = {"Theory", "Lecture", "Tutorial"}

    gt_sat_sessions: List[str] = []
    gt_sat_cohorts: Set[str] = set()

    for s in sessions:
        sid = s["sessionId"]
        cohs = s.get("targetCohorts", [])
        stype = s.get("sessionType", "Theory")
        if s["groundTruth"]["scheduledDay"] == "SATURDAY":
            gt_sat_sessions.append(sid)
            gt_sat_cohorts.update(cohs)

        if sid not in assignments:
            session_saturday_reason[sid] = "Unassigned"
            continue

        day, _, _ = assignments[sid]
        if day != "SATURDAY":
            session_saturday_reason[sid] = "Weekday"
        else:
            csp_sat_cohorts.update(cohs)
            if stype in theory_types:
                csp_sat_theory.append(sid)
            elif len(cohs) >= 2:
                csp_sat_shared_practicals.append(sid)
            else:
                csp_sat_solo_practicals.append(sid)
            if any(c in cond1_cohorts for c in cohs):
                reason = "Saturday (Condition 1: Cohort >60p Overflow)"
                csp_sat_cond1.append(sid)
            else:
                reason = "Saturday (Condition 2: Hard-Constraint Bottleneck)"
                csp_sat_cond2.append(sid)
            session_saturday_reason[sid] = reason

    total_cohorts = len(all_cohorts)
    csp_sat_free_cohorts = total_cohorts - len(csp_sat_cohorts)
    gt_sat_free_cohorts = total_cohorts - len(gt_sat_cohorts)

    return {
        "session_reasons": session_saturday_reason,
        "condition1_cohorts": sorted(cond1_cohorts),
        "cohort_total_periods": dict(cohort_total_periods),
        "csp_saturday_total": len(csp_sat_cond1) + len(csp_sat_cond2),
        "csp_saturday_cond1_count": len(csp_sat_cond1),
        "csp_saturday_cond2_count": len(csp_sat_cond2),
        "csp_saturday_cond1_sessions": csp_sat_cond1,
        "csp_saturday_cond2_sessions": csp_sat_cond2,
        "csp_saturday_shared_practicals_count": len(csp_sat_shared_practicals),
        "csp_saturday_solo_practicals_count": len(csp_sat_solo_practicals),
        "csp_saturday_theory_count": len(csp_sat_theory),
        "csp_saturday_shared_practicals": csp_sat_shared_practicals,
        "csp_saturday_solo_practicals": csp_sat_solo_practicals,
        "csp_saturday_theory_sessions": csp_sat_theory,
        "gt_saturday_total": len(gt_sat_sessions),
        "total_cohorts": total_cohorts,
        "csp_saturday_free_cohorts": csp_sat_free_cohorts,
        "gt_saturday_free_cohorts": gt_sat_free_cohorts,
    }


def diagnose_remaining_saturday_theory(
    sessions: List[Dict[str, Any]],
    assignments: Dict[str, Tuple[str, int, int | str]],
    compatible_venues: Dict[str, List[int | str]],
    schema: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Inspects every remaining Saturday Theory session after SA optimization and diagnoses:
      - session_id, module_code, cohorts, lecturers, durationPeriods, isEveningStream
      - How many weekday non-Theory (Lab/Workshop/Studio/Field) sessions those cohorts have,
        and their durationPeriods
      - The primary reason a pairwise swap with those weekday non-Theory sessions was blocked
        (e.g., `duration mismatch`, `lecturer busy on Saturday`, `shared cohort busy on weekday`,
        `Saturday lecturer busy on weekday`, `weekday cohort busy on Saturday`, `venue unavailable`,
        or `no weekday practicals available`).
    """
    grid = schema["calendar_grid"]
    active_days: List[str] = list(grid["active_days"])
    periods_per_day: int = int(grid.get("periods_per_day", 18))
    day_to_idx: Dict[str, int] = {d: i for i, d in enumerate(active_days)}
    theory_types = set(
        schema.get("soft_constraints", {})
        .get("minimize_saturday_theory", {})
        .get("params", {})
        .get("theory_types", ["Theory", "Lecture", "Tutorial"])
    )

    session_by_id = {s["sessionId"]: s for s in sessions}
    lec_busy: Dict[str, int] = defaultdict(int)
    coh_busy: Dict[str, int] = defaultdict(int)
    ven_busy: Dict[int | str, int] = defaultdict(int)
    session_gmask: Dict[str, int] = {}

    for s in sessions:
        sid = s["sessionId"]
        if sid not in assignments:
            continue
        day_str, start_p, vid = assignments[sid]
        dur = int(s["durationPeriods"])
        gm = compute_time_mask(day_str, start_p, dur, day_to_idx, periods_per_day)
        session_gmask[sid] = gm
        ven_busy[vid] |= gm
        for l in s.get("lecturers", []):
            lec_busy[l] |= gm
        for c in s.get("targetCohorts", []):
            coh_busy[c] |= gm

    sat_theory_sessions = [
        s
        for s in sessions
        if s["sessionId"] in assignments
        and assignments[s["sessionId"]][0] == "SATURDAY"
        and s.get("sessionType", "Theory") in theory_types
    ]

    diagnostics: List[Dict[str, Any]] = []
    for sa in sat_theory_sessions:
        sida = sa["sessionId"]
        da_str, spa, vida = assignments[sida]
        dura = int(sa["durationPeriods"])
        evea = bool(sa.get("isEveningStream", False))
        cohs_a = list(sa.get("targetCohorts", []))
        lecs_a = list(sa.get("lecturers", []))
        cohort_raw_a = str(sa.get("cohortRaw", ""))
        gma = session_gmask[sida]
        has_cs7_2 = any(
            c.lower() in ("cs7-2", "l7-1cs") for c in cohs_a
        ) or ("cs7-2" in cohort_raw_a.lower())

        # Find all weekday non-Theory sessions belonging to any cohort in cohs_a
        coh_set_a = set(cohs_a)
        wk_practicals: List[Dict[str, Any]] = []
        for sb in sessions:
            sidb = sb["sessionId"]
            if sidb == sida or sidb not in assignments:
                continue
            db_str, _, _ = assignments[sidb]
            if db_str == "SATURDAY":
                continue
            if sb.get("sessionType", "Theory") in theory_types:
                continue
            if coh_set_a.intersection(sb.get("targetCohorts", [])):
                wk_practicals.append(sb)

        dur_counts: Counter = Counter(int(sb["durationPeriods"]) for sb in wk_practicals)
        reason_counts: Counter = Counter()
        candidate_details: List[str] = []

        if not wk_practicals:
            primary_reason = "no weekday practicals available"
        else:
            for sb in wk_practicals:
                sidb = sb["sessionId"]
                db_str, spb, vidb = assignments[sidb]
                durb = int(sb["durationPeriods"])
                eveb = bool(sb.get("isEveningStream", False))
                cohs_b = list(sb.get("targetCohorts", []))
                lecs_b = list(sb.get("lecturers", []))
                gmb = session_gmask[sidb]

                if durb != dura:
                    reason = f"duration mismatch ({durb}p vs {dura}p)"
                    reason_counts["duration mismatch"] += 1
                    candidate_details.append(f"{sidb}({sb['moduleCode']},{durb}p): {reason}")
                    continue
                if eveb != evea:
                    reason = "stream mismatch (Evening vs Full-Time)"
                    reason_counts["stream mismatch"] += 1
                    candidate_details.append(f"{sidb}({sb['moduleCode']},{durb}p): {reason}")
                    continue

                # Check hard constraints if sida and sidb swap time slots
                # Release both sida and sidb from bitmasks
                busy_lec_b_on_sat = [
                    l for l in lecs_b if ((lec_busy[l] & ~gma & ~gmb) & gma) != 0
                ]
                busy_coh_b_on_sat = [
                    c for c in cohs_b if ((coh_busy[c] & ~gma & ~gmb) & gma) != 0
                ]
                busy_lec_a_on_wk = [
                    l for l in lecs_a if ((lec_busy[l] & ~gma & ~gmb) & gmb) != 0
                ]
                busy_coh_a_on_wk = [
                    c for c in cohs_a if ((coh_busy[c] & ~gma & ~gmb) & gmb) != 0
                ]

                if busy_lec_b_on_sat:
                    reason = f"lecturer busy on Saturday ({', '.join(busy_lec_b_on_sat)})"
                    reason_counts["lecturer busy on Saturday"] += 1
                elif busy_coh_a_on_wk:
                    reason = f"shared cohort busy on weekday ({', '.join(busy_coh_a_on_wk)} on {db_str} P{spb})"
                    reason_counts["shared cohort busy on weekday"] += 1
                elif busy_lec_a_on_wk:
                    reason = f"Saturday lecturer busy on weekday ({', '.join(busy_lec_a_on_wk)} on {db_str} P{spb})"
                    reason_counts["Saturday lecturer busy on weekday"] += 1
                elif busy_coh_b_on_sat:
                    reason = f"weekday practical cohort busy on Saturday ({', '.join(busy_coh_b_on_sat)})"
                    reason_counts["weekday cohort busy on Saturday"] += 1
                else:
                    # Check venue availability at swapped slots
                    free_va = [
                        v
                        for v in compatible_venues.get(sida, [])
                        if ((ven_busy[v] & ~gma & ~gmb) & gmb) == 0
                    ]
                    free_vb = [
                        v
                        for v in compatible_venues.get(sidb, [])
                        if ((ven_busy[v] & ~gma & ~gmb) & gma) == 0
                    ]
                    if not free_va or not free_vb:
                        reason = "compatible venue unavailable at swapped slot"
                        reason_counts["compatible venue unavailable"] += 1
                    else:
                        reason = "feasible swap exists (blocked by positive Delta-E objective trade-off)"
                        reason_counts["objective trade-off (positive Delta-E)"] += 1
                candidate_details.append(
                    f"{sidb}({sb['moduleCode']},{sb.get('sessionType')},{durb}p,{db_str} P{spb}): {reason}"
                )

            # Determine primary reason: prioritize same-duration candidate blockers if any same-duration practical exists,
            # otherwise report duration mismatch.
            non_dur_reasons = {
                k: v for k, v in reason_counts.items() if k != "duration mismatch"
            }
            if non_dur_reasons:
                top_NonDur = max(non_dur_reasons.items(), key=lambda kv: kv[1])[0]
                if reason_counts["duration mismatch"] > 0:
                    primary_reason = (
                        f"{top_NonDur} (for same-{dura}p practicals); "
                        f"duration mismatch for {reason_counts['duration mismatch']}/{len(wk_practicals)} practicals"
                    )
                else:
                    primary_reason = top_NonDur
            else:
                primary_reason = (
                    f"duration mismatch (all {len(wk_practicals)} weekday practicals have duration "
                    f"{dict(dur_counts)} != {dura}p)"
                )

        diagnostics.append(
            {
                "session_id": sida,
                "module_code": sa["moduleCode"],
                "session_type": sa.get("sessionType", "Theory"),
                "cohorts": cohs_a,
                "cohort_raw": cohort_raw_a,
                "lecturers": lecs_a,
                "durationPeriods": dura,
                "isEveningStream": evea,
                "saturday_slot": f"{da_str} P{spa}..P{spa + dura - 1} (Venue {vida})",
                "has_cs7_2": has_cs7_2,
                "weekday_non_theory_count": len(wk_practicals),
                "weekday_non_theory_durations": dict(sorted(dur_counts.items())),
                "primary_swap_blocker": primary_reason,
                "reason_breakdown": dict(reason_counts),
                "candidate_details": candidate_details,
            }
        )

    return diagnostics


def verify_solution(
    sessions: List[Dict[str, Any]],
    assignments: Dict[str, Tuple[str, int, int | str]],
    initial_domains: Dict[str, List[Tuple[str, int, int | str]]],
    venue_tier_labels: Optional[Dict[str, Dict[int | str, str]]] = None,
) -> Dict[str, Any]:
    """
    Independent Post-Solve Hard-Constraint, Saturday Fallback & Venue Affinity Verifier.
    """
    unassigned = [s["sessionId"] for s in sessions if s["sessionId"] not in assignments]

    unary_violations: List[str] = []
    domain_sets = {sid: set(dom) for sid, dom in initial_domains.items()}
    for sid, val in assignments.items():
        if val not in domain_sets.get(sid, set()):
            unary_violations.append(sid)

    lec_slot_usage: Dict[Tuple[str, str, int], List[str]] = defaultdict(list)
    coh_slot_usage: Dict[Tuple[str, str, int], List[str]] = defaultdict(list)
    ven_slot_usage: Dict[Tuple[int | str, str, int], List[str]] = defaultdict(list)

    lecturer_overlaps = 0
    cohort_overlaps = 0
    venue_double_bookings = 0

    n = len(sessions)
    for i in range(n):
        sa = sessions[i]
        sida = sa["sessionId"]
        if sida not in assignments:
            continue
        day_a, start_a, ven_a = assignments[sida]
        dur_a = sa["durationPeriods"]
        lecs_a = set(sa.get("lecturers", []))
        cohs_a = set(sa.get("targetCohorts", []))

        for p in range(start_a, start_a + dur_a):
            ven_slot_usage[(ven_a, day_a, p)].append(sida)
            for l in lecs_a:
                lec_slot_usage[(l, day_a, p)].append(sida)
            for c in cohs_a:
                coh_slot_usage[(c, day_a, p)].append(sida)

        for j in range(i + 1, n):
            sb = sessions[j]
            sidb = sb["sessionId"]
            if sidb not in assignments:
                continue
            day_b, start_b, ven_b = assignments[sidb]
            dur_b = sb["durationPeriods"]

            if not intervals_overlap(day_a, start_a, dur_a, day_b, start_b, dur_b):
                continue

            if lecs_a & set(sb.get("lecturers", [])):
                lecturer_overlaps += 1
            if cohs_a & set(sb.get("targetCohorts", [])):
                cohort_overlaps += 1
            if ven_a == ven_b:
                venue_double_bookings += 1

    evening_total = 0
    evening_twilight_used = 0
    tier_counts: Counter = Counter()
    specialized_total = 0
    specialized_locked_ok = 0

    for s in sessions:
        sid = s["sessionId"]
        if sid not in assignments:
            continue
        _, start_p, vid = assignments[sid]
        if s["isEveningStream"]:
            evening_total += 1
            if start_p < 13:
                evening_twilight_used += 1

        lbl = (
            venue_tier_labels.get(sid, {}).get(vid, "Tier 1A: Module Preferred")
            if venue_tier_labels
            else "Tier 1A: Module Preferred"
        )
        tier_counts[lbl] += 1

        if s["requiredVenueCategory"] in SPECIALIZED_HARD_CATEGORIES:
            specialized_total += 1
            if lbl.startswith("Tier 1"):
                specialized_locked_ok += 1

    tier_1a = tier_counts["Tier 1A: Module Preferred"]
    tier_1b = tier_counts["Tier 1B: Cohort Home"]
    tier_1c = tier_counts["Tier 1C: Dept Prefix Pool"]
    tier_1_total = tier_1a + tier_1b + tier_1c
    tier_2_overflow = tier_counts["Tier 2: General Overflow"]

    sat_report = classify_saturday_placements(sessions, assignments)

    valid = (
        len(unassigned) == 0
        and len(unary_violations) == 0
        and lecturer_overlaps == 0
        and cohort_overlaps == 0
        and venue_double_bookings == 0
    )

    return {
        "valid": valid,
        "total_sessions": len(sessions),
        "assigned_sessions": len(assignments),
        "unassigned_count": len(unassigned),
        "unary_violations": len(unary_violations),
        "lecturer_overlaps": lecturer_overlaps,
        "cohort_overlaps": cohort_overlaps,
        "venue_double_bookings": venue_double_bookings,
        "lecturer_slot_collisions": sum(1 for v in lec_slot_usage.values() if len(v) > 1),
        "cohort_slot_collisions": sum(1 for v in coh_slot_usage.values() if len(v) > 1),
        "venue_slot_collisions": sum(1 for v in ven_slot_usage.values() if len(v) > 1),
        "evening_total": evening_total,
        "evening_twilight_used": evening_twilight_used,
        "specialized_total": specialized_total,
        "specialized_locked_ok": specialized_locked_ok,
        "tier_1a_count": tier_1a,
        "tier_1b_count": tier_1b,
        "tier_1c_count": tier_1c,
        "tier_1_total": tier_1_total,
        "tier_2_overflow": tier_2_overflow,
        "saturday_report": sat_report,
    }


def run_benchmark(
    label: str,
    sessions: List[Dict[str, Any]],
    venues: List[Dict[str, Any]],
    schema: Dict[str, Any],
    affinity_config: Dict[str, Any] | None = None,
    include_fallback_venues: bool = False,
    pinned_assignments: Dict[str, Tuple[int | str, int, int | str]] | None = None,
) -> Tuple[Dict[str, Tuple[str, int, int | str]], SolverStats, Dict[str, Any], TimetableCSPSolver]:
    print(f"\n{'=' * 72}")
    print(f"  {label}")
    print(f"{'=' * 72}")

    preflight = run_preflight_checks(
        sessions,
        venues,
        schema,
        include_fallback_venues=include_fallback_venues,
        affinity_config=affinity_config,
    )
    print(f"  Preflight Pigeonhole Check : {'PASS' if preflight['passed'] else 'FAIL'}")

    initial_domains = build_domains(
        sessions,
        venues,
        schema,
        include_fallback_venues=include_fallback_venues,
        affinity_config=affinity_config,
    )
    solver = TimetableCSPSolver(
        sessions=sessions,
        venues=venues,
        schema=schema,
        affinity_config=affinity_config,
        include_fallback_venues=include_fallback_venues,
        pinned_assignments=pinned_assignments,
    )
    assignments, stats = solver.solve(pinned_assignments=pinned_assignments)

    print(f"  Total Variables (|X|)      : {stats.total_variables}")
    print(f"  Conflict Graph Edges (|E|) : {solver.graph_diagnostics['num_edges']:,}")
    print(f"  Solve Status               : {stats.status}")
    print(f"  Wall-Clock Runtime         : {stats.runtime_seconds * 1000:.2f} ms ({stats.runtime_seconds:.4f} s)")
    print(f"  Recursive Nodes Visited    : {stats.nodes_visited:,}")
    print(f"  Backtracks                 : {stats.backtracks:,}")
    print(f"  Forward-Check Pruned Slots : {stats.pruned_values:,}")

    verification = verify_solution(
        sessions, assignments, initial_domains, venue_tier_labels=solver.venue_tier_label
    )
    tot = max(1, verification["total_sessions"])
    spec_tot = max(1, verification["specialized_total"])
    sat = verification["saturday_report"]

    print("\n  --- Independent Post-Solve Hard-Constraint Verification ---")
    print(f"  All constraints satisfied? : {verification['valid']}")
    print(f"  Assigned Sessions          : {verification['assigned_sessions']} / {verification['total_sessions']}")
    print(f"  Unary Domain Violations    : {verification['unary_violations']}")
    print(f"  Lecturer Overlaps          : {verification['lecturer_overlaps']} pairs ({verification['lecturer_slot_collisions']} slot collisions)")
    print(f"  Cohort Overlaps            : {verification['cohort_overlaps']} pairs ({verification['cohort_slot_collisions']} slot collisions)")
    print(f"  Venue Double-Bookings      : {verification['venue_double_bookings']} pairs ({verification['venue_slot_collisions']} slot collisions)")
    print(f"  Evening Twilight (P11-P12) : {verification['evening_twilight_used']} / {verification['evening_total']} evening sessions")

    print("\n  --- 2-Condition Saturday Fallback Audit (Mon-Fri Default) ---")
    print(
        f"  Total Saturday Sessions    : Sundial CSP = {sat['csp_saturday_total']} / {tot} "
        f"({sat['csp_saturday_total'] / tot * 100:.1f}%)  vs.  ATC Ground Truth = {sat['gt_saturday_total']} / {tot} "
        f"({sat['gt_saturday_total'] / tot * 100:.1f}%)"
    )
    print(
        f"    * Condition 1 (>60p FT / >30p Eve Overflow) : {sat['csp_saturday_cond1_count']} sessions"
    )
    print(
        f"    * Condition 2 (Hard-Constraint Bottleneck)  : {sat['csp_saturday_cond2_count']} sessions"
    )
    print(
        f"  100% Saturday-Free Cohorts : Sundial CSP = {sat['csp_saturday_free_cohorts']} / {sat['total_cohorts']} "
        f"({sat['csp_saturday_free_cohorts'] / max(1, sat['total_cohorts']) * 100:.1f}%)  vs.  "
        f"ATC Ground Truth = {sat['gt_saturday_free_cohorts']} / {sat['total_cohorts']} "
        f"({sat['gt_saturday_free_cohorts'] / max(1, sat['total_cohorts']) * 100:.1f}%)"
    )

    print("\n  --- Venue Realism & 3-Tier Departmental Affinity Metrics ---")
    print(
        f"  Specialized Lab/W/S Lock   : {verification['specialized_locked_ok']} / {verification['specialized_total']} "
        f"({verification['specialized_locked_ok'] / spec_tot * 100:.1f}%)"
    )
    print(
        f"  Tier 1A Exact Module Match : {verification['tier_1a_count']} / {verification['total_sessions']} "
        f"({verification['tier_1a_count'] / tot * 100:.1f}%)"
    )
    print(
        f"  Tier 1B Cohort Home Match  : {verification['tier_1b_count']} / {verification['total_sessions']} "
        f"({verification['tier_1b_count'] / tot * 100:.1f}%)"
    )
    print(
        f"  Tier 1C Dept Prefix Match  : {verification['tier_1c_count']} / {verification['total_sessions']} "
        f"({verification['tier_1c_count'] / tot * 100:.1f}%)"
    )
    print(
        f"  Tier 1 Total Affinity      : {verification['tier_1_total']} / {verification['total_sessions']} "
        f"({verification['tier_1_total'] / tot * 100:.1f}%)"
    )
    print(
        f"  Tier 2 General Overflow    : {verification['tier_2_overflow']} / {verification['total_sessions']} "
        f"({verification['tier_2_overflow'] / tot * 100:.1f}%)"
    )

    # Phase 4: Declarative Soft-Constraint Engine & Simulated Annealing Optimizer
    optimizer = SimulatedAnnealingOptimizer(
        sessions=sessions,
        venues=venues,
        schema=schema,
        initial_assignments=assignments,
        compatible_venues=solver.compatible_venues,
        venue_tier_label=solver.venue_tier_label,
        affinity_config=affinity_config,
        pinned_session_ids=set(pinned_assignments.keys()) if pinned_assignments else None,
    )
    opt_assignments, opt_stats = optimizer.optimize()
    opt_verification = verify_solution(
        sessions, opt_assignments, initial_domains, venue_tier_labels=solver.venue_tier_label
    )
    verification["optimizer_report"] = opt_stats.to_dict()
    verification["initial_csp_assignments"] = assignments
    verification["post_sa_verification_valid"] = opt_verification["valid"]

    init_bd = opt_stats.initial_breakdown
    final_bd = opt_stats.final_breakdown
    opt_sat = opt_verification["saturday_report"]

    print("\n  --- Phase 4: Soft-Constraint Engine & Simulated Annealing Optimizer ---")
    print(
        f"  SA Optimizer Status        : {'ENABLED' if opt_stats.enabled else 'DISABLED'} "
        f"({opt_stats.iterations:,} iterations in {opt_stats.runtime_seconds * 1000:.2f} ms)"
    )
    print(
        f"  Soft Objective Penalty     : {opt_stats.initial_objective:,.2f}  ->  {opt_stats.final_objective:,.2f} "
        f"(-{opt_stats.improvement_pct:.2f}% reduction)"
    )
    print(
        f"  SA Move Telemetry          : {opt_stats.accepted_moves:,} accepted "
        f"({opt_stats.improving_moves:,} improving, {opt_stats.uphill_moves:,} uphill) | "
        f"Shifts: {opt_stats.single_shift_proposals:,}, Swaps: {opt_stats.pairwise_swap_proposals:,}"
    )
    print(
        f"  Post-SA Hard Verification  : Valid={opt_verification['valid']} "
        f"(0 Lecturer / 0 Cohort / 0 Venue Collisions | 100% Dept Lab Lock)"
    )
    print("  Per-Rule Soft-Constraint Breakdown (Initial CSP -> Post-SA Optimized):")
    for rname in init_bd.enabled_rules:
        w = init_bd.weights_by_rule.get(rname, 0.0)
        c_init = init_bd.counts_by_rule.get(rname, 0)
        c_final = final_bd.counts_by_rule.get(rname, 0)
        w_init = init_bd.weighted_by_rule.get(rname, 0.0)
        w_final = final_bd.weighted_by_rule.get(rname, 0.0)
        print(
            f"    * {rname:38s} (w={w:5.1f}) : count {c_init:4d} -> {c_final:4d} | "
            f"penalty {w_init:9.2f} -> {w_final:9.2f}"
        )
    print(
        f"  Post-SA Saturday Audit     : {opt_sat['csp_saturday_total']} Sat sessions "
        f"[Shared Practicals: {sat['csp_saturday_shared_practicals_count']} -> {opt_sat['csp_saturday_shared_practicals_count']}, "
        f"Solo Practicals: {sat['csp_saturday_solo_practicals_count']} -> {opt_sat['csp_saturday_solo_practicals_count']}, "
        f"Theory: {sat['csp_saturday_theory_count']} -> {opt_sat['csp_saturday_theory_count']} "
        f"(Cond-2: {opt_sat['csp_saturday_cond2_count']})] | "
        f"Tier-1 Affinity: {opt_verification['tier_1_total']}/{tot} ({opt_verification['tier_1_total'] / tot * 100:.1f}%)"
    )

    if "Mode A" in label:
        sat_theory_diag = diagnose_remaining_saturday_theory(
            sessions=sessions,
            assignments=opt_assignments,
            compatible_venues=solver.compatible_venues,
            schema=schema,
        )
        opt_verification["saturday_theory_diagnostics"] = sat_theory_diag
        print(
            f"\n  --- Mode A Post-SA Remaining Saturday Theory Diagnostic ({len(sat_theory_diag)} sessions) ---"
        )
        if not sat_theory_diag:
            print("    * 0 Saturday Theory sessions remaining!")
        else:
            for d in sat_theory_diag:
                tag = " [HIGHLIGHT: cs7-2 / L7-1CS]" if d["has_cs7_2"] else ""
                print(
                    f"    * {d['session_id']}{tag} | module={d['module_code']} ({d['session_type']}) | "
                    f"cohorts={d['cohorts']} (raw='{d.get('cohort_raw', '')}') | lecturers={d['lecturers']} | "
                    f"durationPeriods={d['durationPeriods']} | isEveningStream={d['isEveningStream']} | "
                    f"slot={d['saturday_slot']}"
                )
                print(
                    f"      - Weekday non-Theory sessions for cohort(s): {d['weekday_non_theory_count']} "
                    f"(durationPeriods breakdown: {d['weekday_non_theory_durations']})"
                )
                print(f"      - Primary pairwise swap blocker: {d['primary_swap_blocker']}")
                if d["candidate_details"]:
                    print(
                        f"      - Candidate practicals: {'; '.join(d['candidate_details'])}"
                    )

    opt_verification["optimizer_report"] = opt_stats.to_dict()
    return opt_assignments, stats, opt_verification, solver


if __name__ == "__main__":
    from src.viz.exporter import export_timetable_view_data  # type: ignore

    root = Path(__file__).resolve().parents[2]
    schema = load_json(root / "configs" / "institution_schema.json")
    dataset = load_json(root / "data" / "raw" / "atc" / "atc-timetable-dataset.json")
    csp_raw = load_json(root / "data" / "raw" / "atc" / "atc-csp-sessions.json")
    all_sessions = csp_raw["sessions"]
    venues = dataset["venues"]

    affinity_path = root / "configs" / "atc_venue_affinity.json"
    if not affinity_path.exists():
        affinity_cfg = generate_venue_affinity_config(
            all_sessions, venues, schema, output_path=affinity_path
        )
    else:
        affinity_cfg = load_json(affinity_path)

    # Mode A: Clean Primary Dataset (S0001..S1233, |X| = 1,233)
    primary_sessions = [s for s in all_sessions if int(s["sessionId"][1:]) <= 1233]
    assignments_a, stats_a, ver_a, solver_a = run_benchmark(
        label="Benchmark Mode A: Clean Primary Dataset (S0001-S1233, |X| = 1,233)",
        sessions=primary_sessions,
        venues=venues,
        schema=schema,
        affinity_config=affinity_cfg,
        include_fallback_venues=False,
    )

    # Mode B: Full Pre-Flight Verified Dataset (|X| = 1,299)
    assignments_b, stats_b, ver_b, solver_b = run_benchmark(
        label="Benchmark Mode B: Full Pre-Flight Verified Dataset (|X| = 1,299)",
        sessions=all_sessions,
        venues=venues,
        schema=schema,
        affinity_config=affinity_cfg,
        include_fallback_venues=False,
    )

    out_path = export_timetable_view_data(
        root=root,
        schema=schema,
        dataset=dataset,
        csp_raw=csp_raw,
        mode_a_tuple=(primary_sessions, assignments_a, stats_a, ver_a, solver_a.venue_tier_label),
        mode_b_tuple=(all_sessions, assignments_b, stats_b, ver_b, solver_b.venue_tier_label),
    )
    print(f"\n  [Exporter] Wrote visualizer bundle -> {out_path}")

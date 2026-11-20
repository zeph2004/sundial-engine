from __future__ import annotations

import math
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.csp.affinity import resolve_session_venues_and_tiers
from src.csp.domain import get_valid_time_slots


@dataclass
class SoftConstraintRule:
    """
    Pluggable soft-constraint evaluator specification.
    Institutions or researchers can register custom rules via `SoftConstraintEngine.register_rule(...)`
    or toggle/re-weight rules in `configs/institution_schema.json`.
    """

    name: str
    description: str
    scope: str  # "session" | "cohort_day" | "lecturer_day"
    default_weight: float = 1.0
    default_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SoftObjectiveBreakdown:
    """Detailed per-constraint penalty breakdown before or after optimization."""

    total_objective: float
    weighted_by_rule: Dict[str, float]
    raw_by_rule: Dict[str, float]
    counts_by_rule: Dict[str, int]
    weights_by_rule: Dict[str, float]
    enabled_rules: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "totalObjective": round(self.total_objective, 2),
            "weightedByRule": {k: round(v, 2) for k, v in self.weighted_by_rule.items()},
            "rawByRule": {k: round(v, 2) for k, v in self.raw_by_rule.items()},
            "countsByRule": dict(self.counts_by_rule),
            "weightsByRule": {k: round(v, 2) for k, v in self.weights_by_rule.items()},
            "enabledRules": list(self.enabled_rules),
        }


@dataclass
class OptimizerStats:
    """Telemetry and objective improvements produced by SimulatedAnnealingOptimizer."""

    enabled: bool
    iterations: int
    runtime_seconds: float
    initial_objective: float
    final_objective: float
    best_objective: float
    improvement_pct: float
    accepted_moves: int
    improving_moves: int
    uphill_moves: int
    rejected_moves: int
    single_shift_proposals: int
    pairwise_swap_proposals: int
    initial_breakdown: SoftObjectiveBreakdown
    final_breakdown: SoftObjectiveBreakdown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "iterations": self.iterations,
            "runtimeMs": round(self.runtime_seconds * 1000.0, 2),
            "initialObjective": round(self.initial_objective, 2),
            "finalObjective": round(self.final_objective, 2),
            "bestObjective": round(self.best_objective, 2),
            "improvementPct": round(self.improvement_pct, 2),
            "acceptedMoves": self.accepted_moves,
            "improvingMoves": self.improving_moves,
            "uphillMoves": self.uphill_moves,
            "rejectedMoves": self.rejected_moves,
            "singleShiftProposals": self.single_shift_proposals,
            "pairwiseSwapProposals": self.pairwise_swap_proposals,
            "initialBreakdown": self.initial_breakdown.to_dict(),
            "finalBreakdown": self.final_breakdown.to_dict(),
        }


# Pluggable Soft-Constraint Decorator Registry
REGISTERED_SOFT_CONSTRAINTS: Dict[str, SoftConstraintRule] = {}


def register_soft_constraint(
    name: str,
    description: str = "",
    scope: str = "session",
    default_weight: float = 1.0,
    default_params: Optional[Dict[str, Any]] = None,
    delta_fn: Optional[Callable[..., float]] = None,
) -> Callable[[Callable[..., float]], Callable[..., float]]:
    """
    Decorator for registering pluggable soft-constraint rules (and optional O(1) delta_fn).
    """

    def _decorator(fn: Callable[..., float]) -> Callable[..., float]:
        rule = SoftConstraintRule(
            name=name,
            description=description or (fn.__doc__ or "").strip(),
            scope=scope,
            default_weight=default_weight,
            default_params=dict(default_params or {}),
        )
        setattr(fn, "_soft_constraint_rule", rule)
        setattr(fn, "delta_fn", delta_fn)
        REGISTERED_SOFT_CONSTRAINTS[name] = rule
        return fn

    return _decorator


@register_soft_constraint(
    "prefer_shared_practicals_on_saturday",
    description=(
        "Prefers multi-cohort Shared Practicals on Saturday (0 penalty) over Solo Practicals "
        "(1x duration) and Theory sessions (2x duration)."
    ),
    scope="session",
    default_weight=80.0,
    default_params={
        "theory_types": ["Theory", "Lecture", "Tutorial"],
        "min_shared_cohorts": 2,
        "solo_practical_multiplier": 1.0,
        "theory_multiplier": 2.0,
    },
)
def evaluate_prefer_shared_practicals_on_saturday(
    day_idx: int,
    saturday_idx: int,
    is_theory: bool,
    num_cohorts: int,
    duration: int,
    min_shared_cohorts: int = 2,
    solo_practical_multiplier: float = 1.0,
    theory_multiplier: float = 2.0,
) -> float:
    """
    Computes raw penalty for `prefer_shared_practicals_on_saturday`:
      - Not on Saturday (`day_idx != saturday_idx`): 0.0
      - Shared Practical (`not is_theory` and `num_cohorts >= min_shared_cohorts`): 0.0
      - Solo Practical (`not is_theory` and `num_cohorts < min_shared_cohorts`): `solo_practical_multiplier * duration`
      - Theory (`is_theory`): `theory_multiplier * duration`
    """
    if day_idx != saturday_idx:
        return 0.0
    if is_theory:
        return theory_multiplier * float(duration)
    if num_cohorts >= min_shared_cohorts:
        return 0.0
    return solo_practical_multiplier * float(duration)


def delta_prefer_shared_practicals_on_saturday(
    old_day_idx: int,
    new_day_idx: int,
    saturday_idx: int,
    raw_saturday_penalty: float,
    weight: float,
) -> float:
    """O(1) incremental delta_fn for `prefer_shared_practicals_on_saturday`."""
    if old_day_idx == new_day_idx or weight == 0.0 or raw_saturday_penalty == 0.0:
        return 0.0
    if new_day_idx == saturday_idx:
        return weight * raw_saturday_penalty
    if old_day_idx == saturday_idx:
        return -weight * raw_saturday_penalty
    return 0.0


class SoftConstraintEngine:
    """
    Declarative, Pluggable Soft-Constraint Engine.
    Reads `"soft_constraints"` from `configs/institution_schema.json` and supports:
      1. `minimize_saturday_theory`: Penalizes Theory/Lecture/Tutorial sessions placed on Saturday.
      2. `minimize_saturday_overflow`: Penalizes any session (per period) placed on Saturday.
      3. `prefer_shared_practicals_on_saturday`: Penalizes Theory (2x) and Solo Practicals (1x) on Saturday while allowing Shared Practicals (>=2 cohorts) at 0 penalty.
      4. `minimize_evening_twilight`: Penalizes evening sessions occupying twilight buffer periods (P11-P12).
      5. `minimize_cohort_idle_gaps`: Penalizes idle periods and distinct gaps between a cohort's first and last class of the day (with weekday breathing room `allowed_weekday_free_gaps`).
      6. `balance_weekly_workload`: Balances a cohort's or lecturer's weekly teaching load evenly across active days by penalizing deviations above their ideal daily average (`ceil(total_weekly_periods / target_days)`).
      7. `prefer_exact_module_venue`: Penalizes non-1A venue tiers (1B Cohort Home, 1C Dept Pool, Tier 2 General Overflow).
    Also supports registering custom pluggable session-level or day-level rules at runtime.
    """

    BUILTIN_RULE_ORDER: Tuple[str, ...] = (
        "minimize_saturday_theory",
        "minimize_saturday_overflow",
        "prefer_shared_practicals_on_saturday",
        "minimize_evening_twilight",
        "minimize_cohort_idle_gaps",
        "balance_weekly_workload",
        "prefer_exact_module_venue",
    )

    def __init__(
        self,
        sessions: List[Dict[str, Any]],
        venues: List[Dict[str, Any]],
        schema: Dict[str, Any],
        venue_tier_label: Optional[Dict[str, Dict[int | str, str]]] = None,
        affinity_config: Optional[Dict[str, Any]] = None,
        include_fallback_venues: bool = False,
    ) -> None:
        self.sessions = sessions
        self.venues = venues
        self.schema = schema
        self.session_by_id: Dict[str, Dict[str, Any]] = {s["sessionId"]: s for s in sessions}

        grid = schema["calendar_grid"]
        self.active_days: List[str] = list(grid["active_days"])
        self.periods_per_day: int = int(grid.get("periods_per_day", 18))
        self.day_to_idx: Dict[str, int] = {d: i for i, d in enumerate(self.active_days)}
        self.num_days: int = len(self.active_days)
        self.saturday_idx: int = self.day_to_idx.get("SATURDAY", 5)

        if venue_tier_label is None:
            venue_tier_label = {}
            for s in sessions:
                _, t_labels, _ = resolve_session_venues_and_tiers(
                    session=s,
                    venues=venues,
                    schema=schema,
                    affinity_config=affinity_config,
                    include_fallbacks=include_fallback_venues,
                )
                venue_tier_label[s["sessionId"]] = t_labels
        self.venue_tier_label: Dict[str, Dict[int | str, str]] = venue_tier_label

        # Parse soft_constraints configuration from schema
        raw_sc = schema.get("soft_constraints", {})
        self.rule_configs: Dict[str, Dict[str, Any]] = {}
        for rname in self.BUILTIN_RULE_ORDER:
            cfg = raw_sc.get(rname, {})
            self.rule_configs[rname] = {
                "enabled": bool(cfg.get("enabled", True)),
                "weight": float(cfg.get("weight", 1.0)),
                "params": dict(cfg.get("params", {})),
            }

        # Pluggable custom rules registry:
        # name -> (weight, enabled, fn(sid, day, start_p, vid, session) -> float)
        self.custom_session_rules: Dict[
            str, Tuple[float, bool, Callable[[str, str, int, int | str, Dict[str, Any]], float]]
        ] = {}

        # Extract fast lookup parameters for built-in rules
        c_sat_th = self.rule_configs["minimize_saturday_theory"]
        self.w_sat_theory: float = c_sat_th["weight"] if c_sat_th["enabled"] else 0.0
        self.theory_types: Set[str] = set(
            c_sat_th["params"].get("theory_types", ["Theory", "Lecture", "Tutorial"])
        )

        c_sat_ov = self.rule_configs["minimize_saturday_overflow"]
        self.w_sat_overflow: float = c_sat_ov["weight"] if c_sat_ov["enabled"] else 0.0

        c_sat_sp = self.rule_configs["prefer_shared_practicals_on_saturday"]
        self.w_sat_shared_prac: float = c_sat_sp["weight"] if c_sat_sp["enabled"] else 0.0
        self.sat_sp_theory_types: Set[str] = set(
            c_sat_sp["params"].get("theory_types", ["Theory", "Lecture", "Tutorial"])
        )
        self.min_shared_cohorts: int = int(c_sat_sp["params"].get("min_shared_cohorts", 2))
        self.solo_practical_multiplier: float = float(
            c_sat_sp["params"].get("solo_practical_multiplier", 1.0)
        )
        self.theory_multiplier: float = float(
            c_sat_sp["params"].get("theory_multiplier", 2.0)
        )

        c_twi = self.rule_configs["minimize_evening_twilight"]
        self.w_twilight: float = c_twi["weight"] if c_twi["enabled"] else 0.0
        self.twilight_periods: Set[int] = set(
            int(p) for p in c_twi["params"].get("twilight_periods", [11, 12])
        )
        self.twilight_day_mask: int = 0
        for p in self.twilight_periods:
            if 1 <= p <= self.periods_per_day:
                self.twilight_day_mask |= 1 << (p - 1)

        c_gaps = self.rule_configs["minimize_cohort_idle_gaps"]
        self.w_idle_gaps: float = c_gaps["weight"] if c_gaps["enabled"] else 0.0
        self.allowed_weekday_free_gaps: int = int(
            c_gaps["params"].get("allowed_weekday_free_gaps", 2)
        )

        c_bal = self.rule_configs["balance_weekly_workload"]
        self.w_workload: float = c_bal["weight"] if c_bal["enabled"] else 0.0
        self.cohort_workload_weight: float = float(
            c_bal["params"].get("cohort_weight", 1.0)
        )
        self.lecturer_workload_weight: float = float(
            c_bal["params"].get("lecturer_weight", 0.5)
        )
        self.cohort_ft_max_periods: int = int(
            c_bal["params"].get("cohort_ft_max_periods", 8)
        )
        self.cohort_eve_max_periods: int = int(
            c_bal["params"].get("cohort_eve_max_periods", 4)
        )
        self.lecturer_max_periods: int = int(
            c_bal["params"].get("lecturer_max_periods", 6)
        )
        self.min_weekday_free_periods: int = int(
            c_bal["params"].get("min_weekday_free_periods", 2)
        )
        streams_cfg = schema.get("streams", {})
        ft_cfg = streams_cfg.get("full_time", {})
        eve_cfg = streams_cfg.get("evening", {})
        self.ft_stream_daily_periods: int = int(
            ft_cfg.get("max_period", 12) - ft_cfg.get("min_period", 1) + 1
        )
        self.eve_stream_daily_periods: int = int(
            eve_cfg.get("max_period", 18) - eve_cfg.get("min_period", 13) + 1
        )
        self.cohort_ft_weekday_max_periods: int = max(
            1, self.ft_stream_daily_periods - self.min_weekday_free_periods
        )
        self.cohort_eve_weekday_max_periods: int = max(
            1, self.eve_stream_daily_periods - self.min_weekday_free_periods
        )
        self.lecturer_weekday_max_periods: int = max(
            1, self.ft_stream_daily_periods - self.min_weekday_free_periods
        )

        c_ven = self.rule_configs["prefer_exact_module_venue"]
        self.w_venue_tier: float = c_ven["weight"] if c_ven["enabled"] else 0.0
        raw_tp = c_ven["params"].get(
            "tier_penalties", {"1A": 0.0, "1B": 1.0, "1C": 2.0, "2": 5.0}
        )
        self.tier_penalties: Dict[str, float] = {
            "1A": float(raw_tp.get("1A", 0.0)),
            "1B": float(raw_tp.get("1B", 1.0)),
            "1C": float(raw_tp.get("1C", 2.0)),
            "2": float(raw_tp.get("2", 5.0)),
        }

        # Precompute 18-bit day mask LUT for O(1) idle gap and daily workload evaluation!
        # Since periods_per_day == 18 (262,144 states) or we can compute on demand with a cache:
        self._day_mask_gap_info: Dict[int, Tuple[int, int, int]] = {0: (0, 0, 0)}
        # (busy_periods, distinct_idle_gaps, total_idle_gap_periods)

        # Catalog cohorts and lecturers and compute adaptive weekly workload targets
        self.cohort_is_evening: Dict[str, bool] = {}
        self.all_cohorts: List[str] = []
        self.all_lecturers: List[str] = []
        self.cohort_total_weekly_periods: Dict[str, int] = defaultdict(int)
        self.cohort_6p_blocks: Dict[str, int] = defaultdict(int)
        self.lecturer_total_weekly_periods: Dict[str, int] = defaultdict(int)
        coh_set: Set[str] = set()
        lec_set: Set[str] = set()
        for s in sessions:
            is_eve = bool(s.get("isEveningStream", False))
            dur = int(s["durationPeriods"])
            for c in s.get("targetCohorts", []):
                if c not in coh_set:
                    coh_set.add(c)
                    self.all_cohorts.append(c)
                if is_eve or c.endswith("-E"):
                    self.cohort_is_evening[c] = True
                elif c not in self.cohort_is_evening:
                    self.cohort_is_evening[c] = False
                self.cohort_total_weekly_periods[c] += dur
                if dur == 6:
                    self.cohort_6p_blocks[c] += 1
            for l in s.get("lecturers", []):
                if l not in lec_set:
                    lec_set.add(l)
                    self.all_lecturers.append(l)
                self.lecturer_total_weekly_periods[l] += dur

        self.all_cohorts.sort()
        self.all_lecturers.sort()

        # Precompute per-cohort and per-lecturer daily target cap for balance_weekly_workload:
        # Ideal daily load = ceil(total_weekly_periods / target_active_days) (5 days for Mon-Fri cohorts, 6 for Cond-1 Saturday cohorts),
        # capped on weekdays by the stream's free-period floor (stream_daily_periods - min_weekday_free_periods).
        self.cohort_daily_target: Dict[str, int] = {}
        self.cohort_weekday_target: Dict[str, int] = {}
        for c in self.all_cohorts:
            is_eve_c = self.cohort_is_evening.get(c, False)
            tot_p = self.cohort_total_weekly_periods[c]
            is_cond1 = (
                (tot_p > 30)
                if is_eve_c
                else (tot_p > 60 or self.cohort_6p_blocks[c] > 5)
            )
            spread_days = 6 if is_cond1 else 5
            ideal_daily = max(1, math.ceil(tot_p / spread_days))
            wk_floor_cap = (
                self.cohort_eve_weekday_max_periods
                if is_eve_c
                else self.cohort_ft_weekday_max_periods
            )
            self.cohort_daily_target[c] = ideal_daily
            self.cohort_weekday_target[c] = min(ideal_daily, wk_floor_cap)

        self.lecturer_daily_target: Dict[str, int] = {}
        self.lecturer_weekday_target: Dict[str, int] = {}
        for l in self.all_lecturers:
            tot_p = self.lecturer_total_weekly_periods[l]
            spread_days = 6 if tot_p > 50 else 5
            ideal_daily = max(self.lecturer_max_periods, math.ceil(tot_p / spread_days))
            self.lecturer_daily_target[l] = ideal_daily
            self.lecturer_weekday_target[l] = min(
                ideal_daily, self.lecturer_weekday_max_periods
            )

        # Precompute per-session venue penalty multiplier for every (sid, vid)
        self.session_venue_raw_penalty: Dict[str, Dict[int | str, float]] = {}
        self.session_is_theory: Dict[str, bool] = {}
        self.session_is_evening: Dict[str, bool] = {}
        self.session_duration: Dict[str, int] = {}
        self.session_num_cohorts: Dict[str, int] = {}
        self.session_is_shared_practical: Dict[str, bool] = {}
        self.session_is_solo_practical: Dict[str, bool] = {}
        self.session_sat_shared_prac_raw_penalty: Dict[str, float] = {}

        for s in sessions:
            sid = s["sessionId"]
            stype = s.get("sessionType", "Theory")
            is_th = stype in self.theory_types
            is_sp_th = stype in self.sat_sp_theory_types
            dur = int(s["durationPeriods"])
            ncoh = len(s.get("targetCohorts", []))

            self.session_is_theory[sid] = is_th
            self.session_is_evening[sid] = bool(s.get("isEveningStream", False))
            self.session_duration[sid] = dur
            self.session_num_cohorts[sid] = ncoh
            self.session_is_shared_practical[sid] = (not is_sp_th) and (
                ncoh >= self.min_shared_cohorts
            )
            self.session_is_solo_practical[sid] = (not is_sp_th) and (
                ncoh < self.min_shared_cohorts
            )
            self.session_sat_shared_prac_raw_penalty[sid] = (
                evaluate_prefer_shared_practicals_on_saturday(
                    day_idx=self.saturday_idx,
                    saturday_idx=self.saturday_idx,
                    is_theory=is_sp_th,
                    num_cohorts=ncoh,
                    duration=dur,
                    min_shared_cohorts=self.min_shared_cohorts,
                    solo_practical_multiplier=self.solo_practical_multiplier,
                    theory_multiplier=self.theory_multiplier,
                )
            )

            v_pen: Dict[int | str, float] = {}
            for vid, lbl in self.venue_tier_label.get(sid, {}).items():
                if lbl.startswith("Tier 1A"):
                    v_pen[vid] = self.tier_penalties["1A"]
                elif lbl.startswith("Tier 1B"):
                    v_pen[vid] = self.tier_penalties["1B"]
                elif lbl.startswith("Tier 1C"):
                    v_pen[vid] = self.tier_penalties["1C"]
                else:
                    v_pen[vid] = self.tier_penalties["2"]
            self.session_venue_raw_penalty[sid] = v_pen

    def register_custom_session_rule(
        self,
        name: str,
        weight: float,
        evaluator: Callable[[str, str, int, int | str, Dict[str, Any]], float],
        enabled: bool = True,
    ) -> None:
        """
        Registers a custom pluggable session-level soft constraint rule at runtime.
        `evaluator(sid, day, start_period, venue_id, session_dict) -> raw_penalty_float`.
        """
        self.custom_session_rules[name] = (float(weight), bool(enabled), evaluator)
        self.rule_configs[name] = {
            "enabled": bool(enabled),
            "weight": float(weight),
            "params": {},
        }

    def analyze_day_mask(self, day_mask: int) -> Tuple[int, int, int]:
        """
        Given an 18-bit integer mask representing occupied periods on a single day,
        returns `(busy_periods, distinct_idle_gaps, total_idle_gap_periods)` in O(1) amortized time.
        """
        cached = self._day_mask_gap_info.get(day_mask)
        if cached is not None:
            return cached

        busy = day_mask.bit_count()
        if busy <= 1:
            res = (busy, 0, 0)
            self._day_mask_gap_info[day_mask] = res
            return res

        # Lowest set bit index (0-based) and highest set bit index (0-based)
        lowest_bit = (day_mask & -day_mask).bit_length() - 1
        highest_bit = day_mask.bit_length() - 1
        span = highest_bit - lowest_bit + 1
        idle_periods = span - busy
        if idle_periods == 0:
            res = (busy, 0, 0)
            self._day_mask_gap_info[day_mask] = res
            return res

        # Count distinct contiguous zero-runs strictly inside [lowest_bit, highest_bit]
        shifted = day_mask >> lowest_bit
        # A 1->0 transition inside [0, span-1] starts a new gap
        distinct_gaps = 0
        in_gap = False
        for bit_pos in range(span):
            if ((shifted >> bit_pos) & 1) == 0:
                if not in_gap:
                    distinct_gaps += 1
                    in_gap = True
            else:
                in_gap = False

        res = (busy, distinct_gaps, idle_periods)
        self._day_mask_gap_info[day_mask] = res
        return res

    def cohort_idle_gaps_raw_and_count(
        self, day_mask: int, day_idx: int = 0
    ) -> Tuple[float, int]:
        """
        Computes `(raw_penalty, penalized_gap_count)` for `minimize_cohort_idle_gaps` on `(cohort, day_idx)`:
          - On weekdays (`day_idx < 5`), allows up to `allowed_weekday_free_gaps` free/idle periods
            between a cohort's first and last class with 0 penalty:
            `penalized_gaps = max(0, gaps - allowed_weekday_free_gaps)`
          - On Saturday (`day_idx == 5`), keeps `penalized_gaps = gaps`.
        """
        if day_mask == 0:
            return 0.0, 0
        _, distinct_gaps, idle_periods = self.analyze_day_mask(day_mask)
        if idle_periods <= 0:
            return 0.0, 0
        if day_idx < 5:
            penalized_gaps = max(0, idle_periods - self.allowed_weekday_free_gaps)
            if penalized_gaps <= 0:
                return 0.0, 0
            return distinct_gaps + 0.25 * float(penalized_gaps), distinct_gaps
        else:
            penalized_gaps = idle_periods
            return distinct_gaps + 0.25 * float(penalized_gaps), distinct_gaps

    def cohort_day_cost(
        self,
        day_mask: int,
        is_evening_cohort: bool,
        day_idx: int = 0,
        cohort_id: Optional[str] = None,
    ) -> float:
        """
        Computes the weighted soft penalty for a single `(cohort, day_idx)` 18-bit occupancy mask:
          - `minimize_cohort_idle_gaps`: `w_idle_gaps * (distinct_gaps + 0.25 * penalized_gaps)`
            (0 when `penalized_gaps == 0`, with weekday breathing room `allowed_weekday_free_gaps`)
          - `balance_weekly_workload`: `w_workload * cohort_weight * max(0, busy_periods - target_daily_periods)`
        """
        if day_mask == 0:
            return 0.0
        busy, distinct_gaps, idle_periods = self.analyze_day_mask(day_mask)
        cost = 0.0
        if self.w_idle_gaps > 0.0 and idle_periods > 0:
            penalized_gaps = (
                max(0, idle_periods - self.allowed_weekday_free_gaps)
                if day_idx < 5
                else idle_periods
            )
            if penalized_gaps > 0:
                cost += self.w_idle_gaps * (distinct_gaps + 0.25 * float(penalized_gaps))
        if self.w_workload > 0.0 and self.cohort_workload_weight > 0.0:
            if cohort_id is not None and cohort_id in self.cohort_daily_target:
                max_p = (
                    self.cohort_weekday_target[cohort_id]
                    if day_idx < 5
                    else self.cohort_daily_target[cohort_id]
                )
            elif day_idx < 5:
                max_p = (
                    self.cohort_eve_weekday_max_periods
                    if is_evening_cohort
                    else self.cohort_ft_weekday_max_periods
                )
            else:
                max_p = (
                    self.cohort_eve_max_periods
                    if is_evening_cohort
                    else self.cohort_ft_max_periods
                )
            if busy > max_p:
                excess = busy - max_p
                cost += self.w_workload * self.cohort_workload_weight * float(excess)
        return cost

    def cohort_day_delta_fn(
        self,
        old_mask: int,
        new_mask: int,
        is_evening_cohort: bool,
        day_idx: int = 0,
        cohort_id: Optional[str] = None,
    ) -> float:
        """O(1) delta_fn for `(cohort, day_idx)` idle gaps + weekly workload balance."""
        if old_mask == new_mask:
            return 0.0
        return self.cohort_day_cost(
            new_mask, is_evening_cohort, day_idx, cohort_id
        ) - self.cohort_day_cost(old_mask, is_evening_cohort, day_idx, cohort_id)

    def lecturer_day_cost(
        self,
        day_mask: int,
        day_idx: int = 0,
        lecturer_id: Optional[str] = None,
    ) -> float:
        """
        Computes the weighted soft penalty for a single `(lecturer, day_idx)` 18-bit occupancy mask:
          - `balance_weekly_workload`: `w_workload * lecturer_weight * max(0, busy_periods - target_lecturer_periods)`
        """
        if day_mask == 0 or self.w_workload <= 0.0 or self.lecturer_workload_weight <= 0.0:
            return 0.0
        busy = day_mask.bit_count()
        if lecturer_id is not None and lecturer_id in self.lecturer_daily_target:
            max_p = (
                self.lecturer_weekday_target[lecturer_id]
                if day_idx < 5
                else self.lecturer_daily_target[lecturer_id]
            )
        else:
            max_p = (
                self.lecturer_weekday_max_periods
                if day_idx < 5
                else self.lecturer_max_periods
            )
        if busy > max_p:
            excess = busy - max_p
            return self.w_workload * self.lecturer_workload_weight * float(excess)
        return 0.0

    def lecturer_day_delta_fn(
        self,
        old_mask: int,
        new_mask: int,
        day_idx: int = 0,
        lecturer_id: Optional[str] = None,
    ) -> float:
        """O(1) delta_fn for `(lecturer, day_idx)` weekly workload balance."""
        if old_mask == new_mask:
            return 0.0
        return self.lecturer_day_cost(
            new_mask, day_idx, lecturer_id
        ) - self.lecturer_day_cost(old_mask, day_idx, lecturer_id)

    def session_placement_cost(
        self,
        sid: str,
        day_idx: int,
        start_p: int,
        vid: int | str,
        day_local_mask: int,
    ) -> float:
        """
        Computes the weighted unary session placement penalty for `sid` at `(day_idx, start_p, vid)`:
          - `minimize_saturday_theory`
          - `minimize_saturday_overflow`
          - `prefer_shared_practicals_on_saturday`
          - `minimize_evening_twilight`
          - `prefer_exact_module_venue`
          - plus any registered custom session rules.
        """
        dur = self.session_duration[sid]
        cost = 0.0

        if day_idx == self.saturday_idx:
            if self.w_sat_theory > 0.0 and self.session_is_theory[sid]:
                cost += self.w_sat_theory * float(dur)
            if self.w_sat_overflow > 0.0:
                cost += self.w_sat_overflow * float(dur)
            if self.w_sat_shared_prac > 0.0:
                raw_sp = self.session_sat_shared_prac_raw_penalty[sid]
                if raw_sp > 0.0:
                    cost += self.w_sat_shared_prac * raw_sp

        if self.w_twilight > 0.0 and self.session_is_evening[sid]:
            twi_periods = (day_local_mask & self.twilight_day_mask).bit_count()
            if twi_periods > 0:
                cost += self.w_twilight * float(twi_periods)

        if self.w_venue_tier > 0.0:
            raw_vpen = self.session_venue_raw_penalty[sid].get(vid, 0.0)
            if raw_vpen > 0.0:
                cost += self.w_venue_tier * raw_vpen * float(dur)

        if self.custom_session_rules:
            day_str = self.active_days[day_idx]
            s_dict = self.session_by_id[sid]
            for _, (w, enabled, fn) in self.custom_session_rules.items():
                if enabled and w != 0.0:
                    cost += w * fn(sid, day_str, start_p, vid, s_dict)

        return cost

    def evaluate_full_breakdown(
        self,
        assignments: Dict[str, Tuple[str, int, int | str]],
    ) -> SoftObjectiveBreakdown:
        """
        Evaluates the full schedule from scratch and returns a comprehensive
        `SoftObjectiveBreakdown` across all enabled soft constraints.
        """
        raw_by_rule: Dict[str, float] = {k: 0.0 for k in self.rule_configs}
        counts_by_rule: Dict[str, int] = {k: 0 for k in self.rule_configs}
        weights_by_rule: Dict[str, float] = {
            k: float(cfg["weight"]) if cfg["enabled"] else 0.0
            for k, cfg in self.rule_configs.items()
        }
        enabled_rules = [k for k, cfg in self.rule_configs.items() if cfg["enabled"]]

        cohort_day_masks: Dict[Tuple[str, int], int] = defaultdict(int)
        lecturer_day_masks: Dict[Tuple[str, int], int] = defaultdict(int)

        for s in self.sessions:
            sid = s["sessionId"]
            if sid not in assignments:
                continue
            day_str, start_p, vid = assignments[sid]
            d_idx = self.day_to_idx[day_str]
            dur = self.session_duration[sid]
            local_mask = ((1 << dur) - 1) << (start_p - 1)

            for c in s.get("targetCohorts", []):
                cohort_day_masks[(c, d_idx)] |= local_mask
            for l in s.get("lecturers", []):
                lecturer_day_masks[(l, d_idx)] |= local_mask

            # 1. minimize_saturday_theory, 2. minimize_saturday_overflow & 3. prefer_shared_practicals_on_saturday
            if d_idx == self.saturday_idx:
                if self.session_is_theory[sid]:
                    raw_by_rule["minimize_saturday_theory"] += float(dur)
                    counts_by_rule["minimize_saturday_theory"] += 1
                raw_by_rule["minimize_saturday_overflow"] += float(dur)
                counts_by_rule["minimize_saturday_overflow"] += 1
                raw_sp = self.session_sat_shared_prac_raw_penalty[sid]
                if raw_sp > 0.0:
                    raw_by_rule["prefer_shared_practicals_on_saturday"] += raw_sp
                    counts_by_rule["prefer_shared_practicals_on_saturday"] += 1

            # 4. minimize_evening_twilight
            if self.session_is_evening[sid]:
                twi_periods = (local_mask & self.twilight_day_mask).bit_count()
                if twi_periods > 0:
                    raw_by_rule["minimize_evening_twilight"] += float(twi_periods)
                    counts_by_rule["minimize_evening_twilight"] += 1

            # 7. prefer_exact_module_venue
            raw_vpen = self.session_venue_raw_penalty[sid].get(vid, 0.0)
            if raw_vpen > 0.0:
                raw_by_rule["prefer_exact_module_venue"] += raw_vpen * float(dur)
                counts_by_rule["prefer_exact_module_venue"] += 1

            # Custom session rules
            for cname, (w, enabled, fn) in self.custom_session_rules.items():
                val = fn(sid, day_str, start_p, vid, s)
                if val > 0.0:
                    raw_by_rule[cname] += val
                    counts_by_rule[cname] += 1

        # 5. minimize_cohort_idle_gaps & 6a. cohort weekly workload balance
        for c in self.all_cohorts:
            for d_idx in range(self.num_days):
                d_mask = cohort_day_masks.get((c, d_idx), 0)
                if d_mask == 0:
                    continue
                busy, _, _ = self.analyze_day_mask(d_mask)
                gap_raw, gap_cnt = self.cohort_idle_gaps_raw_and_count(d_mask, d_idx)
                if gap_raw > 0.0:
                    raw_by_rule["minimize_cohort_idle_gaps"] += gap_raw
                    counts_by_rule["minimize_cohort_idle_gaps"] += gap_cnt
                max_p = (
                    self.cohort_weekday_target[c]
                    if d_idx < 5
                    else self.cohort_daily_target[c]
                )
                if busy > max_p and self.cohort_workload_weight > 0.0:
                    excess = busy - max_p
                    raw_by_rule["balance_weekly_workload"] += (
                        self.cohort_workload_weight * float(excess)
                    )
                    counts_by_rule["balance_weekly_workload"] += 1

        # 6b. lecturer weekly workload balance
        for l in self.all_lecturers:
            for d_idx in range(self.num_days):
                d_mask = lecturer_day_masks.get((l, d_idx), 0)
                if d_mask == 0:
                    continue
                busy = d_mask.bit_count()
                max_p = (
                    self.lecturer_weekday_target[l]
                    if d_idx < 5
                    else self.lecturer_daily_target[l]
                )
                if busy > max_p and self.lecturer_workload_weight > 0.0:
                    excess = busy - max_p
                    raw_by_rule["balance_weekly_workload"] += (
                        self.lecturer_workload_weight * float(excess)
                    )
                    counts_by_rule["balance_weekly_workload"] += 1

        weighted_by_rule: Dict[str, float] = {}
        total_obj = 0.0
        for rname, raw_val in raw_by_rule.items():
            w = weights_by_rule.get(rname, 0.0)
            w_val = w * raw_val
            weighted_by_rule[rname] = w_val
            total_obj += w_val

        return SoftObjectiveBreakdown(
            total_objective=total_obj,
            weighted_by_rule=weighted_by_rule,
            raw_by_rule=raw_by_rule,
            counts_by_rule=counts_by_rule,
            weights_by_rule=weights_by_rule,
            enabled_rules=enabled_rules,
        )


class SimulatedAnnealingOptimizer:
    """
    Phase 4 Hard-Constraint-Preserving Simulated Annealing Optimizer.

    Maintains 108-bit integer occupancy bitmasks for every Venue, Lecturer, and Cohort,
    plus 18-bit per-day occupancy bitmasks (`(entity, day_idx)`) for incremental O(1)
    Delta-E evaluation.

    Neighborhood Operators (100% hard-constraint preserving):
      1. Guided / Random Single-Session Move (`(day, start_p, venue_id)`):
         Moves a session to a clash-free time slot and selects the highest-affinity free
         venue in its compatible pool.
      2. Same-Duration / Compatible-Pool Pairwise Swap (`swap(x_i, x_j)`):
         Swaps the assigned `(day, start_p)` of two sessions `x_i, x_j` (releasing `x_i`
         and `x_j`'s bitmasks first before checking feasibility and picking each session's
         best available compatible venue at the swapped time slot). This allows escaping
         tightly packed local minima where single moves are blocked!
    """

    def __init__(
        self,
        sessions: List[Dict[str, Any]],
        venues: List[Dict[str, Any]],
        schema: Dict[str, Any],
        initial_assignments: Dict[str, Tuple[str, int, int | str]],
        compatible_venues: Dict[str, List[int | str]],
        venue_tier_label: Dict[str, Dict[int | str, str]],
        affinity_config: Optional[Dict[str, Any]] = None,
        pinned_session_ids: Optional[Set[str]] = None,
    ) -> None:
        self.sessions = sessions
        self.venues = venues
        self.schema = schema
        self.compatible_venues = compatible_venues
        self.venue_tier_label = venue_tier_label
        self.pinned_session_ids: Set[str] = set(pinned_session_ids or ())
        self.pinned_snapshot: Dict[str, Tuple[str, int, int | str]] = {
            sid: initial_assignments[sid]
            for sid in self.pinned_session_ids
            if sid in initial_assignments
        }

        self.engine = SoftConstraintEngine(
            sessions=sessions,
            venues=venues,
            schema=schema,
            venue_tier_label=venue_tier_label,
            affinity_config=affinity_config,
        )

        self.active_days = self.engine.active_days
        self.periods_per_day = self.engine.periods_per_day
        self.day_to_idx = self.engine.day_to_idx
        self.num_days = self.engine.num_days
        self.saturday_idx = self.engine.saturday_idx

        # Precompute 108-bit global mask and 18-bit day-local mask for every (day_idx, start_p, dur)
        self.global_mask_lut: Dict[Tuple[int, int, int], int] = {}
        self.local_mask_lut: Dict[Tuple[int, int], int] = {}
        for dur in (1, 2, 4, 6):
            for start_p in range(1, self.periods_per_day - dur + 2):
                l_mask = ((1 << dur) - 1) << (start_p - 1)
                self.local_mask_lut[(start_p, dur)] = l_mask
                for d_idx in range(self.num_days):
                    base_bit = d_idx * self.periods_per_day + (start_p - 1)
                    self.global_mask_lut[(d_idx, start_p, dur)] = ((1 << dur) - 1) << base_bit

        # Session metadata arrays/maps for fast inner-loop access
        self.all_sids: List[str] = [s["sessionId"] for s in sessions]
        self.movable_sids: List[str] = [
            sid for sid in self.all_sids if sid not in self.pinned_session_ids
        ]
        self.var_duration: Dict[str, int] = {}
        self.var_is_evening: Dict[str, bool] = {}
        self.var_lecturers: Dict[str, Tuple[str, ...]] = {}
        self.var_cohorts: Dict[str, Tuple[str, ...]] = {}
        self.var_valid_slots: Dict[str, Tuple[Tuple[int, int, int, int], ...]] = {}
        # Each valid slot is (day_idx, start_p, global_108_mask, local_18_mask)
        self.var_weekday_slots: Dict[str, Tuple[Tuple[int, int, int, int], ...]] = {}
        self.var_allows_saturday: Dict[str, bool] = {}

        # Group sessions by (is_evening, duration) for fast pairwise swap proposals
        self.sids_by_stream_dur: Dict[Tuple[bool, int], List[str]] = defaultdict(list)
        # Also group sessions by shared cohort for targeted intra-cohort compaction swaps
        self.sids_by_cohort_dur: Dict[Tuple[str, int], List[str]] = defaultdict(list)
        # Group Shared Practical sessions (and all Practical sessions) by (is_evening, duration) and (cohort, duration)
        self.shared_prac_by_stream_dur: Dict[Tuple[bool, int], List[str]] = defaultdict(list)
        self.shared_prac_by_cohort_dur: Dict[Tuple[str, int], List[str]] = defaultdict(list)
        self.any_prac_by_cohort_dur: Dict[Tuple[str, int], List[str]] = defaultdict(list)

        valid_slots_cache: Dict[Tuple[bool, int], Tuple[Tuple[int, int, int, int], ...]] = {}
        weekday_slots_cache: Dict[Tuple[bool, int], Tuple[Tuple[int, int, int, int], ...]] = {}

        for is_eve in (False, True):
            for dur in (1, 2, 4, 6):
                raw_slots = get_valid_time_slots(is_evening=is_eve, duration=dur, schema=schema)
                encoded = []
                wk_encoded = []
                for d_str, sp in raw_slots:
                    d_idx = self.day_to_idx[d_str]
                    g_mask = self.global_mask_lut[(d_idx, sp, dur)]
                    l_mask = self.local_mask_lut[(sp, dur)]
                    item = (d_idx, sp, g_mask, l_mask)
                    encoded.append(item)
                    if d_idx != self.saturday_idx:
                        wk_encoded.append(item)
                valid_slots_cache[(is_eve, dur)] = tuple(encoded)
                weekday_slots_cache[(is_eve, dur)] = tuple(wk_encoded)

        # Precompute Condition 1 Saturday-allowed cohorts (>60p Full-Time or >30p standard Evening or >5 6p blocks)
        cohort_total_periods: Dict[str, int] = defaultdict(int)
        cohort_6p_blocks: Dict[str, int] = defaultdict(int)
        for s in sessions:
            dur = int(s["durationPeriods"])
            for c in s.get("targetCohorts", []):
                cohort_total_periods[c] += dur
                if dur == 6:
                    cohort_6p_blocks[c] += 1

        self.condition1_saturday_cohorts: Set[str] = set()
        for c in self.engine.all_cohorts:
            if self.engine.cohort_is_evening.get(c, False):
                if cohort_total_periods[c] > 30:
                    self.condition1_saturday_cohorts.add(c)
            else:
                if cohort_total_periods[c] > 60 or cohort_6p_blocks[c] > 5:
                    self.condition1_saturday_cohorts.add(c)

        for s in sessions:
            sid = s["sessionId"]
            dur = int(s["durationPeriods"])
            is_eve = bool(s["isEveningStream"])
            lecs = tuple(s.get("lecturers", []))
            cohs = tuple(s.get("targetCohorts", []))

            self.var_duration[sid] = dur
            self.var_is_evening[sid] = is_eve
            self.var_lecturers[sid] = lecs
            self.var_cohorts[sid] = cohs

            allows_saturday = any(c in self.condition1_saturday_cohorts for c in cohs) or (
                initial_assignments.get(sid, ("", 0, ""))[0] == "SATURDAY"
            )
            self.var_allows_saturday[sid] = allows_saturday
            self.var_weekday_slots[sid] = weekday_slots_cache[(is_eve, dur)]
            self.var_valid_slots[sid] = (
                valid_slots_cache[(is_eve, dur)] if allows_saturday else weekday_slots_cache[(is_eve, dur)]
            )

            if sid not in self.pinned_session_ids:
                self.sids_by_stream_dur[(is_eve, dur)].append(sid)
                is_shared_prac = self.engine.session_is_shared_practical[sid]
                is_any_prac = is_shared_prac or self.engine.session_is_solo_practical[sid]
                if is_shared_prac:
                    self.shared_prac_by_stream_dur[(is_eve, dur)].append(sid)
                for c in cohs:
                    self.sids_by_cohort_dur[(c, dur)].append(sid)
                    if is_shared_prac:
                        self.shared_prac_by_cohort_dur[(c, dur)].append(sid)
                    if is_any_prac:
                        self.any_prac_by_cohort_dur[(c, dur)].append(sid)

        self.swappable_cohort_dur_groups: List[List[str]] = [
            grp for grp in self.sids_by_cohort_dur.values() if len(grp) >= 2
        ]
        self.swappable_stream_dur_groups: List[List[str]] = [
            grp for grp in self.sids_by_stream_dur.values() if len(grp) >= 2
        ]

        # Initialize live state bitmasks from initial_assignments
        self.venue_busy_108: Dict[int | str, int] = {v["venueId"]: 0 for v in venues}
        self.lecturer_busy_108: Dict[str, int] = defaultdict(int)
        self.cohort_busy_108: Dict[str, int] = defaultdict(int)

        self.cohort_day_18: Dict[Tuple[str, int], int] = defaultdict(int)
        self.lecturer_day_18: Dict[Tuple[str, int], int] = defaultdict(int)

        # Current assignment state: sid -> (day_idx, start_p, vid, global_108_mask, local_18_mask)
        self.state: Dict[str, Tuple[int, int, int | str, int, int]] = {}
        self.session_cost_cache: Dict[str, float] = {}
        self.cohort_day_cost_cache: Dict[Tuple[str, int], float] = defaultdict(float)
        self.lecturer_day_cost_cache: Dict[Tuple[str, int], float] = defaultdict(float)

        for sid, (d_str, start_p, vid) in initial_assignments.items():
            d_idx = self.day_to_idx[d_str]
            dur = self.var_duration[sid]
            g_mask = self.global_mask_lut[(d_idx, start_p, dur)]
            l_mask = self.local_mask_lut[(start_p, dur)]

            self.state[sid] = (d_idx, start_p, vid, g_mask, l_mask)
            self.venue_busy_108[vid] |= g_mask
            for l in self.var_lecturers[sid]:
                self.lecturer_busy_108[l] |= g_mask
                self.lecturer_day_18[(l, d_idx)] |= l_mask
            for c in self.var_cohorts[sid]:
                self.cohort_busy_108[c] |= g_mask
                self.cohort_day_18[(c, d_idx)] |= l_mask

        # Compute initial cached costs
        self.current_objective: float = 0.0
        for sid, (d_idx, start_p, vid, _, l_mask) in self.state.items():
            sc = self.engine.session_placement_cost(sid, d_idx, start_p, vid, l_mask)
            self.session_cost_cache[sid] = sc
            self.current_objective += sc

        for (c, d_idx), d_mask in list(self.cohort_day_18.items()):
            cc = self.engine.cohort_day_cost(
                d_mask, self.engine.cohort_is_evening.get(c, False), d_idx, c
            )
            self.cohort_day_cost_cache[(c, d_idx)] = cc
            self.current_objective += cc

        for (l, d_idx), d_mask in list(self.lecturer_day_18.items()):
            lc = self.engine.lecturer_day_cost(d_mask, d_idx, l)
            self.lecturer_day_cost_cache[(l, d_idx)] = lc
            self.current_objective += lc

    def _export_current_assignments(self) -> Dict[str, Tuple[str, int, int | str]]:
        days = self.active_days
        return {
            sid: (days[d_idx], start_p, vid)
            for sid, (d_idx, start_p, vid, _, _) in self.state.items()
        }

    def _collect_penalized_sessions(self) -> List[str]:
        """
        Identifies sessions currently contributing to soft penalties (Saturday sessions,
        Twilight sessions, non-1A venue sessions, or sessions on days with cohort idle gaps
        or workload overload) for guided neighborhood proposals.
        Excludes all pinned_session_ids.
        """
        penalized: List[str] = []
        gappy_cohort_days: Set[Tuple[str, int]] = set()
        for (c, d_idx), cc in self.cohort_day_cost_cache.items():
            if cc > 0.0:
                gappy_cohort_days.add((c, d_idx))

        for sid, (d_idx, _, _, _, _) in self.state.items():
            if sid in self.pinned_session_ids:
                continue
            if self.session_cost_cache[sid] > 0.0:
                penalized.append(sid)
                continue
            for c in self.var_cohorts[sid]:
                if (c, d_idx) in gappy_cohort_days:
                    penalized.append(sid)
                    break

        return penalized if penalized else self.movable_sids

    def _refine_venues_greedily(self) -> int:
        """
        Zero-cost post-SA greedy venue refinement pass:
        Iterates over all sessions and upgrades any unpinned session currently placed in a
        non-1A venue (Tier 1B / 1C / 2) to a free higher-affinity venue (e.g. Tier 1A)
        at its exact assigned (day, start_p) whenever one has opened up.
        Preserves 100% of hard constraints and only monotonically decreases or preserves
        the total soft objective.
        """
        upgrades = 0
        for sid in self.movable_sids:
            d_idx, start_p, old_vid, g_mask, l_mask = self.state[sid]
            old_raw = self.engine.session_venue_raw_penalty[sid].get(old_vid, 0.0)
            if old_raw <= 0.0:
                continue
            self.venue_busy_108[old_vid] &= ~g_mask
            best_vid = self._find_best_free_venue(sid, g_mask)
            if best_vid is not None and best_vid != old_vid:
                new_raw = self.engine.session_venue_raw_penalty[sid].get(best_vid, 0.0)
                if new_raw < old_raw:
                    self.venue_busy_108[best_vid] |= g_mask
                    new_sc = self.engine.session_placement_cost(sid, d_idx, start_p, best_vid, l_mask)
                    self.current_objective += new_sc - self.session_cost_cache[sid]
                    self.session_cost_cache[sid] = new_sc
                    self.state[sid] = (d_idx, start_p, best_vid, g_mask, l_mask)
                    upgrades += 1
                    continue
            self.venue_busy_108[old_vid] |= g_mask
        return upgrades

    def _find_best_free_venue(self, sid: str, g_mask: int) -> Optional[int | str]:
        """
        Returns the highest-affinity compatible venue for `sid` that is completely free
        during `g_mask` (`(venue_busy_108[vid] & g_mask) == 0`).
        Since `compatible_venues[sid]` is already sorted `[Tier 1A -> Tier 1B -> Tier 1C -> Tier 2]`,
        the first free venue in `compatible_venues[sid]` is guaranteed to minimize the venue tier penalty!
        """
        v_busy = self.venue_busy_108
        for vid in self.compatible_venues[sid]:
            if (v_busy[vid] & g_mask) == 0:
                return vid
        return None

    def _try_single_session_move(
        self,
        sid: str,
        target_slot: Tuple[int, int, int, int],
        temperature: float,
        rng: random.Random,
    ) -> Tuple[bool, float]:
        """
        Proposes moving `sid` from its current placement to `target_slot = (new_d_idx, new_start_p, new_g_mask, new_l_mask)`.
        Checks hard constraints in O(1) bitmask operations, computes exact Delta-E in O(1),
        and accepts/rejects via the Metropolis criterion.
        Returns `(accepted, delta_e)`.
        """
        if sid in self.pinned_session_ids:
            return False, 0.0
        old_d_idx, old_start_p, old_vid, old_g_mask, old_l_mask = self.state[sid]
        new_d_idx, new_start_p, new_g_mask, new_l_mask = target_slot

        if new_d_idx == old_d_idx and new_start_p == old_start_p:
            # Same time slot: check if a strictly better Tier 1A venue is now free
            if self.engine.session_venue_raw_penalty[sid].get(old_vid, 0.0) == 0.0:
                return False, 0.0
            new_vid = self._find_best_free_venue(sid, new_g_mask)
            if new_vid is None or new_vid == old_vid:
                return False, 0.0
            new_sc = self.engine.session_placement_cost(sid, new_d_idx, new_start_p, new_vid, new_l_mask)
            old_sc = self.session_cost_cache[sid]
            delta_e = new_sc - old_sc
            if delta_e <= 0.0 or rng.random() < math.exp(-delta_e / temperature):
                self.venue_busy_108[old_vid] &= ~old_g_mask
                self.venue_busy_108[new_vid] |= new_g_mask
                self.state[sid] = (new_d_idx, new_start_p, new_vid, new_g_mask, new_l_mask)
                self.session_cost_cache[sid] = new_sc
                self.current_objective += delta_e
                return True, delta_e
            return False, 0.0

        lecs = self.var_lecturers[sid]
        cohs = self.var_cohorts[sid]

        # 1. Hard Constraint Check: Lecturer & Cohort non-overlap (ignoring sid's old bits)
        lec_busy = self.lecturer_busy_108
        for l in lecs:
            if ((lec_busy[l] & ~old_g_mask) & new_g_mask) != 0:
                return False, 0.0

        coh_busy = self.cohort_busy_108
        for c in cohs:
            if ((coh_busy[c] & ~old_g_mask) & new_g_mask) != 0:
                return False, 0.0

        # 2. Hard Constraint Check: Find best available compatible venue at new_g_mask
        # Temporarily clear old_vid's busy bits so old_vid itself can be reused if new_d_idx == old_d_idx
        self.venue_busy_108[old_vid] &= ~old_g_mask
        new_vid = self._find_best_free_venue(sid, new_g_mask)
        if new_vid is None:
            self.venue_busy_108[old_vid] |= old_g_mask
            return False, 0.0

        # 3. Incremental Delta-E calculation
        old_sc = self.session_cost_cache[sid]
        new_sc = self.engine.session_placement_cost(sid, new_d_idx, new_start_p, new_vid, new_l_mask)
        delta_e = new_sc - old_sc

        coh_is_eve = self.engine.cohort_is_evening
        coh_day_18 = self.cohort_day_18
        coh_cost_cache = self.cohort_day_cost_cache
        lec_day_18 = self.lecturer_day_18
        lec_cost_cache = self.lecturer_day_cost_cache

        if new_d_idx == old_d_idx:
            for c in cohs:
                key = (c, old_d_idx)
                new_cmask = (coh_day_18[key] & ~old_l_mask) | new_l_mask
                delta_e += (
                    self.engine.cohort_day_cost(
                        new_cmask, coh_is_eve.get(c, False), old_d_idx, c
                    )
                    - coh_cost_cache[key]
                )
            # Note: on the same day, lecturer busy period count doesn't change for a single session move!
        else:
            for c in cohs:
                is_eve_c = coh_is_eve.get(c, False)
                k_old = (c, old_d_idx)
                k_new = (c, new_d_idx)
                cmask_old = coh_day_18[k_old] & ~old_l_mask
                cmask_new = coh_day_18[k_new] | new_l_mask
                delta_e += (
                    self.engine.cohort_day_cost(cmask_old, is_eve_c, old_d_idx, c)
                    - coh_cost_cache[k_old]
                    + self.engine.cohort_day_cost(cmask_new, is_eve_c, new_d_idx, c)
                    - coh_cost_cache[k_new]
                )
            for l in lecs:
                k_old = (l, old_d_idx)
                k_new = (l, new_d_idx)
                lmask_old = lec_day_18[k_old] & ~old_l_mask
                lmask_new = lec_day_18[k_new] | new_l_mask
                delta_e += (
                    self.engine.lecturer_day_cost(lmask_old, old_d_idx, l)
                    - lec_cost_cache[k_old]
                    + self.engine.lecturer_day_cost(lmask_new, new_d_idx, l)
                    - lec_cost_cache[k_new]
                )

        # 4. Metropolis Acceptance Criterion
        if delta_e <= 0.0 or rng.random() < math.exp(-delta_e / temperature):
            # Commit move
            self.venue_busy_108[new_vid] |= new_g_mask
            for l in lecs:
                lec_busy[l] = (lec_busy[l] & ~old_g_mask) | new_g_mask
            for c in cohs:
                coh_busy[c] = (coh_busy[c] & ~old_g_mask) | new_g_mask

            if new_d_idx == old_d_idx:
                for c in cohs:
                    key = (c, old_d_idx)
                    new_cmask = (coh_day_18[key] & ~old_l_mask) | new_l_mask
                    coh_day_18[key] = new_cmask
                    coh_cost_cache[key] = self.engine.cohort_day_cost(
                        new_cmask, coh_is_eve.get(c, False), old_d_idx, c
                    )
                for l in lecs:
                    key = (l, old_d_idx)
                    lec_day_18[key] = (lec_day_18[key] & ~old_l_mask) | new_l_mask
            else:
                for c in cohs:
                    is_eve_c = coh_is_eve.get(c, False)
                    k_old = (c, old_d_idx)
                    k_new = (c, new_d_idx)
                    cmask_old = coh_day_18[k_old] & ~old_l_mask
                    cmask_new = coh_day_18[k_new] | new_l_mask
                    coh_day_18[k_old] = cmask_old
                    coh_day_18[k_new] = cmask_new
                    coh_cost_cache[k_old] = self.engine.cohort_day_cost(
                        cmask_old, is_eve_c, old_d_idx, c
                    )
                    coh_cost_cache[k_new] = self.engine.cohort_day_cost(
                        cmask_new, is_eve_c, new_d_idx, c
                    )
                for l in lecs:
                    k_old = (l, old_d_idx)
                    k_new = (l, new_d_idx)
                    lmask_old = lec_day_18[k_old] & ~old_l_mask
                    lmask_new = lec_day_18[k_new] | new_l_mask
                    lec_day_18[k_old] = lmask_old
                    lec_day_18[k_new] = lmask_new
                    lec_cost_cache[k_old] = self.engine.lecturer_day_cost(
                        lmask_old, old_d_idx, l
                    )
                    lec_cost_cache[k_new] = self.engine.lecturer_day_cost(
                        lmask_new, new_d_idx, l
                    )

            self.state[sid] = (new_d_idx, new_start_p, new_vid, new_g_mask, new_l_mask)
            self.session_cost_cache[sid] = new_sc
            self.current_objective += delta_e
            return True, delta_e

        # Reject move: restore old_vid busy mask
        self.venue_busy_108[old_vid] |= old_g_mask
        return False, 0.0

    def _try_pairwise_swap(
        self,
        sid_a: str,
        sid_b: str,
        temperature: float,
        rng: random.Random,
    ) -> Tuple[bool, float]:
        """
        Proposes swapping the time slots of two same-duration sessions `sid_a` and `sid_b`
        (and assigning each session its highest-affinity available venue at the target time slot).
        Preserves 100% of hard constraints.
        """
        if sid_a == sid_b or sid_a in self.pinned_session_ids or sid_b in self.pinned_session_ids:
            return False, 0.0

        da, spa, vida, gma, lma = self.state[sid_a]
        db, spb, vidb, gmb, lmb = self.state[sid_b]

        if da == db and spa == spb:
            return False, 0.0

        # Ensure target time slots are unary-valid for both sessions and respect Saturday policy
        if self.var_is_evening[sid_a] != self.var_is_evening[sid_b]:
            return False, 0.0
        if db == self.saturday_idx and not self.var_allows_saturday[sid_a]:
            return False, 0.0
        if da == self.saturday_idx and not self.var_allows_saturday[sid_b]:
            return False, 0.0

        lecs_a = self.var_lecturers[sid_a]
        cohs_a = self.var_cohorts[sid_a]
        lecs_b = self.var_lecturers[sid_b]
        cohs_b = self.var_cohorts[sid_b]

        lec_busy = self.lecturer_busy_108
        coh_busy = self.cohort_busy_108

        # Temporarily remove both sessions from lecturer, cohort, and venue 108-bit masks
        for l in lecs_a:
            lec_busy[l] &= ~gma
        for l in lecs_b:
            lec_busy[l] &= ~gmb
        for c in cohs_a:
            coh_busy[c] &= ~gma
        for c in cohs_b:
            coh_busy[c] &= ~gmb
        self.venue_busy_108[vida] &= ~gma
        self.venue_busy_108[vidb] &= ~gmb

        # Check if sid_a fits at slot_b (gmb) and sid_b fits at slot_a (gma)
        feasible = True
        for l in lecs_a:
            if (lec_busy[l] & gmb) != 0:
                feasible = False
                break
        if feasible:
            for l in lecs_b:
                if (lec_busy[l] & gma) != 0:
                    feasible = False
                    break
        if feasible:
            for c in cohs_a:
                if (coh_busy[c] & gmb) != 0:
                    feasible = False
                    break
        if feasible:
            for c in cohs_b:
                if (coh_busy[c] & gma) != 0:
                    feasible = False
                    break

        new_vida: Optional[int | str] = None
        new_vidb: Optional[int | str] = None
        if feasible:
            new_vida = self._find_best_free_venue(sid_a, gmb)
            if new_vida is None:
                feasible = False
            else:
                self.venue_busy_108[new_vida] |= gmb
                new_vidb = self._find_best_free_venue(sid_b, gma)
                self.venue_busy_108[new_vida] &= ~gmb
                if new_vidb is None:
                    feasible = False

        if not feasible or new_vida is None or new_vidb is None:
            # Restore original masks
            for l in lecs_a:
                lec_busy[l] |= gma
            for l in lecs_b:
                lec_busy[l] |= gmb
            for c in cohs_a:
                coh_busy[c] |= gma
            for c in cohs_b:
                coh_busy[c] |= gmb
            self.venue_busy_108[vida] |= gma
            self.venue_busy_108[vidb] |= gmb
            return False, 0.0

        # Compute exact Delta-E across affected sessions, (cohort, day) pairs, and (lecturer, day) pairs
        old_sca = self.session_cost_cache[sid_a]
        old_scb = self.session_cost_cache[sid_b]
        new_sca = self.engine.session_placement_cost(sid_a, db, spb, new_vida, lmb)
        new_scb = self.engine.session_placement_cost(sid_b, da, spa, new_vidb, lma)
        delta_e = (new_sca + new_scb) - (old_sca + old_scb)

        coh_day_18 = self.cohort_day_18
        coh_cost_cache = self.cohort_day_cost_cache
        coh_is_eve = self.engine.cohort_is_evening
        lec_day_18 = self.lecturer_day_18
        lec_cost_cache = self.lecturer_day_cost_cache

        # Compute updated (cohort, day) masks
        affected_coh_days: Dict[Tuple[str, int], int] = {}
        for c in cohs_a:
            affected_coh_days[(c, da)] = coh_day_18[(c, da)]
            affected_coh_days[(c, db)] = coh_day_18[(c, db)]
        for c in cohs_b:
            affected_coh_days[(c, da)] = coh_day_18[(c, da)]
            affected_coh_days[(c, db)] = coh_day_18[(c, db)]

        for c in cohs_a:
            affected_coh_days[(c, da)] &= ~lma
        for c in cohs_b:
            affected_coh_days[(c, db)] &= ~lmb
        for c in cohs_a:
            affected_coh_days[(c, db)] |= lmb
        for c in cohs_b:
            affected_coh_days[(c, da)] |= lma

        new_coh_costs: Dict[Tuple[str, int], float] = {}
        for (c, d_idx), new_cmask in affected_coh_days.items():
            nc = self.engine.cohort_day_cost(
                new_cmask, coh_is_eve.get(c, False), d_idx, c
            )
            new_coh_costs[(c, d_idx)] = nc
            delta_e += nc - coh_cost_cache[(c, d_idx)]

        affected_lec_days: Dict[Tuple[str, int], int] = {}
        if da != db:
            for l in lecs_a:
                affected_lec_days[(l, da)] = lec_day_18[(l, da)]
                affected_lec_days[(l, db)] = lec_day_18[(l, db)]
            for l in lecs_b:
                affected_lec_days[(l, da)] = lec_day_18[(l, da)]
                affected_lec_days[(l, db)] = lec_day_18[(l, db)]

            for l in lecs_a:
                affected_lec_days[(l, da)] &= ~lma
            for l in lecs_b:
                affected_lec_days[(l, db)] &= ~lmb
            for l in lecs_a:
                affected_lec_days[(l, db)] |= lmb
            for l in lecs_b:
                affected_lec_days[(l, da)] |= lma

        new_lec_costs: Dict[Tuple[str, int], float] = {}
        for (l, d_idx), new_lmask in affected_lec_days.items():
            nlc = self.engine.lecturer_day_cost(new_lmask, d_idx, l)
            new_lec_costs[(l, d_idx)] = nlc
            delta_e += nlc - lec_cost_cache[(l, d_idx)]

        if delta_e <= 0.0 or rng.random() < math.exp(-delta_e / temperature):
            # Commit pairwise swap
            for l in lecs_a:
                lec_busy[l] |= gmb
            for l in lecs_b:
                lec_busy[l] |= gma
            for c in cohs_a:
                coh_busy[c] |= gmb
            for c in cohs_b:
                coh_busy[c] |= gma
            self.venue_busy_108[new_vida] |= gmb
            self.venue_busy_108[new_vidb] |= gma

            for k, new_cmask in affected_coh_days.items():
                coh_day_18[k] = new_cmask
                coh_cost_cache[k] = new_coh_costs[k]

            if da == db:
                # Update lecturer day masks on same day if needed
                for l in lecs_a:
                    lec_day_18[(l, da)] &= ~lma
                for l in lecs_b:
                    lec_day_18[(l, db)] &= ~lmb
                for l in lecs_a:
                    lec_day_18[(l, db)] |= lmb
                for l in lecs_b:
                    lec_day_18[(l, da)] |= lma
            else:
                for k, new_lmask in affected_lec_days.items():
                    lec_day_18[k] = new_lmask
                    lec_cost_cache[k] = new_lec_costs[k]

            self.state[sid_a] = (db, spb, new_vida, gmb, lmb)
            self.state[sid_b] = (da, spa, new_vidb, gma, lma)
            self.session_cost_cache[sid_a] = new_sca
            self.session_cost_cache[sid_b] = new_scb
            self.current_objective += delta_e
            return True, delta_e

        # Reject pairwise swap: restore original masks
        for l in lecs_a:
            lec_busy[l] |= gma
        for l in lecs_b:
            lec_busy[l] |= gmb
        for c in cohs_a:
            coh_busy[c] |= gma
        for c in cohs_b:
            coh_busy[c] |= gmb
        self.venue_busy_108[vida] |= gma
        self.venue_busy_108[vidb] |= gmb
        return False, 0.0

    def optimize(
        self,
        max_iterations: Optional[int] = None,
        initial_temperature: Optional[float] = None,
        cooling_rate: Optional[float] = None,
        min_temperature: Optional[float] = None,
        swap_probability: Optional[float] = None,
        guided_proposal_probability: Optional[float] = None,
        random_seed: Optional[int] = None,
    ) -> Tuple[Dict[str, Tuple[str, int, int | str]], OptimizerStats]:
        """
        Executes Hard-Constraint-Preserving Simulated Annealing and returns
        `(best_assignments, optimizer_stats)`.
        """
        opt_cfg = self.schema.get("optimizer", {})
        enabled = bool(opt_cfg.get("enabled", True))
        max_iter = int(
            max_iterations if max_iterations is not None else opt_cfg.get("max_iterations", 40000)
        )
        t_init = float(
            initial_temperature
            if initial_temperature is not None
            else opt_cfg.get("initial_temperature", 120.0)
        )
        alpha = float(
            cooling_rate if cooling_rate is not None else opt_cfg.get("cooling_rate", 0.99985)
        )
        t_min = float(
            min_temperature
            if min_temperature is not None
            else opt_cfg.get("min_temperature", 0.05)
        )
        p_swap = float(
            swap_probability
            if swap_probability is not None
            else opt_cfg.get("swap_probability", 0.45)
        )
        p_guided = float(
            guided_proposal_probability
            if guided_proposal_probability is not None
            else opt_cfg.get("guided_proposal_probability", 0.70)
        )
        seed = int(
            random_seed if random_seed is not None else opt_cfg.get("random_seed", 42)
        )

        start_time = time.perf_counter()
        initial_assignments = self._export_current_assignments()
        initial_breakdown = self.engine.evaluate_full_breakdown(initial_assignments)
        initial_obj = initial_breakdown.total_objective
        self.current_objective = initial_obj

        if not enabled or max_iter <= 0 or not self.movable_sids:
            elapsed = time.perf_counter() - start_time
            return initial_assignments, OptimizerStats(
                enabled=enabled,
                iterations=0,
                runtime_seconds=elapsed,
                initial_objective=initial_obj,
                final_objective=initial_obj,
                best_objective=initial_obj,
                improvement_pct=0.0,
                accepted_moves=0,
                improving_moves=0,
                uphill_moves=0,
                rejected_moves=0,
                single_shift_proposals=0,
                pairwise_swap_proposals=0,
                initial_breakdown=initial_breakdown,
                final_breakdown=initial_breakdown,
            )

        rng = random.Random(seed)
        best_obj = initial_obj
        best_state_snapshot: Dict[str, Tuple[int, int, int | str, int, int]] = dict(self.state)

        temperature = t_init
        accepted_moves = 0
        improving_moves = 0
        uphill_moves = 0
        rejected_moves = 0
        single_shift_proposals = 0
        pairwise_swap_proposals = 0

        penalized_sids = self._collect_penalized_sessions()
        movable_sids = self.movable_sids
        coh_swap_groups = self.swappable_cohort_dur_groups
        stream_swap_groups = self.swappable_stream_dur_groups

        for it in range(1, max_iter + 1):
            # Periodically refresh guided candidate pool every 500 iterations
            if (it & 511) == 0:
                penalized_sids = self._collect_penalized_sessions()

            if rng.random() < p_swap and stream_swap_groups:
                pairwise_swap_proposals += 1
                # Guided Swap Bias for Saturday Sessions:
                # When sid_a is scheduled on SATURDAY and is NOT a Shared Practical,
                # bias the swap partner search (sid_b) toward weekday Shared Practical sessions
                # (same durationPeriods and isEveningStream, preferably sharing a cohort with sid_a).
                if rng.random() < p_guided and penalized_sids:
                    sid_a = penalized_sids[rng.randrange(len(penalized_sids))]
                    da_curr = self.state[sid_a][0]
                    dur_a = self.var_duration[sid_a]
                    eve_a = self.var_is_evening[sid_a]
                    cohs_a = self.var_cohorts[sid_a]

                    if (
                        da_curr == self.saturday_idx
                        and not self.engine.session_is_shared_practical[sid_a]
                    ):
                        # 1st priority: weekday Shared Practical sharing a cohort with sid_a
                        coh_shared_cands: List[str] = []
                        for c in cohs_a:
                            for cand in self.shared_prac_by_cohort_dur.get((c, dur_a), ()):
                                if (
                                    cand != sid_a
                                    and self.var_is_evening[cand] == eve_a
                                    and self.state[cand][0] != self.saturday_idx
                                ):
                                    coh_shared_cands.append(cand)
                        if coh_shared_cands and rng.random() < 0.85:
                            sid_b = coh_shared_cands[rng.randrange(len(coh_shared_cands))]
                        else:
                            # 2nd priority: any weekday Practical sharing a cohort, or global weekday Shared Practical
                            coh_prac_cands: List[str] = []
                            for c in cohs_a:
                                for cand in self.any_prac_by_cohort_dur.get((c, dur_a), ()):
                                    if (
                                        cand != sid_a
                                        and self.var_is_evening[cand] == eve_a
                                        and self.state[cand][0] != self.saturday_idx
                                    ):
                                        coh_prac_cands.append(cand)
                            if coh_prac_cands and rng.random() < 0.75:
                                sid_b = coh_prac_cands[rng.randrange(len(coh_prac_cands))]
                            else:
                                stream_shared = [
                                    cand
                                    for cand in self.shared_prac_by_stream_dur.get(
                                        (eve_a, dur_a), ()
                                    )
                                    if cand != sid_a
                                    and self.state[cand][0] != self.saturday_idx
                                ]
                                if stream_shared and rng.random() < 0.70:
                                    sid_b = stream_shared[rng.randrange(len(stream_shared))]
                                else:
                                    grp = self.sids_by_stream_dur[(eve_a, dur_a)]
                                    if len(grp) < 2:
                                        continue
                                    sid_b = grp[rng.randrange(len(grp))]
                    elif cohs_a and rng.random() < 0.65:
                        c = cohs_a[rng.randrange(len(cohs_a))]
                        grp = self.sids_by_cohort_dur[(c, dur_a)]
                        if len(grp) >= 2:
                            sid_b = grp[rng.randrange(len(grp))]
                        else:
                            grp = self.sids_by_stream_dur[(eve_a, dur_a)]
                            if len(grp) < 2:
                                continue
                            sid_b = grp[rng.randrange(len(grp))]
                    else:
                        grp = self.sids_by_stream_dur[(eve_a, dur_a)]
                        if len(grp) < 2:
                            continue
                        sid_b = grp[rng.randrange(len(grp))]
                else:
                    if coh_swap_groups and rng.random() < 0.65:
                        grp = coh_swap_groups[rng.randrange(len(coh_swap_groups))]
                        sid_a, sid_b = rng.sample(grp, 2)
                    else:
                        grp = stream_swap_groups[rng.randrange(len(stream_swap_groups))]
                        sid_a, sid_b = rng.sample(grp, 2)

                accepted, delta_e = self._try_pairwise_swap(sid_a, sid_b, temperature, rng)
            else:
                single_shift_proposals += 1
                if rng.random() < p_guided and penalized_sids:
                    sid = penalized_sids[rng.randrange(len(penalized_sids))]
                    # When guided, prefer Monday-Friday slots 85% of the time
                    wk_slots = self.var_weekday_slots[sid]
                    if wk_slots and rng.random() < 0.85:
                        target_slot = wk_slots[rng.randrange(len(wk_slots))]
                    else:
                        v_slots = self.var_valid_slots[sid]
                        target_slot = v_slots[rng.randrange(len(v_slots))]
                else:
                    sid = movable_sids[rng.randrange(len(movable_sids))]
                    v_slots = self.var_valid_slots[sid]
                    target_slot = v_slots[rng.randrange(len(v_slots))]

                accepted, delta_e = self._try_single_session_move(sid, target_slot, temperature, rng)

            if accepted:
                accepted_moves += 1
                if delta_e < -1e-9:
                    improving_moves += 1
                    if self.current_objective < best_obj - 1e-9:
                        best_obj = self.current_objective
                        best_state_snapshot = dict(self.state)
                elif delta_e > 1e-9:
                    uphill_moves += 1
            else:
                rejected_moves += 1

            temperature = max(t_min, temperature * alpha)

        # Restore best-found state snapshot so returned schedule is strictly the global best visited
        self.state = best_state_snapshot
        # Rebuild venue_busy_108 from best_state_snapshot and run zero-cost greedy venue upgrade pass
        for vid in self.venue_busy_108:
            self.venue_busy_108[vid] = 0
        for sid, (d_idx, start_p, vid, g_mask, l_mask) in self.state.items():
            self.venue_busy_108[vid] |= g_mask
            self.session_cost_cache[sid] = self.engine.session_placement_cost(
                sid, d_idx, start_p, vid, l_mask
            )
        while self._refine_venues_greedily() > 0:
            pass

        best_assignments = self._export_current_assignments()
        for sid, expected_pin in self.pinned_snapshot.items():
            assert best_assignments.get(sid) == expected_pin, (
                f"Pinned session '{sid}' was modified during SA optimization: "
                f"expected {expected_pin}, got {best_assignments.get(sid)}"
            )
        final_breakdown = self.engine.evaluate_full_breakdown(best_assignments)
        final_obj = final_breakdown.total_objective
        elapsed = time.perf_counter() - start_time

        improvement_pct = (
            ((initial_obj - final_obj) / initial_obj * 100.0) if initial_obj > 0.0 else 0.0
        )

        stats = OptimizerStats(
            enabled=enabled,
            iterations=max_iter,
            runtime_seconds=elapsed,
            initial_objective=initial_obj,
            final_objective=final_obj,
            best_objective=final_obj,
            improvement_pct=improvement_pct,
            accepted_moves=accepted_moves,
            improving_moves=improving_moves,
            uphill_moves=uphill_moves,
            rejected_moves=rejected_moves,
            single_shift_proposals=single_shift_proposals,
            pairwise_swap_proposals=pairwise_swap_proposals,
            initial_breakdown=initial_breakdown,
            final_breakdown=final_breakdown,
        )
        return best_assignments, stats


if __name__ == "__main__":
    from src.csp.domain import build_domains, load_json
    from src.csp.solver import TimetableCSPSolver, verify_solution

    root = Path(__file__).resolve().parents[2]
    schema = load_json(root / "configs" / "institution_schema.json")
    dataset = load_json(root / "data" / "raw" / "atc" / "atc-timetable-dataset.json")
    csp_raw = load_json(root / "data" / "raw" / "atc" / "atc-csp-sessions.json")
    affinity_cfg = load_json(root / "configs" / "atc_venue_affinity.json")
    all_sessions = csp_raw["sessions"]
    venues = dataset["venues"]

    primary_sessions = [s for s in all_sessions if int(s["sessionId"][1:]) <= 1233]
    solver = TimetableCSPSolver(
        sessions=primary_sessions,
        venues=venues,
        schema=schema,
        affinity_config=affinity_cfg,
    )
    init_assignments, solve_stats = solver.solve()
    optimizer = SimulatedAnnealingOptimizer(
        sessions=primary_sessions,
        venues=venues,
        schema=schema,
        initial_assignments=init_assignments,
        compatible_venues=solver.compatible_venues,
        venue_tier_label=solver.venue_tier_label,
        affinity_config=affinity_cfg,
    )
    opt_assignments, opt_stats = optimizer.optimize()
    initial_domains = build_domains(
        primary_sessions, venues, schema, affinity_config=affinity_cfg
    )
    ver = verify_solution(
        primary_sessions, opt_assignments, initial_domains, solver.venue_tier_label
    )
    print(f"CSP Solve: {solve_stats.status} in {solve_stats.runtime_seconds * 1000:.2f} ms")
    print(
        f"SA Optimizer: {opt_stats.initial_objective:,.2f} -> {opt_stats.final_objective:,.2f} "
        f"(-{opt_stats.improvement_pct:.2f}%) in {opt_stats.runtime_seconds * 1000:.2f} ms"
    )
    print(f"Post-SA Hard Verification: valid={ver['valid']}")


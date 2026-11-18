import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def load_json(filepath: str | Path) -> Any:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def get_valid_start_periods_for_day(
    day: str,
    is_evening: bool,
    duration: int,
    schema: Dict[str, Any]
) -> List[int]:
    """
    Dynamically computes valid start periods for a given (day, stream, duration)
    using only declarative rules from institution_schema.json.
    """
    grid = schema["calendar_grid"]
    day_overrides = grid.get("day_overrides", {}).get(day, {})
    override_active = day_overrides.get("apply_override", False)

    # 1. If override is active and explicitly disables the entire day, return empty
    if override_active and not day_overrides.get("day_active", True):
        return []

    stream_key = "evening" if is_evening else "full_time"
    stream_cfg = schema["streams"][stream_key]

    if duration not in stream_cfg["supported_durations"]:
        return []

    min_p = stream_cfg["min_period"]
    max_p = stream_cfg["max_period"]
    if override_active:
        max_p = min(max_p, day_overrides.get("max_period", grid["periods_per_day"]))

    # Handle Evening Twilight Buffer (Periods 11-12)
    breaks = list(grid.get("breaks_after_periods", []))
    if is_evening:
        buffer_cfg = stream_cfg.get("twilight_buffer", {})
        if buffer_cfg.get("enabled", False):
            min_p = buffer_cfg["buffer_min_period"]
            # If bridging across 12 -> 13 is disallowed, treat Period 12 as a break boundary
            if not buffer_cfg.get("allow_bridge_into_evening", True):
                breaks.append(buffer_cfg["buffer_max_period"])
    else:
        # Full-Time cannot cross the stream boundary after Period 12
        if not stream_cfg.get("allow_stream_boundary_crossing", False):
            breaks.append(stream_cfg["max_period"])

    # Merge any day-specific breaks and blocked periods (e.g., Friday Jummah prayers)
    if override_active:
        breaks.extend(day_overrides.get("additional_breaks_after_periods", []))
        blocked_periods = set(day_overrides.get("blocked_periods", []))
    else:
        blocked_periods = set()

    enforce_odd = grid.get("enforce_odd_start_alignment_for_multi_period", True)
    valid_starts: List[int] = []

    for p in range(min_p, max_p - duration + 2):
        end_p = p + duration - 1

        # Rule A: Multi-period sessions (duration >= 2) must start on odd periods
        if enforce_odd and duration >= 2 and (p % 2 == 0):
            continue

        # Rule B: Cannot cover any blocked period on this day
        session_periods = set(range(p, end_p + 1))
        if session_periods & blocked_periods:
            continue

        # Rule C: Break-crossing inequality (p <= b < end_p)
        crosses_break = any(p <= b < end_p for b in breaks)
        if crosses_break:
            continue

        # Rule D: For evening buffer starts (11-12), ensure a 6-period block doesn't start at 11
        if is_evening and p < stream_cfg["min_period"] and duration == 6:
            continue

        valid_starts.append(p)

    return valid_starts


def get_valid_time_slots(
    is_evening: bool,
    duration: int,
    schema: Dict[str, Any]
) -> List[Tuple[str, int]]:
    """Returns all valid (day, start_period) pairs across active calendar days."""
    slots: List[Tuple[str, int]] = []
    for day in schema["calendar_grid"]["active_days"]:
        for start_p in get_valid_start_periods_for_day(day, is_evening, duration, schema):
            slots.append((day, start_p))
    return slots


def get_compatible_venues(
    required_category: str,
    venues: List[Dict[str, Any]],
    schema: Dict[str, Any],
    include_fallbacks: bool | None = None
) -> List[int | str]:
    """
    Returns venueIds matching the session's requiredVenueCategory.
    Uses primary categories plus optional fallback categories from institution_schema.json.
    """
    venue_rules = schema["venue_rules"]
    if include_fallbacks is None:
        include_fallbacks = venue_rules.get("allow_fallback_venues_in_initial_domain", True)

    compat_entry = venue_rules["compatibility_map"].get(required_category, {
        "primary": [required_category],
        "fallback": []
    })

    allowed_categories = set(compat_entry["primary"])
    if include_fallbacks:
        allowed_categories.update(compat_entry.get("fallback", []))

    matched_venue_ids: List[int | str] = []
    for v in venues:
        v_cat = v.get("category", "").strip()
        if v_cat in allowed_categories:
            matched_venue_ids.append(v["venueId"])

    return matched_venue_ids


def build_domains(
    sessions: List[Dict[str, Any]],
    venues: List[Dict[str, Any]],
    schema: Dict[str, Any],
    include_fallback_venues: bool = False,
    affinity_config: Dict[str, Any] | None = None,
) -> Dict[str, List[Tuple[str, int, int | str]]]:
    """
    Constructs the Unary-Filtered Domain D_i = [(day, start_period, venue_id), ...]
    for every session x_i in X.
    When `affinity_config` is provided, applies hard sub-pool pruning for specialized
    categories and orders compatible venues by [Tier 1A -> Tier 1B -> Tier 1C -> Tier 2].
    """
    from src.csp.affinity import resolve_session_venues_and_tiers

    domains: Dict[str, List[Tuple[str, int, int | str]]] = {}

    for s in sessions:
        sid = s["sessionId"]
        time_slots = get_valid_time_slots(
            is_evening=s["isEveningStream"],
            duration=s["durationPeriods"],
            schema=schema
        )
        if affinity_config is not None:
            compat_venues, _, _ = resolve_session_venues_and_tiers(
                session=s,
                venues=venues,
                schema=schema,
                affinity_config=affinity_config,
                include_fallbacks=include_fallback_venues,
            )
        else:
            compat_venues = get_compatible_venues(
                required_category=s["requiredVenueCategory"],
                venues=venues,
                schema=schema,
                include_fallbacks=include_fallback_venues
            )

        # Cartesian product of valid (day, start_period) x valid venue_id
        domains[sid] = [
            (day, start_p, vid)
            for (day, start_p) in time_slots
            for vid in compat_venues
        ]

    return domains


def run_preflight_checks(
    sessions: List[Dict[str, Any]],
    venues: List[Dict[str, Any]],
    schema: Dict[str, Any],
    include_fallback_venues: bool = False,
    affinity_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Verifies necessary (pigeonhole) capacity conditions before search starts:
      1. Lecturer Capacity Check
      2. Cohort Capacity Check
      3. Venue Category Capacity Check (per stream)
      4. Departmental Restricted Sub-Pool Capacity Check (when affinity_config is provided)
    """
    from src.csp.affinity import resolve_session_venues_and_tiers

    ft_slots = set(get_valid_time_slots(is_evening=False, duration=1, schema=schema))
    eve_slots = set(get_valid_time_slots(is_evening=True, duration=1, schema=schema))
    both_slots = ft_slots | eve_slots

    ft_capacity = len(ft_slots)
    eve_capacity = len(eve_slots)
    both_capacity = len(both_slots)

    # 1. Lecturer Capacity Check
    lec_loads: Dict[str, Dict[str, int]] = defaultdict(lambda: {"full_time": 0, "evening": 0, "total": 0})
    for s in sessions:
        dur = s["durationPeriods"]
        stream_key = "evening" if s["isEveningStream"] else "full_time"
        for lec in s.get("lecturers", []):
            lec_loads[lec][stream_key] += dur
            lec_loads[lec]["total"] += dur

    lecturer_violations: List[Dict[str, Any]] = []
    for lec, load in sorted(lec_loads.items()):
        if load["full_time"] > 0 and load["evening"] > 0:
            avail = both_capacity
        elif load["evening"] > 0:
            avail = eve_capacity
        else:
            avail = ft_capacity

        if load["total"] > avail or load["full_time"] > ft_capacity or load["evening"] > eve_capacity:
            lecturer_violations.append({
                "lecturer": lec,
                "demand_periods": load["total"],
                "full_time_periods": load["full_time"],
                "evening_periods": load["evening"],
                "available_periods": avail,
            })

    # 2. Cohort Capacity Check
    cohort_loads: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"full_time": 0, "evening": 0, "total": 0})
    for s in sessions:
        dur = s["durationPeriods"]
        stream_key = "evening" if s["isEveningStream"] else "full_time"
        for coh in s.get("targetCohorts", []):
            cohort_loads[coh][stream_key] += dur
            cohort_loads[coh]["total"] += dur

    cohort_violations: List[Dict[str, Any]] = []
    for coh, load in sorted(cohort_loads.items()):
        if load["full_time"] > 0 and load["evening"] > 0:
            avail = both_capacity
        elif load["evening"] > 0:
            avail = eve_capacity
        else:
            avail = ft_capacity

        if load["total"] > avail or load["full_time"] > ft_capacity or load["evening"] > eve_capacity:
            cohort_violations.append({
                "cohort": coh,
                "demand_periods": load["total"],
                "full_time_periods": load["full_time"],
                "evening_periods": load["evening"],
                "available_periods": avail,
            })

    # 3. Venue Category Capacity Check (per requiredVenueCategory, per stream)
    cat_stream_demand: Dict[Tuple[str, bool], int] = defaultdict(int)
    for s in sessions:
        cat_stream_demand[(s["requiredVenueCategory"], s["isEveningStream"])] += s["durationPeriods"]

    venue_category_violations: List[Dict[str, Any]] = []
    venue_category_utilization: List[Dict[str, Any]] = []
    for (cat, is_eve), demand in sorted(cat_stream_demand.items()):
        compat_venues = get_compatible_venues(
            required_category=cat,
            venues=venues,
            schema=schema,
            include_fallbacks=include_fallback_venues
        )
        stream_periods = eve_capacity if is_eve else ft_capacity
        total_capacity = len(compat_venues) * stream_periods
        entry = {
            "category": cat,
            "stream": "evening" if is_eve else "full_time",
            "demand_periods": demand,
            "compatible_venues": len(compat_venues),
            "stream_periods": stream_periods,
            "capacity_periods": total_capacity,
            "utilization": round(demand / total_capacity, 4) if total_capacity > 0 else float("inf"),
        }
        venue_category_utilization.append(entry)
        if demand > total_capacity:
            venue_category_violations.append(entry)

    # 4. Restricted Sub-Pool Capacity Check (for hard-locked specialized lab/workshop pools)
    subpool_violations: List[Dict[str, Any]] = []
    if affinity_config is not None:
        policies = affinity_config.get("category_overflow_policies", {})
        pool_demand: Dict[Tuple[str, bool, Tuple[int | str, ...]], int] = defaultdict(int)
        for s in sessions:
            cat = s["requiredVenueCategory"]
            if not policies.get(cat, {}).get("restrict_to_prefix_or_module_pool", False):
                continue
            vids, _, _ = resolve_session_venues_and_tiers(
                session=s,
                venues=venues,
                schema=schema,
                affinity_config=affinity_config,
                include_fallbacks=include_fallback_venues,
            )
            pool_key = (cat, s["isEveningStream"], tuple(sorted(vids, key=str)))
            pool_demand[pool_key] += s["durationPeriods"]

        for (cat, is_eve, pool_vids), demand in sorted(pool_demand.items(), key=lambda x: str(x[0])):
            stream_periods = eve_capacity if is_eve else ft_capacity
            cap = len(pool_vids) * stream_periods
            if demand > cap:
                subpool_violations.append({
                    "category": cat,
                    "stream": "evening" if is_eve else "full_time",
                    "venue_pool": list(pool_vids),
                    "demand_periods": demand,
                    "capacity_periods": cap,
                })

    passed = (
        len(lecturer_violations) == 0
        and len(cohort_violations) == 0
        and len(venue_category_violations) == 0
        and len(subpool_violations) == 0
    )

    return {
        "passed": passed,
        "stream_periods": {
            "full_time": ft_capacity,
            "evening": eve_capacity,
            "combined": both_capacity,
        },
        "lecturer_check": {
            "passed": len(lecturer_violations) == 0,
            "total_lecturers": len(lec_loads),
            "max_demand_periods": max((v["total"] for v in lec_loads.values()), default=0),
            "violations": lecturer_violations,
        },
        "cohort_check": {
            "passed": len(cohort_violations) == 0,
            "total_cohorts": len(cohort_loads),
            "max_demand_periods": max((v["total"] for v in cohort_loads.values()), default=0),
            "violations": cohort_violations,
        },
        "venue_category_check": {
            "passed": len(venue_category_violations) == 0,
            "utilization": venue_category_utilization,
            "violations": venue_category_violations,
        },
        "subpool_check": {
            "passed": len(subpool_violations) == 0,
            "violations": subpool_violations,
        },
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    schema = load_json(root / "configs" / "institution_schema.json")
    affinity_path = root / "configs" / "atc_venue_affinity.json"
    affinity_cfg = load_json(affinity_path) if affinity_path.exists() else None
    dataset = load_json(root / "data" / "raw" / "atc" / "atc-timetable-dataset.json")
    sessions = load_json(root / "data" / "raw" / "atc" / "atc-csp-sessions.json")["sessions"]
    venues = dataset["venues"]

    print("=== 1. Computed Start Periods Verification (MONDAY) ===")
    for is_eve in [False, True]:
        stream_label = "Evening" if is_eve else "Full-Time"
        for dur in [1, 2, 4, 6]:
            starts = get_valid_start_periods_for_day("MONDAY", is_eve, dur, schema)
            print(f"  {stream_label:9s} | duration={dur} -> {starts}")

    # Build strict primary domains with departmental affinity config active
    domains_primary = build_domains(
        sessions, venues, schema, include_fallback_venues=False, affinity_config=affinity_cfg
    )
    wipeouts = [sid for sid, dom in domains_primary.items() if len(dom) == 0]
    sizes = [len(dom) for dom in domains_primary.values()]

    print(f"\n=== 2. Domain Generation Summary (Affinity Sub-Pools Active) ===")
    print(f"  Total variables (|X|) : {len(domains_primary)}")
    print(f"  Domain wipeouts (|D|=0): {len(wipeouts)}")
    print(f"  Min |D_i|              : {min(sizes)}")
    print(f"  Max |D_i|              : {max(sizes)}")
    print(f"  Avg |D_i|              : {sum(sizes) / len(sizes):.1f}")

    gt_hits = 0
    for s in sessions:
        gt_tuple = (s["groundTruth"]["scheduledDay"], s["groundTruth"]["startPeriod"], s["groundTruth"]["venueId"])
        if gt_tuple in domains_primary[s["sessionId"]]:
            gt_hits += 1
    print(f"  Ground-truth in domain : {gt_hits} / {len(sessions)}")

    preflight = run_preflight_checks(
        sessions, venues, schema, include_fallback_venues=False, affinity_config=affinity_cfg
    )
    print(f"\n=== 3. Preflight Pigeonhole Capacity Checks ===")
    print(f"  Overall Passed         : {preflight['passed']}")
    print(f"  1. Lecturer Check      : {'PASS' if preflight['lecturer_check']['passed'] else 'FAIL'} "
          f"(max={preflight['lecturer_check']['max_demand_periods']}p, violations={len(preflight['lecturer_check']['violations'])})")
    print(f"  2. Cohort Check        : {'PASS' if preflight['cohort_check']['passed'] else 'FAIL'} "
          f"(max={preflight['cohort_check']['max_demand_periods']}p, violations={len(preflight['cohort_check']['violations'])})")
    for v in preflight["cohort_check"]["violations"]:
        print(f"       -> Cohort {v['cohort']}: {v['demand_periods']}p required > {v['available_periods']}p available")
    print(f"  3. Venue Category Check: {'PASS' if preflight['venue_category_check']['passed'] else 'FAIL'} "
          f"(violations={len(preflight['venue_category_check']['violations'])})")
    for u in preflight["venue_category_check"]["utilization"]:
        print(f"       -> {u['category']:26s} [{u['stream']:9s}]: {u['demand_periods']:4d} / {u['capacity_periods']:4d}p ({u['utilization']*100:5.1f}%)")
    print(f"  4. Dept Sub-Pool Check : {'PASS' if preflight['subpool_check']['passed'] else 'FAIL'} "
          f"(violations={len(preflight['subpool_check']['violations'])})")

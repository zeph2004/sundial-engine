from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PERIOD_DURATION_MINUTES = 45

DEFAULT_CHUNKING_RULE: Dict[str, int] = {"preferred": 2, "max": 3}
DEFAULT_MIN_PERIODS = 2


def _parse_hhmm(raw: str) -> Optional[int]:
    """Parses 'HH:MM' into minutes since midnight, or None if invalid."""
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(raw or ""))
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return hours * 60 + minutes


def get_period_duration_minutes(schema_config: Optional[Dict[str, Any]]) -> int:
    """
    Computes period_duration_minutes from the active schema_config period grid
    (using the difference between start_time and end_time of Period 1),
    falling back to calendar_grid.period_duration_minutes, then 45 minutes.
    """
    if isinstance(schema_config, dict):
        grid = schema_config.get("calendar_grid")
        if isinstance(grid, dict):
            periods = grid.get("periods")
            if isinstance(periods, list) and periods:
                p1 = None
                for entry in periods:
                    if isinstance(entry, dict) and entry.get("period_number", entry.get("period")) == 1:
                        p1 = entry
                        break
                if p1 is None and isinstance(periods[0], dict):
                    p1 = periods[0]
                if isinstance(p1, dict):
                    start_min = _parse_hhmm(p1.get("start_time", p1.get("start", "")))
                    end_min = _parse_hhmm(p1.get("end_time", p1.get("end", "")))
                    if start_min is not None and end_min is not None and end_min > start_min:
                        return end_min - start_min

            explicit = grid.get("period_duration_minutes")
            if isinstance(explicit, (int, float)) and explicit > 0:
                return int(round(explicit))

    return DEFAULT_PERIOD_DURATION_MINUTES


def hours_to_weekly_periods(
    hours_per_week: float,
    period_duration_minutes: int,
    row_num: Optional[int] = None,
    module_code: str = "",
) -> Tuple[int, Optional[str]]:
    """
    Converts weekly teaching hours into an integer number of grid periods.
    Emits a non-blocking warning string if rounding differs by more than 0.05 periods.
    """
    if hours_per_week <= 0:
        prefix = f"Row {row_num}" if row_num is not None else "Allocation"
        if module_code:
            prefix = f"{prefix} ({module_code})"
        raise ValueError(f"{prefix}: hours_per_week must be greater than 0 (got {hours_per_week}).")

    if period_duration_minutes <= 0:
        period_duration_minutes = DEFAULT_PERIOD_DURATION_MINUTES

    raw_periods = (float(hours_per_week) * 60.0) / float(period_duration_minutes)
    weekly_periods = max(1, round(raw_periods))

    warning: Optional[str] = None
    if abs(raw_periods - weekly_periods) > 0.05:
        label = f"Row {row_num}" if row_num is not None else "Allocation"
        if module_code:
            label = f"{label} ({module_code})"
        warning = (
            f"{label}: {hours_per_week:g}h on a {period_duration_minutes}-min grid = "
            f"{raw_periods:.1f} periods, rounded to {weekly_periods} periods."
        )

    return weekly_periods, warning


def _resolve_chunking_rule(
    session_type: str,
    chunking_config: Optional[Dict[str, Any]],
) -> Tuple[int, int, int]:
    """
    Resolves (min_periods, preferred, max_periods) for `session_type` from `chunking_config`.
    Case-insensitive lookup in `by_type`, falling back to `default`, then hardcoded safe fallback.
    """
    if not isinstance(chunking_config, dict):
        return (
            DEFAULT_MIN_PERIODS,
            DEFAULT_CHUNKING_RULE["preferred"],
            DEFAULT_CHUNKING_RULE["max"],
        )

    min_p = int(chunking_config.get("min_periods", DEFAULT_MIN_PERIODS))
    min_p = max(1, min_p)

    by_type = chunking_config.get("by_type")
    target_lower = str(session_type or "").strip().lower()
    rule: Optional[Dict[str, Any]] = None
    if isinstance(by_type, dict) and target_lower:
        for key, cfg in by_type.items():
            if isinstance(key, str) and key.strip().lower() == target_lower and isinstance(cfg, dict):
                rule = cfg
                break

    if rule is None:
        default_cfg = chunking_config.get("default")
        rule = default_cfg if isinstance(default_cfg, dict) else DEFAULT_CHUNKING_RULE

    pref = max(1, int(rule.get("preferred", DEFAULT_CHUNKING_RULE["preferred"])))
    max_p = max(pref, int(rule.get("max", max(pref, DEFAULT_CHUNKING_RULE["max"]))))
    return min_p, pref, max_p


def chunk_weekly_periods(
    weekly_periods: int,
    session_type: str,
    split_override: Optional[str] = None,
    row_label: str = "",
    chunking_config: Optional[Dict[str, Any]] = None,
) -> List[int]:
    """
    Splits weekly_periods into balanced session block durations using declarative
    `session_chunking` rules from institution_schema.json.
    Honors explicit `split_override` (e.g. '3+3', '4', '2+2+2') with highest priority.
    """
    prefix = f"{row_label}: " if row_label else ""
    if not isinstance(weekly_periods, int) or weekly_periods < 1:
        raise ValueError(f"{prefix}weekly_periods must be a positive integer (got {weekly_periods}).")

    override_clean = str(split_override or "").strip()
    if override_clean:
        tokens = [t.strip() for t in re.split(r"[+,]", override_clean) if t.strip()]
        if not tokens:
            raise ValueError(f"{prefix}split_override '{split_override}' is empty.")
        parts: List[int] = []
        for tok in tokens:
            try:
                val = int(tok)
            except ValueError as exc:
                raise ValueError(
                    f"{prefix}invalid split_override '{split_override}': '{tok}' is not a positive integer."
                ) from exc
            if val < 1:
                raise ValueError(
                    f"{prefix}invalid split_override '{split_override}': all block sizes must be >= 1."
                )
            parts.append(val)
        if sum(parts) != weekly_periods:
            raise ValueError(
                f"{prefix}split_override '{split_override}' sums to {sum(parts)}, "
                f"which does not match {weekly_periods} weekly periods."
            )
        return parts

    min_p, pref, max_p = _resolve_chunking_rule(session_type, chunking_config)

    # 1. Fits within preferred block size
    if weekly_periods <= pref:
        return [weekly_periods]

    # 2. Fits within max block size
    if weekly_periods <= max_p:
        if weekly_periods % pref == 0:
            return [pref] * (weekly_periods // pref)
        return [weekly_periods]

    # 3. Greedily build chunks of size `pref` until remaining < pref
    chunks: List[int] = []
    remaining = weekly_periods
    while remaining >= pref:
        chunks.append(pref)
        remaining -= pref

    if remaining > 0:
        if remaining >= min_p or pref == 1:
            chunks.append(remaining)
        else:
            # 0 < remaining < min_p: try merging into last chunk, else borrow 1 to balance
            if chunks and chunks[-1] + remaining <= max_p:
                chunks[-1] += remaining
            elif chunks and chunks[-1] > min_p:
                chunks[-1] -= 1
                chunks.append(remaining + 1)
            else:
                chunks.append(remaining)

    chunks.sort(reverse=True)
    return chunks


def merge_duplicate_allocation_rows(
    rows: List[Dict[str, Any]],
    mode: str,
) -> List[Dict[str, Any]]:
    """
    Merges duplicate allocation rows sharing the exact same
    (module_code, session_type, sorted cohorts, sorted lecturers, is_evening_stream)
    when neither row specifies a split_override, summing their hours_per_week or
    weekly_periods so the chunker produces balanced [2, 2] / [3, 2] blocks instead
    of 1-period fragments.
    """
    merged_order: List[Dict[str, Any]] = []
    by_key: Dict[Tuple[Any, ...], Dict[str, Any]] = {}

    def _split_list(val: Any) -> Tuple[str, ...]:
        if isinstance(val, list):
            return tuple(sorted(str(x).strip() for x in val if str(x).strip()))
        return tuple(sorted(p.strip() for p in str(val or "").split(";") if p.strip()))

    def _to_bool(val: Any) -> bool:
        if isinstance(val, bool):
            return val
        return str(val or "").strip().lower() in ("true", "1", "yes", "y")

    for row in rows:
        override = str(row.get("split_override", row.get("splitOverride", "")) or "").strip()
        if override:
            merged_order.append(dict(row))
            continue

        mod_code = str(row.get("module_code", row.get("moduleCode", ""))).strip().upper()
        stype = str(row.get("session_type", row.get("sessionType", "Theory"))).strip().lower() or "theory"
        cohorts = _split_list(row.get("cohorts", row.get("targetCohorts", [])))
        lecturers = _split_list(row.get("lecturers", []))
        is_eve = _to_bool(row.get("is_evening_stream", row.get("isEveningStream", False)))
        key = (mod_code, stype, cohorts, lecturers, is_eve)

        if key not in by_key:
            copy_row = dict(row)
            by_key[key] = copy_row
            merged_order.append(copy_row)
        else:
            existing = by_key[key]
            if mode == "allocations_hours":
                h1 = float(str(existing.get("hours_per_week", existing.get("hoursPerWeek", 0)) or 0).strip())
                h2 = float(str(row.get("hours_per_week", row.get("hoursPerWeek", 0)) or 0).strip())
                existing["hours_per_week"] = h1 + h2
            elif mode == "allocations_periods":
                p1 = int(str(existing.get("weekly_periods", existing.get("weeklyPeriods", 0)) or 0).strip())
                p2 = int(str(row.get("weekly_periods", row.get("weeklyPeriods", 0)) or 0).strip())
                existing["weekly_periods"] = p1 + p2
            if not str(existing.get("preferred_venue", existing.get("preferredVenue", "")) or "").strip():
                pv = str(row.get("preferred_venue", row.get("preferredVenue", "")) or "").strip()
                if pv:
                    existing["preferred_venue"] = pv

    return merged_order


def expand_allocation_to_sessions(
    base_id: str,
    chunks: List[int],
    module_code: str,
    module_name: str,
    session_type: str,
    required_venue_category: str,
    cohorts: List[str],
    lecturers: List[str],
    is_evening_stream: bool,
    preferred_venue: Optional[str],
    cohort_level: str = "",
) -> List[Dict[str, Any]]:
    """
    Deterministically expands a single course allocation row into len(chunks)
    standard internal session dicts expected by src/csp/domain.py.
    """
    expanded: List[Dict[str, Any]] = []
    for idx, dur in enumerate(chunks, start=1):
        sid = f"{base_id}_{idx}"
        expanded.append(
            {
                "sessionId": sid,
                "moduleCode": module_code,
                "moduleCodes": [module_code],
                "moduleName": module_name,
                "sessionType": session_type,
                "requiredVenueCategory": required_venue_category,
                "durationPeriods": dur,
                "targetCohorts": list(cohorts),
                "cohortRaw": " + ".join(cohorts),
                "cohortLevel": cohort_level,
                "lecturers": list(lecturers),
                "isEveningStream": is_evening_stream,
                "preferredVenue": preferred_venue,
                "groundTruth": {
                    "scheduledDay": "MONDAY",
                    "startPeriod": 1,
                    "endPeriod": dur,
                    "venueId": None,
                    "venueName": preferred_venue or "",
                },
            }
        )
    return expanded

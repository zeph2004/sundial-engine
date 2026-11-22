from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PERIOD_DURATION_MINUTES = 45

PRACTICAL_KEYWORDS = ("lab", "workshop", "practical", "studio")


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


def _is_practical_session(session_type: str) -> bool:
    st = str(session_type or "").strip().lower()
    return any(kw in st for kw in PRACTICAL_KEYWORDS)


def chunk_weekly_periods(
    weekly_periods: int,
    session_type: str,
    split_override: Optional[str] = None,
    row_label: str = "",
) -> List[int]:
    """
    Splits weekly_periods into balanced session block durations.
    Honors explicit split_override (e.g. '3+3', '4', '2+2+2') when provided.
    Avoids stray 1-period fragments and 4-period marathons by default.
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

    is_practical = _is_practical_session(session_type)

    if weekly_periods == 1:
        return [1]
    if weekly_periods == 2:
        return [2]
    if weekly_periods == 3:
        return [3] if is_practical else [2, 1]
    if weekly_periods == 4:
        return [2, 2]
    if weekly_periods == 5:
        return [3, 2]
    if weekly_periods == 6:
        return [3, 3] if is_practical else [2, 2, 2]

    # 7+ periods: greedily chunk into 3s (practical) or 2s (theory), avoiding remainder 1
    if is_practical:
        q, rem = divmod(weekly_periods, 3)
        if rem == 0:
            return [3] * q
        if rem == 2:
            return [3] * q + [2]
        # rem == 1: borrow 1 from the last 3-block so (3 + 1) becomes (2, 2), e.g., 7 -> [3, 2, 2]
        return [3] * (q - 1) + [2, 2]

    # Theory 7+: greedily chunk into 2s; if remainder 1, merge into one 3-block, e.g., 7 -> [3, 2, 2], 8 -> [2, 2, 2, 2]
    q, rem = divmod(weekly_periods, 2)
    if rem == 0:
        return [2] * q
    return [3] + [2] * (q - 1)


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

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Request

from src.api.routes_solve import build_public_sessions_list
from src.api.state import AppStateManager, DEFAULT_BRANDING

router = APIRouter(tags=["Public Consumer"])


def _get_manager(request: Request) -> AppStateManager:
    return request.app.state.manager


@router.get("/api/public/timetable")
def get_public_timetable(request: Request) -> Dict[str, Any]:
    """
    Public endpoint (NO authentication required) serving everything the React
    Public Front Door needs in a single fast request.
    """
    manager = _get_manager(request)
    state = manager.state
    schema = state.get("schema", {})
    grid = schema.get("calendar_grid", {})
    streams = schema.get("streams", {})
    ft_cfg = streams.get("full_time", {})
    eve_cfg = streams.get("evening", {})
    twi_cfg = eve_cfg.get("twilight_buffer", {})

    sessions_raw = state.get("sessions", [])
    venues_raw = state.get("venues", [])
    assignments = state.get("assignments", {})
    pinned_ids = set(state.get("pinned_assignments", {}).keys())
    active_tt = state.get("active_timetable", {})

    # Build sorted entity catalogs [{id, label}] for cohorts, lecturers, and venues
    cohort_meta: Dict[str, Dict[str, Any]] = {}
    lecturer_names: set[str] = set()
    for s in sessions_raw:
        lvl = str(s.get("cohortLevel", "")).strip()
        is_eve = bool(s.get("isEveningStream", False))
        for c in s.get("targetCohorts", []):
            if c not in cohort_meta:
                stream_tag = "Evening" if (is_eve or c.endswith("-E")) else "Full-Time"
                label = f"{c} (Level {lvl} • {stream_tag})" if lvl else f"{c} ({stream_tag})"
                cohort_meta[c] = {"id": c, "label": label}
        for l in s.get("lecturers", []):
            if l:
                lecturer_names.add(l)

    cohorts_entities: List[Dict[str, str]] = [
        cohort_meta[k] for k in sorted(cohort_meta.keys())
    ]
    lecturers_entities: List[Dict[str, str]] = [
        {"id": l, "label": l} for l in sorted(lecturer_names)
    ]
    venues_entities: List[Dict[str, str]] = sorted(
        [
            {
                "id": str(v["venueId"]),
                "label": f"{v['name']} ({v.get('category', 'Venue')})",
            }
            for v in venues_raw
        ],
        key=lambda x: x["label"].lower(),
    )

    scheduled_sessions = build_public_sessions_list(
        sessions=sessions_raw,
        assignments=assignments,
        pinned_ids=pinned_ids,
    )

    grid_config = {
        "days": list(grid.get("active_days", [])),
        "periods_per_day": int(grid.get("periods_per_day", 18)),
        "period_duration_minutes": int(grid.get("period_duration_minutes", 45)),
        "periods": state.get("teaching_periods", []),
        "break_slots": list(grid.get("breaks_after_periods", [4, 6])),
        "stream_boundaries": {
            "full_time_min": int(ft_cfg.get("min_period", 1)),
            "full_time_max": int(ft_cfg.get("max_period", 12)),
            "evening_min": int(eve_cfg.get("min_period", 13)),
            "evening_max": int(eve_cfg.get("max_period", 18)),
            "twilight_periods": (
                list(
                    range(
                        int(twi_cfg.get("buffer_min_period", 11)),
                        int(twi_cfg.get("buffer_max_period", 12)) + 1,
                    )
                )
                if twi_cfg.get("enabled", True)
                else []
            ),
        },
    }

    return {
        "branding": state.get("branding", DEFAULT_BRANDING),
        "grid_config": grid_config,
        "has_timetable": len(scheduled_sessions) > 0,
        "generated_at": active_tt.get("generated_at") or state.get("updated_at"),
        "entities": {
            "cohorts": cohorts_entities,
            "lecturers": lecturers_entities,
            "venues": venues_entities,
        },
        "sessions": scheduled_sessions,
    }

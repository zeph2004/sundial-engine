from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from src.api.auth import require_admin
from src.api.state import AppStateManager, validate_schema_config
from src.csp.domain import build_domains
from src.csp.optimizer import SimulatedAnnealingOptimizer
from src.csp.solver import TimetableCSPSolver, verify_solution

router = APIRouter(tags=["Solver & Optimization"])


class SolveRequest(BaseModel):
    schema_override: Optional[Dict[str, Any]] = None
    use_pins: bool = True
    run_optimizer: bool = True
    max_iterations: Optional[int] = None


def _get_manager(request: Request) -> AppStateManager:
    return request.app.state.manager


def build_saturday_explanations(
    sessions: List[Dict[str, Any]],
    assignments: Dict[str, Tuple[str, int, int | str]],
    schema: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    For every cohort with Saturday sessions, computes its total weekly periods vs.
    the 5-day weekday ceiling (60p FT / 30p Evening) and returns plain-English
    Condition 1 / Condition 2 explanations.
    """
    streams = schema.get("streams", {})
    ft_cfg = streams.get("full_time", {})
    eve_cfg = streams.get("evening", {})
    ft_daily = int(ft_cfg.get("max_period", 12)) - int(ft_cfg.get("min_period", 1)) + 1
    eve_daily = int(eve_cfg.get("max_period", 18)) - int(eve_cfg.get("min_period", 13)) + 1
    ft_weekday_limit = ft_daily * 5
    eve_weekday_limit = eve_daily * 5

    cohort_total_periods: Dict[str, int] = defaultdict(int)
    cohort_6p_blocks: Dict[str, int] = defaultdict(int)
    cohort_is_evening: Dict[str, bool] = {}
    cohort_sat_sessions: Dict[str, int] = defaultdict(int)
    cohort_sat_periods: Dict[str, int] = defaultdict(int)

    for s in sessions:
        sid = s["sessionId"]
        dur = int(s["durationPeriods"])
        is_eve = bool(s.get("isEveningStream", False))
        day_str = assignments.get(sid, ("", 0, ""))[0]
        for c in s.get("targetCohorts", []):
            cohort_total_periods[c] += dur
            if dur == 6:
                cohort_6p_blocks[c] += 1
            if is_eve or c.endswith("-E"):
                cohort_is_evening[c] = True
            elif c not in cohort_is_evening:
                cohort_is_evening[c] = False
            if day_str == "SATURDAY":
                cohort_sat_sessions[c] += 1
                cohort_sat_periods[c] += dur

    explanations: List[Dict[str, Any]] = []
    for coh in sorted(cohort_sat_sessions.keys()):
        is_eve = cohort_is_evening.get(coh, False)
        stream_label = "Evening" if is_eve else "Full-Time"
        weekday_limit = eve_weekday_limit if is_eve else ft_weekday_limit
        total_p = cohort_total_periods[coh]
        overflow_p = max(0, total_p - weekday_limit)
        sat_cnt = cohort_sat_sessions[coh]

        if overflow_p > 0:
            reason = (
                f"Condition 1: {total_p} periods assigned exceeds "
                f"{weekday_limit}-period Mon-Fri capacity by {overflow_p} periods."
            )
        elif not is_eve and cohort_6p_blocks[coh] > 5:
            reason = (
                f"Condition 1: {cohort_6p_blocks[coh]} six-period practical blocks assigned "
                f"exceeds 5 Mon-Fri afternoon slots."
            )
        else:
            reason = (
                f"Condition 2: Hard-constraint bottleneck ({sat_cnt} session(s) placed on Saturday "
                f"due to shared lecturer, cohort, or specialized lab contention)."
            )

        explanations.append(
            {
                "cohort": coh,
                "stream": stream_label,
                "total_periods": total_p,
                "weekday_limit": weekday_limit,
                "overflow_periods": overflow_p,
                "saturday_sessions": sat_cnt,
                "reason": reason,
            }
        )

    explanations.sort(key=lambda x: (-x["overflow_periods"], -x["saturday_sessions"], x["cohort"]))
    return explanations


def build_public_sessions_list(
    sessions: List[Dict[str, Any]],
    assignments: Dict[str, Dict[str, Any]],
    pinned_ids: set[str],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in sessions:
        sid = s["sessionId"]
        a = assignments.get(sid)
        if not a:
            continue
        out.append(
            {
                "session_id": sid,
                "module_code": s.get("moduleCode", ""),
                "module_name": s.get("moduleName", s.get("moduleCode", "")),
                "session_type": s.get("sessionType", "Theory"),
                "day_idx": int(a.get("day_idx", 0)),
                "day": a.get("day", "MONDAY"),
                "start_period": int(a.get("start_period", 1)),
                "duration_periods": int(s.get("durationPeriods", 1)),
                "venue_id": a.get("venue_id"),
                "venue_name": a.get("venue_name", ""),
                "venue_tier": a.get("venue_tier", ""),
                "cohorts": list(s.get("targetCohorts", [])),
                "lecturers": list(s.get("lecturers", [])),
                "is_evening_stream": bool(s.get("isEveningStream", False)),
                "is_twilight": bool(a.get("is_twilight", False)),
                "is_pinned": sid in pinned_ids,
                "saturday_reason": a.get("saturday_reason", "Weekday"),
            }
        )
    return out


@router.post("/api/solve")
def solve_active_timetable(
    request: Request,
    payload: Optional[SolveRequest] = None,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    manager = _get_manager(request)
    body = payload or SolveRequest()

    active_schema = (
        body.schema_override
        if body.schema_override is not None
        else manager.state["schema"]
    )
    if body.schema_override is not None:
        s_errs = validate_schema_config(active_schema)
        if s_errs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Invalid schema_override.", "errors": s_errs},
            )

    # 1. Pre-flight validation
    validation = manager.validate_active_dataset(schema_override=active_schema)
    if not validation["passed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation,
        )

    sessions = manager.state["sessions"]
    venues = manager.state["venues"]
    affinity_config = (
        manager.state.get("venue_affinity")
        if manager.state.get("dataset_mode") != "custom_upload"
        else None
    )
    solver_pins = manager.get_pins_as_solver_tuples() if body.use_pins else {}

    # 2. Phase 3 CSP Backtracking Solver
    solver = TimetableCSPSolver(
        sessions=sessions,
        venues=venues,
        schema=active_schema,
        affinity_config=affinity_config,
        pinned_assignments=solver_pins,
    )
    try:
        csp_assignments, csp_stats = solver.solve(pinned_assignments=solver_pins)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if csp_stats.status != "SOLVED":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "status": csp_stats.status,
                "solve_ms": round(csp_stats.runtime_seconds * 1000.0, 2),
                "assigned_count": csp_stats.assigned_count,
                "total_variables": csp_stats.total_variables,
            },
        )

    # 3. Phase 4 Simulated Annealing Optimizer
    final_assignments = csp_assignments
    optimize_ms = 0.0
    scorecard: Dict[str, Any] = {"enabled": False}
    if body.run_optimizer and active_schema.get("optimizer", {}).get("enabled", True):
        optimizer = SimulatedAnnealingOptimizer(
            sessions=sessions,
            venues=venues,
            schema=active_schema,
            initial_assignments=csp_assignments,
            compatible_venues=solver.compatible_venues,
            venue_tier_label=solver.venue_tier_label,
            affinity_config=affinity_config,
            pinned_session_ids=set(solver_pins.keys()),
        )
        final_assignments, opt_stats = optimizer.optimize(
            max_iterations=body.max_iterations
        )
        optimize_ms = round(opt_stats.runtime_seconds * 1000.0, 2)
        scorecard = opt_stats.to_dict()

    # 4. Independent Hard-Constraint Verification
    initial_domains = build_domains(
        sessions, venues, active_schema, affinity_config=affinity_config
    )
    verification = verify_solution(
        sessions,
        final_assignments,
        initial_domains,
        venue_tier_labels=solver.venue_tier_label,
    )
    hard_violations = (
        verification["unassigned_count"]
        + verification["unary_violations"]
        + verification["lecturer_overlaps"]
        + verification["cohort_overlaps"]
        + verification["venue_double_bookings"]
        + verification.get("venue_hopping_violations", 0)
    )

    # 5. Condition 1 Saturday Overflow Explanations
    saturday_explanations = build_saturday_explanations(
        sessions=sessions,
        assignments=final_assignments,
        schema=active_schema,
    )

    # Format assignments for persistence
    venue_by_id = {v["venueId"]: v for v in venues}
    session_by_id = {s["sessionId"]: s for s in sessions}
    active_days = active_schema["calendar_grid"]["active_days"]
    day_to_idx = {d: i for i, d in enumerate(active_days)}
    sat_report = verification.get("saturday_report", {})
    sat_reasons = sat_report.get("session_reasons", {})
    pinned_id_set = set(solver_pins.keys())

    formatted_assignments: Dict[str, Dict[str, Any]] = {}
    for sid, (d_str, sp, vid) in final_assignments.items():
        s_obj = session_by_id[sid]
        dur = int(s_obj["durationPeriods"])
        is_eve = bool(s_obj.get("isEveningStream", False))
        raw_tier = solver.venue_tier_label.get(sid, {}).get(
            vid, "Tier 1A: Module Preferred"
        )
        formatted_assignments[sid] = {
            "day": d_str,
            "day_idx": day_to_idx[d_str],
            "start_period": sp,
            "end_period": sp + dur - 1,
            "venue_id": vid,
            "venue_name": venue_by_id.get(vid, {}).get("name", f"Venue {vid}"),
            "venue_tier": raw_tier,
            "venue_sub_tier": raw_tier,
            "is_twilight": bool(is_eve and sp < 13),
            "saturday_reason": sat_reasons.get(sid, "Weekday"),
            "is_pinned": sid in pinned_id_set,
        }

    tot = max(1, verification["total_sessions"])
    total_cohorts = max(1, sat_report.get("total_cohorts", 1))
    kpis: Dict[str, Any] = {
        "total_sessions": verification["total_sessions"],
        "assigned_sessions": verification["assigned_sessions"],
        "backtracks": csp_stats.backtracks,
        "hard_violations": hard_violations,
        "tier1_affinity_pct": round(verification["tier_1_total"] / tot * 100.0, 1),
        "tier1a_exact_pct": round(verification["tier_1a_count"] / tot * 100.0, 1),
        "saturday_sessions": sat_report.get("csp_saturday_total", 0),
        "saturday_theory_sessions": sat_report.get("csp_saturday_theory_count", 0),
        "saturday_free_cohorts": sat_report.get("csp_saturday_free_cohorts", 0),
        "total_cohorts": sat_report.get("total_cohorts", 0),
        "saturday_free_cohorts_pct": round(
            sat_report.get("csp_saturday_free_cohorts", 0) / total_cohorts * 100.0, 1
        ),
        "evening_twilight_sessions": verification["evening_twilight_used"],
        "objective_improvement_pct": scorecard.get("improvementPct", 0.0),
    }

    solve_ms = round(csp_stats.runtime_seconds * 1000.0, 2)
    generated_at = datetime.now(timezone.utc).isoformat()
    timetable_sessions = build_public_sessions_list(
        sessions=sessions,
        assignments=formatted_assignments,
        pinned_ids=pinned_id_set,
    )

    # 6. Persist into active_timetable in app_state.json
    with manager._lock:
        manager.state["assignments"] = formatted_assignments
        manager.state["telemetry"] = {
            "status": csp_stats.status,
            "totalVariables": csp_stats.total_variables,
            "runtimeMs": solve_ms,
            "optimizeMs": optimize_ms,
            "nodesVisited": csp_stats.nodes_visited,
            "backtracks": csp_stats.backtracks,
            "prunedValues": csp_stats.pruned_values,
            "pinnedCount": len(pinned_id_set),
            "validHardConstraints": hard_violations == 0,
            "tier1AffinityCount": verification["tier_1_total"],
            "tier1AffinityPct": kpis["tier1_affinity_pct"],
            "tier1AExactModuleCount": verification["tier_1a_count"],
            "cspSaturdayTotal": kpis["saturday_sessions"],
            "cspSaturdayFreeCohorts": kpis["saturday_free_cohorts"],
            "totalCohorts": kpis["total_cohorts"],
            "twilightCount": kpis["evening_twilight_sessions"],
            "optimizer": scorecard,
        }
        manager.state["active_timetable"] = {
            "generated_at": generated_at,
            "has_timetable": True,
            "status": csp_stats.status,
            "solve_ms": solve_ms,
            "optimize_ms": optimize_ms,
            "hard_violations": hard_violations,
            "kpis": kpis,
            "scorecard": scorecard,
            "saturday_explanations": saturday_explanations,
            "pinned_count": len(pinned_id_set),
        }
        manager.save()

    # Export data/processed/timetable_view_data.json cleanly
    try:
        out_view_path = manager.root / "data" / "processed" / "timetable_view_data.json"
        out_view_path.parent.mkdir(parents=True, exist_ok=True)
        existing_bundle: Dict[str, Any] = {}
        if out_view_path.exists():
            try:
                with open(out_view_path, "r", encoding="utf-8") as rf:
                    existing_bundle = json.load(rf)
            except Exception:
                existing_bundle = {}
        existing_bundle["activeSolve"] = {
            "generatedAt": generated_at,
            "branding": manager.state.get("branding", {}),
            "kpis": kpis,
            "scorecard": scorecard,
            "saturdayExplanations": saturday_explanations,
            "sessions": timetable_sessions,
        }
        with open(out_view_path, "w", encoding="utf-8") as wf:
            json.dump(existing_bundle, wf, indent=2)
            wf.write("\n")
    except Exception:
        pass

    return {
        "status": csp_stats.status,
        "generated_at": generated_at,
        "solve_ms": solve_ms,
        "optimize_ms": optimize_ms,
        "hard_violations": hard_violations,
        "kpis": kpis,
        "scorecard": scorecard,
        "saturday_explanations": saturday_explanations,
        "pinned_count": len(pinned_id_set),
        "timetable": timetable_sessions,
    }

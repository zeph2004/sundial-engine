from __future__ import annotations

import json
import sys
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.csp.affinity import generate_venue_affinity_config
from src.csp.domain import build_domains, load_json, run_preflight_checks
from src.csp.optimizer import SimulatedAnnealingOptimizer
from src.csp.solver import TimetableCSPSolver, verify_solution

DEFAULT_BRANDING: Dict[str, Any] = {
    "institution_name": "Arusha Technical College",
    "semester_title": "Academic Year 2026/27 — Semester 1",
    "logo_url": None,
}


class AppStateManager:
    """
    Manages the single active institution workspace persisted to `data/processed/app_state.json`.
    On first boot (when `app_state.json` does not exist), automatically preloads with:
      - ATC Clean Primary Dataset (Mode A: S0001..S1233, |X| = 1,233 sessions) and ATC venues
      - `configs/institution_schema.json`
      - `configs/atc_venue_affinity.json`
      - Default branding:
        {
          "institution_name": "Arusha Technical College",
          "semester_title": "Academic Year 2026/27 — Semester 1",
          "logo_url": None
        }
    Provides thread-safe persistence and operations for session pinning, schema/branding updates,
    and re-running the CSP + Simulated Annealing solver around pinned sessions.
    """

    def __init__(
        self,
        root: Optional[Path] = None,
        state_path: Optional[Path] = None,
    ) -> None:
        self.root = (root or Path(__file__).resolve().parents[2]).resolve()
        self.state_path = (
            state_path or (self.root / "data" / "processed" / "app_state.json")
        ).resolve()
        self._lock = threading.RLock()
        self.state: Dict[str, Any] = {}
        self.load_or_initialize()

    def _build_default_state(self) -> Dict[str, Any]:
        schema_path = self.root / "configs" / "institution_schema.json"
        affinity_path = self.root / "configs" / "atc_venue_affinity.json"
        dataset_path = self.root / "data" / "raw" / "atc" / "atc-timetable-dataset.json"
        csp_sessions_path = self.root / "data" / "raw" / "atc" / "atc-csp-sessions.json"
        view_bundle_path = self.root / "data" / "processed" / "timetable_view_data.json"

        schema = load_json(schema_path)
        dataset = load_json(dataset_path)
        csp_raw = load_json(csp_sessions_path)
        venues = dataset["venues"]
        all_sessions = csp_raw["sessions"]
        primary_sessions = [s for s in all_sessions if int(s["sessionId"][1:]) <= 1233]

        if affinity_path.exists():
            affinity_config = load_json(affinity_path)
        else:
            affinity_config = generate_venue_affinity_config(
                all_sessions, venues, schema, output_path=affinity_path
            )

        day_to_idx = {
            d: i for i, d in enumerate(schema["calendar_grid"]["active_days"])
        }

        # Reuse pre-solved Mode A assignments from timetable_view_data.json if present for instant first boot
        assignments: Dict[str, Dict[str, Any]] = {}
        telemetry: Dict[str, Any] = {}
        if view_bundle_path.exists():
            try:
                bundle = load_json(view_bundle_path)
                mode_a = bundle.get("modes", {}).get("1233_clean", bundle)
                telemetry = mode_a.get("telemetry", {})
                for s_item in mode_a.get("sessions", []):
                    sid = s_item["sessionId"]
                    csp_a = s_item.get("cspAssignment", {})
                    d_str = csp_a.get("day", "MONDAY")
                    sp = int(csp_a.get("startPeriod", 1))
                    vid = csp_a.get("venueId")
                    assignments[sid] = {
                        "day": d_str,
                        "day_idx": day_to_idx.get(d_str, 0),
                        "start_period": sp,
                        "end_period": int(csp_a.get("endPeriod", sp)),
                        "venue_id": vid,
                        "venue_name": csp_a.get("venueName", str(vid)),
                        "venue_tier": csp_a.get("venueTier", ""),
                        "venue_sub_tier": csp_a.get("venueSubTier", ""),
                        "is_twilight": bool(csp_a.get("isTwilight", False)),
                        "saturday_reason": csp_a.get("saturdayReason", "Weekday"),
                    }
            except Exception:
                assignments = {}

        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "version": "1.0.0",
            "created_at": now_iso,
            "updated_at": now_iso,
            "dataset_mode": "1233_clean",
            "branding": deepcopy(DEFAULT_BRANDING),
            "schema": schema,
            "venue_affinity": affinity_config,
            "venues": venues,
            "sessions": primary_sessions,
            "teaching_periods": csp_raw.get("metadata", {}).get("teachingPeriods", []),
            "pinned_assignments": {},
            "assignments": assignments,
            "telemetry": telemetry,
        }

    def load_or_initialize(self) -> Dict[str, Any]:
        with self._lock:
            if self.state_path.exists():
                self.state = load_json(self.state_path)
                # Ensure required keys exist
                if "branding" not in self.state:
                    self.state["branding"] = deepcopy(DEFAULT_BRANDING)
                if "pinned_assignments" not in self.state:
                    self.state["pinned_assignments"] = {}
                return self.state

            self.state = self._build_default_state()
            self.save()
            return self.state

    def save(self) -> Path:
        with self._lock:
            self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.state_path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
                f.write("\n")
            tmp_path.replace(self.state_path)
            return self.state_path

    def reset_to_default(self) -> Dict[str, Any]:
        with self._lock:
            self.state = self._build_default_state()
            self.save()
            return self.state

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": self.state.get("version", "1.0.0"),
                "updated_at": self.state.get("updated_at"),
                "dataset_mode": self.state.get("dataset_mode", "1233_clean"),
                "branding": deepcopy(self.state.get("branding", DEFAULT_BRANDING)),
                "session_count": len(self.state.get("sessions", [])),
                "venue_count": len(self.state.get("venues", [])),
                "assigned_count": len(self.state.get("assignments", {})),
                "pinned_count": len(self.state.get("pinned_assignments", {})),
                "pinned_assignments": deepcopy(self.state.get("pinned_assignments", {})),
                "telemetry": deepcopy(self.state.get("telemetry", {})),
            }

    def update_branding(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            branding = self.state.setdefault("branding", deepcopy(DEFAULT_BRANDING))
            for k in ("institution_name", "semester_title", "logo_url"):
                if k in updates:
                    branding[k] = updates[k]
            self.save()
            return deepcopy(branding)

    def update_schema(self, schema_updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            current_schema = self.state.get("schema", {})
            for k, v in schema_updates.items():
                current_schema[k] = v
            self.state["schema"] = current_schema
            self.save()
            return deepcopy(current_schema)

    def _normalize_pin_entry(
        self,
        session_id: str,
        day: int | str,
        start_period: int,
        venue_id: int | str,
    ) -> Dict[str, Any]:
        """
        Validates a single pin against the active workspace's solver unary domain and compatible
        venues, returning a normalized pin dictionary:
        `{"day": day_str, "day_idx": day_idx, "start_period": int, "venue_id": canonical_vid}`.
        Raises ValueError on any invalid session, time slot, or venue.
        """
        solver = TimetableCSPSolver(
            sessions=self.state["sessions"],
            venues=self.state["venues"],
            schema=self.state["schema"],
            affinity_config=self.state.get("venue_affinity"),
        )
        day_str, sp, canonical_vid = solver._normalize_pin_tuple(
            session_id, (day, int(start_period), venue_id)
        )
        day_idx = solver.day_to_idx[day_str]
        return {
            "session_id": session_id,
            "day": day_str,
            "day_idx": day_idx,
            "start_period": sp,
            "venue_id": canonical_vid,
        }

    def get_pins_as_solver_tuples(
        self,
        override_pins: Optional[Dict[str, Tuple[int | str, int, int | str]]] = None,
    ) -> Dict[str, Tuple[int, int, int | str]]:
        """
        Converts persisted `pinned_assignments` (or explicit `override_pins`) into the
        `dict[str, tuple[int, int, str | int]]` format accepted by `TimetableCSPSolver.solve`.
        """
        with self._lock:
            if override_pins is not None:
                return dict(override_pins)  # type: ignore[arg-type]

            raw_pins = self.state.get("pinned_assignments", {})
            active_days = self.state["schema"]["calendar_grid"]["active_days"]
            day_to_idx = {d: i for i, d in enumerate(active_days)}

            result: Dict[str, Tuple[int, int, int | str]] = {}
            for sid, val in raw_pins.items():
                if isinstance(val, (list, tuple)) and len(val) == 3:
                    d_raw, sp_raw, vid_raw = val
                    if isinstance(d_raw, str) and d_raw.upper() in day_to_idx:
                        d_idx = day_to_idx[d_raw.upper()]
                    else:
                        d_idx = int(d_raw)
                    result[sid] = (d_idx, int(sp_raw), vid_raw)
                elif isinstance(val, dict):
                    if "day_idx" in val:
                        d_idx = int(val["day_idx"])
                    else:
                        d_idx = day_to_idx[str(val["day"]).upper()]
                    result[sid] = (d_idx, int(val["start_period"]), val["venue_id"])
            return result

    def set_pin(
        self,
        session_id: str,
        day: int | str,
        start_period: int,
        venue_id: int | str,
    ) -> Dict[str, Any]:
        """
        Validates and persists a session pin `(day_idx, start_period, venue_id)`, checking both
        unary validity and pairwise consistency against all existing pins.
        Raises ValueError if invalid or conflicting.
        """
        with self._lock:
            entry = self._normalize_pin_entry(session_id, day, start_period, venue_id)
            candidate_pins = self.get_pins_as_solver_tuples()
            candidate_pins[session_id] = (
                entry["day_idx"],
                entry["start_period"],
                entry["venue_id"],
            )

            # Run full pre-solve pin validation (unary + pairwise 108-bit conflicts)
            solver = TimetableCSPSolver(
                sessions=self.state["sessions"],
                venues=self.state["venues"],
                schema=self.state["schema"],
                affinity_config=self.state.get("venue_affinity"),
            )
            solver._validate_and_apply_pins(candidate_pins)

            self.state.setdefault("pinned_assignments", {})[session_id] = entry
            self.save()
            return deepcopy(entry)

    def remove_pin(self, session_id: str) -> bool:
        with self._lock:
            pins = self.state.setdefault("pinned_assignments", {})
            existed = session_id in pins
            if existed:
                del pins[session_id]
                self.save()
            return existed

    def clear_pins(self) -> int:
        with self._lock:
            pins = self.state.setdefault("pinned_assignments", {})
            count = len(pins)
            pins.clear()
            self.save()
            return count

    def solve_workspace(
        self,
        pinned_assignments: Optional[Dict[str, Tuple[int | str, int, int | str]]] = None,
        run_optimizer: bool = True,
        max_iterations: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Re-runs the CSP solver and Hard-Constraint-Preserving Simulated Annealing Optimizer
        around all active pinned sessions, updates `self.state["assignments"]` and
        `self.state["telemetry"]`, and persists to `data/processed/app_state.json`.
        """
        with self._lock:
            sessions = self.state["sessions"]
            venues = self.state["venues"]
            schema = self.state["schema"]
            affinity_config = self.state.get("venue_affinity")
            venue_by_id = {v["venueId"]: v for v in venues}
            active_days = schema["calendar_grid"]["active_days"]
            day_to_idx = {d: i for i, d in enumerate(active_days)}

            if pinned_assignments is not None:
                # Validate and persist the caller-supplied pins
                normalized_map: Dict[str, Dict[str, Any]] = {}
                for sid, (d_val, sp_val, vid_val) in pinned_assignments.items():
                    normalized_map[sid] = self._normalize_pin_entry(
                        sid, d_val, sp_val, vid_val
                    )
                solver_pins: Dict[str, Tuple[int | str, int, int | str]] = {
                    sid: (info["day_idx"], info["start_period"], info["venue_id"])
                    for sid, info in normalized_map.items()
                }
            else:
                solver_pins = self.get_pins_as_solver_tuples()
                normalized_map = deepcopy(self.state.get("pinned_assignments", {}))

            solver = TimetableCSPSolver(
                sessions=sessions,
                venues=venues,
                schema=schema,
                affinity_config=affinity_config,
                pinned_assignments=solver_pins,
            )
            csp_assignments, csp_stats = solver.solve(pinned_assignments=solver_pins)
            if csp_stats.status != "SOLVED":
                return {
                    "status": csp_stats.status,
                    "runtime_ms": round(csp_stats.runtime_seconds * 1000, 2),
                    "pinned_count": len(solver_pins),
                    "assigned_count": csp_stats.assigned_count,
                }

            final_assignments = csp_assignments
            opt_report: Dict[str, Any] = {"enabled": False}
            if run_optimizer and schema.get("optimizer", {}).get("enabled", True):
                optimizer = SimulatedAnnealingOptimizer(
                    sessions=sessions,
                    venues=venues,
                    schema=schema,
                    initial_assignments=csp_assignments,
                    compatible_venues=solver.compatible_venues,
                    venue_tier_label=solver.venue_tier_label,
                    affinity_config=affinity_config,
                    pinned_session_ids=set(solver_pins.keys()),
                )
                final_assignments, opt_stats = optimizer.optimize(
                    max_iterations=max_iterations
                )
                opt_report = opt_stats.to_dict()

            initial_domains = build_domains(
                sessions, venues, schema, affinity_config=affinity_config
            )
            verification = verify_solution(
                sessions,
                final_assignments,
                initial_domains,
                venue_tier_labels=solver.venue_tier_label,
            )
            sat_report = verification.get("saturday_report", {})
            sat_reasons = sat_report.get("session_reasons", {})

            formatted_assignments: Dict[str, Dict[str, Any]] = {}
            session_by_id = {s["sessionId"]: s for s in sessions}
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
                    "is_pinned": sid in solver_pins,
                }

            if pinned_assignments is not None:
                self.state["pinned_assignments"] = normalized_map
            self.state["assignments"] = formatted_assignments
            self.state["telemetry"] = {
                "status": csp_stats.status,
                "totalVariables": csp_stats.total_variables,
                "runtimeMs": round(csp_stats.runtime_seconds * 1000, 2),
                "nodesVisited": csp_stats.nodes_visited,
                "backtracks": csp_stats.backtracks,
                "prunedValues": csp_stats.pruned_values,
                "pinnedCount": len(solver_pins),
                "validHardConstraints": verification["valid"],
                "tier1AffinityCount": verification["tier_1_total"],
                "tier1AExactModuleCount": verification["tier_1a_count"],
                "cspSaturdayTotal": sat_report.get("csp_saturday_total", 0),
                "cspSaturdayFreeCohorts": sat_report.get("csp_saturday_free_cohorts", 0),
                "optimizer": opt_report,
            }
            self.save()
            return {
                "status": csp_stats.status,
                "valid": verification["valid"],
                "pinned_count": len(solver_pins),
                "assigned_count": len(formatted_assignments),
                "telemetry": deepcopy(self.state["telemetry"]),
            }

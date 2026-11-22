from __future__ import annotations

import json
import sys
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def validate_schema_config(schema_cfg: Any) -> List[str]:
    """
    Validates the structure and required keys of `schema_config` (supporting both
    guided UI updates and raw JSON editing). Returns a list of field-level error strings.
    """
    errors: List[str] = []
    if not isinstance(schema_cfg, dict):
        return ["schema_config must be a JSON object."]

    # 1. calendar_grid
    grid = schema_cfg.get("calendar_grid")
    if not isinstance(grid, dict):
        errors.append("Missing or invalid 'calendar_grid' object.")
    else:
        active_days = grid.get("active_days")
        if not isinstance(active_days, list) or len(active_days) == 0:
            errors.append("'calendar_grid.active_days' must be a non-empty list of day names.")
        elif not all(isinstance(d, str) and d.strip() for d in active_days):
            errors.append("'calendar_grid.active_days' must contain non-empty strings.")

        ppd = grid.get("periods_per_day")
        if not isinstance(ppd, int) or ppd < 1 or ppd > 30:
            errors.append("'calendar_grid.periods_per_day' must be an integer between 1 and 30.")

        breaks = grid.get("breaks_after_periods", [])
        if not isinstance(breaks, list) or not all(isinstance(b, int) for b in breaks):
            errors.append("'calendar_grid.breaks_after_periods' must be a list of integers.")

    # 2. streams
    streams = schema_cfg.get("streams")
    if not isinstance(streams, dict):
        errors.append("Missing or invalid 'streams' object.")
    else:
        for stream_key in ("full_time", "evening"):
            s_cfg = streams.get(stream_key)
            if not isinstance(s_cfg, dict):
                errors.append(f"Missing or invalid 'streams.{stream_key}' object.")
                continue
            min_p = s_cfg.get("min_period")
            max_p = s_cfg.get("max_period")
            if not isinstance(min_p, int) or not isinstance(max_p, int) or min_p < 1 or max_p < min_p:
                errors.append(
                    f"'streams.{stream_key}.min_period' and 'max_period' must be integers with 1 <= min_period <= max_period."
                )
            durs = s_cfg.get("supported_durations")
            if not isinstance(durs, list) or not durs or not all(isinstance(d, int) and d >= 1 for d in durs):
                errors.append(
                    f"'streams.{stream_key}.supported_durations' must be a non-empty list of positive integers."
                )

    # 3. venue_rules
    v_rules = schema_cfg.get("venue_rules")
    if not isinstance(v_rules, dict):
        errors.append("Missing or invalid 'venue_rules' object.")
    else:
        cmap = v_rules.get("compatibility_map")
        if not isinstance(cmap, dict) or len(cmap) == 0:
            errors.append("'venue_rules.compatibility_map' must be a non-empty object.")

    # 4. soft_constraints
    sc = schema_cfg.get("soft_constraints")
    if sc is not None:
        if not isinstance(sc, dict):
            errors.append("'soft_constraints' must be an object mapping rule names to configs.")
        else:
            for rname, rcfg in sc.items():
                if not isinstance(rcfg, dict):
                    errors.append(f"'soft_constraints.{rname}' must be an object.")
                    continue
                if "enabled" in rcfg and not isinstance(rcfg["enabled"], bool):
                    errors.append(f"'soft_constraints.{rname}.enabled' must be a boolean.")
                if "weight" in rcfg and not isinstance(rcfg["weight"], (int, float)):
                    errors.append(f"'soft_constraints.{rname}.weight' must be a number.")
                if "params" in rcfg and not isinstance(rcfg["params"], dict):
                    errors.append(f"'soft_constraints.{rname}.params' must be an object.")

    # 5. optimizer
    opt = schema_cfg.get("optimizer")
    if opt is not None:
        if not isinstance(opt, dict):
            errors.append("'optimizer' must be an object.")
        else:
            if "enabled" in opt and not isinstance(opt["enabled"], bool):
                errors.append("'optimizer.enabled' must be a boolean.")
            if "max_iterations" in opt and (
                not isinstance(opt["max_iterations"], int) or opt["max_iterations"] < 0
            ):
                errors.append("'optimizer.max_iterations' must be a non-negative integer.")
            if "initial_temperature" in opt and (
                not isinstance(opt["initial_temperature"], (int, float))
                or opt["initial_temperature"] <= 0
            ):
                errors.append("'optimizer.initial_temperature' must be a positive number.")
            if "cooling_rate" in opt and (
                not isinstance(opt["cooling_rate"], (int, float))
                or not (0.0 < float(opt["cooling_rate"]) < 1.0)
            ):
                errors.append("'optimizer.cooling_rate' must be a float strictly between 0 and 1.")

    return errors


class AppStateManager:
    """
    Manages the single active institution workspace persisted to `data/processed/app_state.json`.
    On first boot (when `app_state.json` does not exist), automatically preloads with:
      - ATC Clean Primary Dataset (Mode A: S0001..S1233, |X| = 1,233 sessions) and ATC venues/lecturers
      - `configs/institution_schema.json`
      - `configs/atc_venue_affinity.json`
      - Default branding
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
        self.uploads_dir = (self.root / "data" / "uploads").resolve()
        self._lock = threading.RLock()
        self.state: Dict[str, Any] = {}
        self.load_or_initialize()

    def _extract_default_lecturers(
        self,
        dataset: Dict[str, Any],
        sessions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        raw_lecturers = dataset.get("lecturers", [])
        if raw_lecturers:
            lecturers: List[Dict[str, Any]] = []
            for idx, lec in enumerate(raw_lecturers, start=1):
                name = str(lec.get("name", "")).strip()
                if not name:
                    continue
                progs = lec.get("programsTaught") or []
                dept = str(progs[0]) if progs else ""
                lecturers.append(
                    {
                        "lecturerId": f"L{idx:03d}",
                        "name": name,
                        "department": dept,
                    }
                )
            return lecturers

        names = sorted({l for s in sessions for l in s.get("lecturers", []) if l})
        return [
            {"lecturerId": f"L{idx:03d}", "name": name, "department": ""}
            for idx, name in enumerate(names, start=1)
        ]

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
        lecturers = self._extract_default_lecturers(dataset, primary_sessions)

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
        generated_at = datetime.now(timezone.utc).isoformat()
        if view_bundle_path.exists():
            try:
                bundle = load_json(view_bundle_path)
                generated_at = bundle.get("metadata", {}).get("generatedAt", generated_at)
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
        onboarding_sources = {
            "venues": {
                "filename": "atc-timetable-dataset.json",
                "row_count": len(venues),
                "updated_at": now_iso,
                "source": "preloaded_atc",
            },
            "lecturers": {
                "filename": "atc-timetable-dataset.json",
                "row_count": len(lecturers),
                "updated_at": now_iso,
                "source": "preloaded_atc",
            },
            "sessions": {
                "filename": "atc-csp-sessions.json",
                "row_count": len(primary_sessions),
                "updated_at": now_iso,
                "source": "preloaded_atc",
            },
            "affinity": {
                "filename": "atc_venue_affinity.json",
                "row_count": len(
                    affinity_config.get("module_and_prefix_rules", {}).get("by_module_code", {})
                ),
                "updated_at": now_iso,
                "source": "preloaded_atc",
            },
        }

        state_obj: Dict[str, Any] = {
            "version": "1.1.0",
            "created_at": now_iso,
            "updated_at": now_iso,
            "dataset_mode": "1233_clean",
            "branding": deepcopy(DEFAULT_BRANDING),
            "logo_file": None,
            "schema": schema,
            "venue_affinity": affinity_config,
            "venues": venues,
            "lecturers": lecturers,
            "sessions": primary_sessions,
            "teaching_periods": csp_raw.get("metadata", {}).get("teachingPeriods", []),
            "onboarding_sources": onboarding_sources,
            "pinned_assignments": {},
            "assignments": assignments,
            "telemetry": telemetry,
            "active_timetable": {
                "generated_at": generated_at,
                "has_timetable": len(assignments) > 0,
                "status": telemetry.get("status", "SOLVED" if assignments else "EMPTY"),
                "kpis": {},
                "scorecard": telemetry.get("optimizer", {}),
                "saturday_explanations": [],
            },
        }
        return state_obj

    def _ensure_state_migrations(self) -> None:
        """Backfills Sprint 2 keys cleanly when loading an older Sprint 1 app_state.json."""
        now_iso = datetime.now(timezone.utc).isoformat()
        dirty = False
        if "branding" not in self.state:
            self.state["branding"] = deepcopy(DEFAULT_BRANDING)
            dirty = True
        if "logo_file" not in self.state:
            self.state["logo_file"] = None
            dirty = True
        if "pinned_assignments" not in self.state:
            self.state["pinned_assignments"] = {}
            dirty = True
        if "lecturers" not in self.state:
            names = sorted(
                {l for s in self.state.get("sessions", []) for l in s.get("lecturers", []) if l}
            )
            self.state["lecturers"] = [
                {"lecturerId": f"L{idx:03d}", "name": name, "department": ""}
                for idx, name in enumerate(names, start=1)
            ]
            dirty = True
        if "onboarding_sources" not in self.state:
            affinity = self.state.get("venue_affinity") or {}
            self.state["onboarding_sources"] = {
                "venues": {
                    "filename": "atc-timetable-dataset.json",
                    "row_count": len(self.state.get("venues", [])),
                    "updated_at": now_iso,
                    "source": "preloaded_atc",
                },
                "lecturers": {
                    "filename": "atc-timetable-dataset.json",
                    "row_count": len(self.state.get("lecturers", [])),
                    "updated_at": now_iso,
                    "source": "preloaded_atc",
                },
                "sessions": {
                    "filename": "atc-csp-sessions.json",
                    "row_count": len(self.state.get("sessions", [])),
                    "updated_at": now_iso,
                    "source": "preloaded_atc",
                },
                "affinity": {
                    "filename": "atc_venue_affinity.json",
                    "row_count": len(
                        affinity.get("module_and_prefix_rules", {}).get("by_module_code", {})
                    ),
                    "updated_at": now_iso,
                    "source": "preloaded_atc",
                },
            }
            dirty = True
        if "active_timetable" not in self.state:
            assignments = self.state.get("assignments", {})
            telemetry = self.state.get("telemetry", {})
            self.state["active_timetable"] = {
                "generated_at": self.state.get("updated_at", now_iso),
                "has_timetable": len(assignments) > 0,
                "status": telemetry.get("status", "SOLVED" if assignments else "EMPTY"),
                "kpis": {},
                "scorecard": telemetry.get("optimizer", {}),
                "saturday_explanations": [],
            }
            dirty = True
        if dirty:
            self.save()

    def load_or_initialize(self) -> Dict[str, Any]:
        with self._lock:
            if self.state_path.exists():
                self.state = load_json(self.state_path)
                self._ensure_state_migrations()
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
                "version": self.state.get("version", "1.1.0"),
                "updated_at": self.state.get("updated_at"),
                "dataset_mode": self.state.get("dataset_mode", "1233_clean"),
                "branding": deepcopy(self.state.get("branding", DEFAULT_BRANDING)),
                "session_count": len(self.state.get("sessions", [])),
                "venue_count": len(self.state.get("venues", [])),
                "lecturer_count": len(self.state.get("lecturers", [])),
                "assigned_count": len(self.state.get("assignments", {})),
                "pinned_count": len(self.state.get("pinned_assignments", {})),
                "pinned_assignments": deepcopy(self.state.get("pinned_assignments", {})),
                "telemetry": deepcopy(self.state.get("telemetry", {})),
            }

    def get_settings(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "branding": deepcopy(self.state.get("branding", DEFAULT_BRANDING)),
                "schema_config": deepcopy(self.state.get("schema", {})),
            }

    def update_branding(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            branding = self.state.setdefault("branding", deepcopy(DEFAULT_BRANDING))
            for k in ("institution_name", "semester_title", "logo_url"):
                if k in updates:
                    branding[k] = updates[k]
            self.save()
            return deepcopy(branding)

    def set_logo(self, saved_filename: str) -> Dict[str, Any]:
        with self._lock:
            self.state["logo_file"] = saved_filename
            branding = self.state.setdefault("branding", deepcopy(DEFAULT_BRANDING))
            branding["logo_url"] = "/api/public/logo"
            self.save()
            return deepcopy(branding)

    def get_logo_path(self) -> Optional[Path]:
        with self._lock:
            logo_file = self.state.get("logo_file")
            if logo_file:
                candidate = self.uploads_dir / logo_file
                if candidate.exists() and candidate.is_file():
                    return candidate
            # Fallback scan for data/uploads/logo.<ext>
            if self.uploads_dir.exists():
                for ext in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
                    p = self.uploads_dir / f"logo{ext}"
                    if p.exists() and p.is_file():
                        return p
            return None

    def replace_schema(self, new_schema: Dict[str, Any]) -> Dict[str, Any]:
        errors = validate_schema_config(new_schema)
        if errors:
            raise ValueError("; ".join(errors))
        with self._lock:
            self.state["schema"] = deepcopy(new_schema)
            self.save()
            return deepcopy(self.state["schema"])

    def reset_schema_to_default(self) -> Dict[str, Any]:
        default_schema = load_json(self.root / "configs" / "institution_schema.json")
        with self._lock:
            self.state["schema"] = deepcopy(default_schema)
            self.save()
            return deepcopy(self.state["schema"])

    def update_entity_data(
        self,
        entity: str,
        rows: List[Dict[str, Any]],
        filename: str,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Updates a single onboarding entity (`venues`, `lecturers`, or `sessions`) independently."""
        with self._lock:
            now_iso = datetime.now(timezone.utc).isoformat()
            self.state[entity] = rows
            self.state["dataset_mode"] = "custom_upload"
            sources = self.state.setdefault("onboarding_sources", {})
            entry: Dict[str, Any] = {
                "filename": filename,
                "row_count": len(rows),
                "updated_at": now_iso,
                "source": "custom_upload",
            }
            if extra_meta:
                entry.update(extra_meta)
            sources[entity] = entry
            # If sessions or venues were replaced with custom uploads, clear stale pins for missing IDs
            if entity == "sessions":
                valid_sids = {s["sessionId"] for s in rows}
                pins = self.state.get("pinned_assignments", {})
                self.state["pinned_assignments"] = {
                    k: v for k, v in pins.items() if k in valid_sids
                }
            self.save()
            return deepcopy(sources[entity])

    def _normalize_pin_entry(
        self,
        session_id: str,
        day: int | str,
        start_period: int,
        venue_id: int | str,
    ) -> Dict[str, Any]:
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
        with self._lock:
            entry = self._normalize_pin_entry(session_id, day, start_period, venue_id)
            candidate_pins = self.get_pins_as_solver_tuples()
            candidate_pins[session_id] = (
                entry["day_idx"],
                entry["start_period"],
                entry["venue_id"],
            )

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

    def validate_active_dataset(
        self,
        schema_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Runs `run_preflight_checks` and referential integrity checks across the active
        dataset (`venues`, `lecturers`, `sessions`) and `schema_config`.
        Returns a structured row-level report:
        `{"passed": bool, "summary": {...}, "errors": [...], "warnings": [...]}`.
        """
        with self._lock:
            sessions = self.state.get("sessions", [])
            venues = self.state.get("venues", [])
            lecturers = self.state.get("lecturers", [])
            schema = schema_override if schema_override is not None else self.state.get("schema", {})
            affinity_config = self.state.get("venue_affinity")

        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        schema_errs = validate_schema_config(schema)
        for msg in schema_errs:
            errors.append(
                {
                    "entity": "schema",
                    "row": None,
                    "id": "schema_config",
                    "code": "INVALID_SCHEMA",
                    "message": msg,
                }
            )

        if not sessions:
            errors.append(
                {
                    "entity": "sessions",
                    "row": None,
                    "id": None,
                    "code": "EMPTY_DATASET",
                    "message": "No sessions loaded in workspace.",
                }
            )
        if not venues:
            errors.append(
                {
                    "entity": "venues",
                    "row": None,
                    "id": None,
                    "code": "EMPTY_DATASET",
                    "message": "No venues loaded in workspace.",
                }
            )

        # Build lookup catalogs
        venue_ids_str = {str(v.get("venueId")) for v in venues}
        venue_names_lower = {str(v.get("name", "")).strip().lower() for v in venues}
        lecturer_names_lower = {str(l.get("name", "")).strip().lower() for l in lecturers}
        compat_categories = set(
            schema.get("venue_rules", {}).get("compatibility_map", {}).keys()
        )
        ft_durs = set(schema.get("streams", {}).get("full_time", {}).get("supported_durations", [1, 2, 4, 6]))
        eve_durs = set(schema.get("streams", {}).get("evening", {}).get("supported_durations", [1, 2, 4, 6]))

        seen_sids: Dict[str, int] = {}
        all_cohorts: set[str] = set()
        all_session_lecturers: set[str] = set()
        cohort_last_row: Dict[str, Tuple[int, str]] = {}
        lecturer_last_row: Dict[str, Tuple[int, str]] = {}

        for row_idx, s in enumerate(sessions, start=1):
            sid = str(s.get("sessionId", "")).strip()
            if not sid:
                errors.append(
                    {
                        "entity": "sessions",
                        "row": row_idx,
                        "id": None,
                        "code": "MISSING_SESSION_ID",
                        "message": f"Row {row_idx} is missing a session_id.",
                    }
                )
            elif sid in seen_sids:
                errors.append(
                    {
                        "entity": "sessions",
                        "row": row_idx,
                        "id": sid,
                        "code": "DUPLICATE_SESSION_ID",
                        "message": f"Duplicate session_id '{sid}' (first seen at row {seen_sids[sid]}).",
                    }
                )
            else:
                seen_sids[sid] = row_idx

            dur = s.get("durationPeriods")
            is_eve = bool(s.get("isEveningStream", False))
            allowed_durs = eve_durs if is_eve else ft_durs
            if not isinstance(dur, int) or dur not in allowed_durs:
                errors.append(
                    {
                        "entity": "sessions",
                        "row": row_idx,
                        "id": sid,
                        "code": "INVALID_DURATION",
                        "message": f"Session '{sid}' has unsupported durationPeriods={dur} for {'Evening' if is_eve else 'Full-Time'} stream (allowed: {sorted(allowed_durs)}).",
                    }
                )

            req_cat = str(s.get("requiredVenueCategory", "")).strip()
            if compat_categories and req_cat not in compat_categories:
                errors.append(
                    {
                        "entity": "sessions",
                        "row": row_idx,
                        "id": sid,
                        "code": "UNKNOWN_VENUE_CATEGORY",
                        "message": f"Session '{sid}' requires unknown venue category '{req_cat}'.",
                    }
                )

            cohs = s.get("targetCohorts") or []
            if not cohs:
                warnings.append(
                    {
                        "entity": "sessions",
                        "row": row_idx,
                        "id": sid,
                        "code": "NO_COHORTS",
                        "message": f"Session '{sid}' has no target cohorts assigned.",
                    }
                )
            for c in cohs:
                all_cohorts.add(c)
                cohort_last_row[c] = (row_idx, sid)

            lecs = s.get("lecturers") or []
            for l in lecs:
                all_session_lecturers.add(l)
                lecturer_last_row[l] = (row_idx, sid)
                if lecturer_names_lower and str(l).strip().lower() not in lecturer_names_lower:
                    warnings.append(
                        {
                            "entity": "sessions",
                            "row": row_idx,
                            "id": sid,
                            "code": "UNREGISTERED_LECTURER",
                            "message": f"Lecturer '{l}' in session '{sid}' is not listed in the lecturers catalog.",
                        }
                    )

            pref_v = s.get("preferredVenue")
            if pref_v is not None and str(pref_v).strip() != "":
                pv_str = str(pref_v).strip()
                if pv_str not in venue_ids_str and pv_str.lower() not in venue_names_lower:
                    warnings.append(
                        {
                            "entity": "sessions",
                            "row": row_idx,
                            "id": sid,
                            "code": "UNKNOWN_PREFERRED_VENUE",
                            "message": f"Preferred venue '{pv_str}' for session '{sid}' was not found in venues.",
                        }
                    )

        # Run pigeonhole preflight checks if schema and basic datasets exist
        if not schema_errs and sessions and venues:
            # Use affinity config only if dataset is preloaded ATC and includes non-Theory sessions
            has_specialized_sessions = any(
                str(s.get("requiredVenueCategory", "")).strip() != "Theory / Lecture Room"
                for s in sessions
            )
            active_affinity = (
                affinity_config
                if (
                    self.state.get("dataset_mode") != "custom_upload"
                    and has_specialized_sessions
                )
                else None
            )
            preflight = run_preflight_checks(
                sessions=sessions,
                venues=venues,
                schema=schema,
                include_fallback_venues=False,
                affinity_config=active_affinity,
            )

            for v in preflight["cohort_check"]["violations"]:
                coh = v["cohort"]
                r_idx, r_sid = cohort_last_row.get(coh, (None, coh))
                stream_lbl = "Evening" if v["evening_periods"] > 0 and v["full_time_periods"] == 0 else "FT"
                errors.append(
                    {
                        "entity": "sessions",
                        "row": r_idx,
                        "id": r_sid,
                        "code": "PIGEONHOLE_OVERFLOW",
                        "message": (
                            f"Cohort {coh} has {v['demand_periods']} {stream_lbl} periods assigned "
                            f"(exceeds {v['available_periods']}p weekly ceiling)."
                        ),
                    }
                )

            for v in preflight["lecturer_check"]["violations"]:
                lec = v["lecturer"]
                r_idx, r_sid = lecturer_last_row.get(lec, (None, lec))
                errors.append(
                    {
                        "entity": "sessions",
                        "row": r_idx,
                        "id": r_sid,
                        "code": "LECTURER_OVERFLOW",
                        "message": (
                            f"Lecturer {lec} has {v['demand_periods']} periods assigned "
                            f"(exceeds {v['available_periods']}p weekly ceiling)."
                        ),
                    }
                )

            for v in preflight["venue_category_check"]["violations"]:
                errors.append(
                    {
                        "entity": "venues",
                        "row": None,
                        "id": v["category"],
                        "code": "VENUE_CATEGORY_OVERFLOW",
                        "message": (
                            f"Venue category '{v['category']}' ({v['stream']}) requires "
                            f"{v['demand_periods']}p but only {v['capacity_periods']}p are available."
                        ),
                    }
                )

            for v in preflight["subpool_check"]["violations"]:
                errors.append(
                    {
                        "entity": "venues",
                        "row": None,
                        "id": v["category"],
                        "code": "SUBPOOL_OVERFLOW",
                        "message": (
                            f"Restricted sub-pool for '{v['category']}' ({v['stream']}) requires "
                            f"{v['demand_periods']}p > {v['capacity_periods']}p capacity."
                        ),
                    }
                )

        summary = {
            "sessions": len(sessions),
            "cohorts": len(all_cohorts),
            "lecturers": len(lecturers) if lecturers else len(all_session_lecturers),
            "venues": len(venues),
        }
        return {
            "passed": len(errors) == 0,
            "summary": summary,
            "errors": errors,
            "warnings": warnings,
        }

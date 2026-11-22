from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from src.api.auth import create_access_token
from src.api.chunker import (
    chunk_weekly_periods,
    expand_allocation_to_sessions,
    get_period_duration_minutes,
    hours_to_weekly_periods,
)
from src.api.main import create_app
from src.api.state import AppStateManager, validate_schema_config

ATC_CHUNKING_CONFIG = {
    "min_periods": 2,
    "by_type": {
        "Theory": {"preferred": 2, "max": 2},
        "Tutorial": {"preferred": 1, "max": 2},
        "Lab": {"preferred": 3, "max": 4},
        "Workshop": {"preferred": 4, "max": 4},
    },
    "default": {"preferred": 2, "max": 3},
}


class TestChunkerUnit(unittest.TestCase):
    def test_period_duration_from_schema_grid(self) -> None:
        schema_50 = {
            "calendar_grid": {
                "period_duration_minutes": 45,
                "periods": [
                    {"period_number": 1, "start_time": "08:00", "end_time": "08:50"},
                    {"period_number": 2, "start_time": "08:50", "end_time": "09:40"},
                ],
            }
        }
        self.assertEqual(get_period_duration_minutes(schema_50), 50)

        schema_60 = {
            "calendar_grid": {
                "periods": [
                    {"period_number": 1, "start_time": "08:00", "end_time": "09:00"},
                ],
            }
        }
        self.assertEqual(get_period_duration_minutes(schema_60), 60)

        self.assertEqual(get_period_duration_minutes({}), 45)
        self.assertEqual(get_period_duration_minutes(None), 45)

    def test_hours_to_weekly_periods_and_rounding_warnings(self) -> None:
        wp, warn = hours_to_weekly_periods(3.0, 45, row_num=1, module_code="CST 05102")
        self.assertEqual(wp, 4)
        self.assertIsNone(warn)

        wp60, warn60 = hours_to_weekly_periods(3.0, 60, row_num=2, module_code="CST 05103")
        self.assertEqual(wp60, 3)
        self.assertIsNone(warn60)

        wp50, warn50 = hours_to_weekly_periods(2.0, 50, row_num=4, module_code="CST 05102")
        self.assertEqual(wp50, 2)
        self.assertIsNotNone(warn50)
        self.assertIn("Row 4", warn50 or "")
        self.assertIn("CST 05102", warn50 or "")
        self.assertIn("50-min grid", warn50 or "")
        self.assertIn("2.4 periods", warn50 or "")

        with self.assertRaises(ValueError):
            hours_to_weekly_periods(0, 45, row_num=1, module_code="BAD 101")

    def test_atc_default_config_driven_splitting(self) -> None:
        # Theory: {preferred: 2, max: 2}
        self.assertEqual(chunk_weekly_periods(4, "Theory", chunking_config=ATC_CHUNKING_CONFIG), [2, 2])
        self.assertEqual(chunk_weekly_periods(6, "Theory", chunking_config=ATC_CHUNKING_CONFIG), [2, 2, 2])
        self.assertEqual(chunk_weekly_periods(3, "theory", chunking_config=ATC_CHUNKING_CONFIG), [2, 1])

        # Lab: {preferred: 3, max: 4}
        self.assertEqual(chunk_weekly_periods(3, "Lab", chunking_config=ATC_CHUNKING_CONFIG), [3])
        self.assertEqual(chunk_weekly_periods(4, "Lab", chunking_config=ATC_CHUNKING_CONFIG), [4])
        self.assertEqual(chunk_weekly_periods(6, "Lab", chunking_config=ATC_CHUNKING_CONFIG), [3, 3])
        self.assertEqual(chunk_weekly_periods(7, "Lab", chunking_config=ATC_CHUNKING_CONFIG), [4, 3])

        # Workshop: {preferred: 4, max: 4}
        self.assertEqual(chunk_weekly_periods(4, "Workshop", chunking_config=ATC_CHUNKING_CONFIG), [4])
        self.assertEqual(chunk_weekly_periods(8, "Workshop", chunking_config=ATC_CHUNKING_CONFIG), [4, 4])

        # Tutorial: {preferred: 1, max: 2}
        self.assertIn(
            chunk_weekly_periods(2, "Tutorial", chunking_config=ATC_CHUNKING_CONFIG),
            ([1, 1], [2]),
        )

    def test_custom_60min_university_config_and_unknown_type_fallback(self) -> None:
        uni_60_cfg = {
            "min_periods": 2,
            "by_type": {
                "Theory": {"preferred": 1, "max": 2},
                "Lab": {"preferred": 3, "max": 3},
            },
            "default": {"preferred": 2, "max": 3},
        }
        # Theory: {preferred: 1, max: 2}
        self.assertEqual(chunk_weekly_periods(1, "Theory", chunking_config=uni_60_cfg), [1])
        self.assertEqual(chunk_weekly_periods(2, "Theory", chunking_config=uni_60_cfg), [1, 1])
        self.assertEqual(chunk_weekly_periods(3, "Theory", chunking_config=uni_60_cfg), [1, 1, 1])

        # Lab: {preferred: 3, max: 3} -> 7p borrows 1 to balance [3, 2, 2]
        self.assertEqual(chunk_weekly_periods(3, "Lab", chunking_config=uni_60_cfg), [3])
        self.assertEqual(chunk_weekly_periods(6, "Lab", chunking_config=uni_60_cfg), [3, 3])
        self.assertEqual(chunk_weekly_periods(7, "Lab", chunking_config=uni_60_cfg), [3, 2, 2])

        # Unknown / custom session type falls back cleanly to default {preferred: 2, max: 3}
        self.assertEqual(chunk_weekly_periods(3, "Clinical", chunking_config=uni_60_cfg), [3])
        self.assertEqual(chunk_weekly_periods(4, "Seminar", chunking_config=uni_60_cfg), [2, 2])
        self.assertEqual(chunk_weekly_periods(5, "Studio", chunking_config=uni_60_cfg), [3, 2])
        self.assertEqual(chunk_weekly_periods(7, "Studio", chunking_config=uni_60_cfg), [3, 2, 2])

    def test_split_override_overrides_chunking_config(self) -> None:
        self.assertEqual(
            chunk_weekly_periods(6, "Theory", split_override="3+3", chunking_config=ATC_CHUNKING_CONFIG),
            [3, 3],
        )
        self.assertEqual(
            chunk_weekly_periods(6, "Lab", split_override="2,2,2", chunking_config=ATC_CHUNKING_CONFIG),
            [2, 2, 2],
        )
        self.assertEqual(
            chunk_weekly_periods(4, "Theory", split_override="4", chunking_config=ATC_CHUNKING_CONFIG),
            [4],
        )

        with self.assertRaises(ValueError) as ctx:
            chunk_weekly_periods(
                4,
                "Theory",
                split_override="3+2",
                row_label="Row 2 (CS101)",
                chunking_config=ATC_CHUNKING_CONFIG,
            )
        self.assertIn("Row 2 (CS101)", str(ctx.exception))
        self.assertIn("sums to 5", str(ctx.exception))

        with self.assertRaises(ValueError):
            chunk_weekly_periods(4, "Theory", split_override="2+abc", chunking_config=ATC_CHUNKING_CONFIG)

    def test_schema_validation_rejects_invalid_session_chunking(self) -> None:
        bad_schema = {
            "calendar_grid": {"active_days": ["MONDAY"], "periods_per_day": 12, "breaks_after_periods": []},
            "streams": {
                "full_time": {"min_period": 1, "max_period": 12, "supported_durations": [1, 2]},
                "evening": {"min_period": 13, "max_period": 18, "supported_durations": [1, 2]},
            },
            "venue_rules": {"compatibility_map": {"Theory / Lecture Room": {"primary": ["Theory / Lecture Room"], "fallback": []}}},
            "session_chunking": {
                "min_periods": 0,
                "by_type": {"Lab": {"preferred": 4, "max": 2}},
                "default": {"preferred": 2, "max": 3},
            },
        }
        errs = validate_schema_config(bad_schema)
        self.assertTrue(any("min_periods" in e for e in errs), errs)
        self.assertTrue(any("by_type.Lab.max" in e for e in errs), errs)

    def test_deterministic_expansion(self) -> None:
        sessions = expand_allocation_to_sessions(
            base_id="ALLOC_001",
            chunks=[2, 2],
            module_code="CST 05102",
            module_name="Computer Networks",
            session_type="Theory",
            required_venue_category="Theory / Lecture Room",
            cohorts=["L5CS"],
            lecturers=["Dr. Juma"],
            is_evening_stream=False,
            preferred_venue=None,
        )
        self.assertEqual(len(sessions), 2)
        self.assertEqual([s["sessionId"] for s in sessions], ["ALLOC_001_1", "ALLOC_001_2"])
        self.assertEqual([s["durationPeriods"] for s in sessions], [2, 2])
        self.assertEqual(sessions[0]["moduleCode"], "CST 05102")
        self.assertEqual(sessions[0]["targetCohorts"], ["L5CS"])


class TestOnboardingChunkerAndTheoryOnlyAPI(unittest.TestCase):
    def _make_client(self, tmpdir: str) -> tuple[TestClient, dict[str, str]]:
        state_path = Path(tmpdir) / "app_state.json"
        manager = AppStateManager(state_path=state_path)
        manager.uploads_dir = Path(tmpdir) / "uploads"
        app = create_app(state_manager=manager)
        token = create_access_token("admin")
        headers = {"Authorization": f"Bearer {token}"}
        return TestClient(app), headers

    def test_template_download_and_upload_uses_schema_session_chunking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client, headers = self._make_client(tmpdir)

            tpl_res = client.get("/api/onboarding/templates/sessions", headers=headers)
            self.assertEqual(tpl_res.status_code, 200)
            csv_bytes = tpl_res.content
            self.assertIn(b"hours_per_week", csv_bytes)
            self.assertIn(b"split_override", csv_bytes)

            # On ATC defaults: Theory 3h=4p -> [2, 2] (2 sessions), Lab 3h=4p -> [4] (1 session) => 3 sessions
            up_res = client.post(
                "/api/onboarding/upload/sessions",
                headers=headers,
                files={"file": ("sessions_template.csv", csv_bytes, "text/csv")},
            )
            self.assertEqual(up_res.status_code, 200, up_res.text)
            body = up_res.json()
            self.assertEqual(body["entity"], "sessions")
            self.assertEqual(body["mode"], "allocations_hours")
            self.assertEqual(body["input_rows"], 2)
            self.assertEqual(body["rows_loaded"], 3)
            self.assertEqual(body["period_duration_minutes"], 45)
            self.assertEqual(body["warnings"], [])

            status_res = client.get("/api/onboarding/status", headers=headers)
            self.assertEqual(status_res.status_code, 200)
            s_meta = status_res.json()["entities"]["sessions"]
            self.assertEqual(s_meta["input_rows"], 2)
            self.assertEqual(s_meta["row_count"], 3)

    def test_weekly_periods_and_legacy_duration_periods_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client, headers = self._make_client(tmpdir)

            wp_csv = (
                "module_code,module_name,session_type,weekly_periods,cohorts,lecturers,is_evening_stream,preferred_venue,split_override\n"
                "CS 101,Algorithms,Theory,6,C1,Dr. A,false,,\n"
            ).encode("utf-8")
            res_wp = client.post(
                "/api/onboarding/upload/sessions",
                headers=headers,
                files={"file": ("wp.csv", wp_csv, "text/csv")},
            )
            self.assertEqual(res_wp.status_code, 200, res_wp.text)
            self.assertEqual(res_wp.json()["mode"], "allocations_periods")
            self.assertEqual(res_wp.json()["input_rows"], 1)
            self.assertEqual(res_wp.json()["rows_loaded"], 3)  # 6 Theory -> [2, 2, 2]

            legacy_csv = (
                "session_id,module_code,module_name,session_type,duration_periods,cohorts,lecturers,is_evening_stream,preferred_venue\n"
                "S0001,CS 101,Algorithms,Theory,2,C1,Dr. A,false,\n"
            ).encode("utf-8")
            res_leg = client.post(
                "/api/onboarding/upload/sessions",
                headers=headers,
                files={"file": ("legacy.csv", legacy_csv, "text/csv")},
            )
            self.assertEqual(res_leg.status_code, 200, res_leg.text)
            self.assertEqual(res_leg.json()["mode"], "legacy_sessions")
            self.assertEqual(res_leg.json()["rows_loaded"], 1)

    def test_theory_only_institution_validates_and_solves_zero_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client, headers = self._make_client(tmpdir)

            venues_csv = (
                "venue_id,name,capacity,venue_type,department_prefix\n"
                "101,Lecture Hall A,120,Theory / Lecture Room,GEN\n"
                "102,Lecture Hall B,90,Theory / Lecture Room,GEN\n"
            ).encode("utf-8")
            lecturers_csv = (
                "lecturer_id,name,department\n"
                "L001,Dr. Amina,Business\n"
                "L002,Dr. Juma,Law\n"
            ).encode("utf-8")
            sessions_csv = (
                "module_code,module_name,session_type,hours_per_week,cohorts,lecturers,is_evening_stream,preferred_venue,split_override\n"
                "BUS 101,Accounting,Theory,3,BBA1,Dr. Amina,false,,\n"
                "LAW 102,Contract Law,Theory,3,BBA1,Dr. Juma,false,,\n"
                "BUS 201,Economics,Theory,1.5,BBA2,Dr. Amina,false,,\n"
            ).encode("utf-8")

            self.assertEqual(
                client.post(
                    "/api/onboarding/upload/venues",
                    headers=headers,
                    files={"file": ("venues.csv", venues_csv, "text/csv")},
                ).status_code,
                200,
            )
            self.assertEqual(
                client.post(
                    "/api/onboarding/upload/lecturers",
                    headers=headers,
                    files={"file": ("lecturers.csv", lecturers_csv, "text/csv")},
                ).status_code,
                200,
            )
            up_sess = client.post(
                "/api/onboarding/upload/sessions",
                headers=headers,
                files={"file": ("sessions.csv", sessions_csv, "text/csv")},
            )
            self.assertEqual(up_sess.status_code, 200, up_sess.text)
            self.assertEqual(up_sess.json()["rows_loaded"], 5)

            val_res = client.post("/api/onboarding/validate", headers=headers)
            self.assertEqual(val_res.status_code, 200)
            val_body = val_res.json()
            self.assertTrue(val_body["passed"], val_body)
            self.assertEqual(val_body["errors"], [])
            self.assertEqual(val_body["warnings"], [])

            solve_res = client.post(
                "/api/solve",
                headers=headers,
                json={"run_optimizer": False, "use_pins": False},
            )
            self.assertEqual(solve_res.status_code, 200, solve_res.text)
            solve_body = solve_res.json()
            self.assertEqual(solve_body["kpis"]["hard_violations"], 0)
            self.assertEqual(solve_body["kpis"]["assigned_sessions"], 5)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from src.api.auth import create_access_token
from src.api.main import create_app
from src.api.state import AppStateManager


class TestPdfExportEndpoints(unittest.TestCase):
    def _make_client(self, tmpdir: str) -> tuple[TestClient, dict[str, str]]:
        root = Path(__file__).resolve().parents[1]
        state_path = Path(tmpdir) / "app_state.json"
        manager = AppStateManager(root=root, state_path=state_path)
        manager.uploads_dir = Path(tmpdir) / "uploads"
        app = create_app(state_manager=manager)
        token = create_access_token("admin")
        headers = {"Authorization": f"Bearer {token}"}
        return TestClient(app), headers

    def test_public_single_cohort_pdf_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client, _ = self._make_client(tmpdir)

            # Public endpoint requires NO auth header
            res = client.get("/api/public/export/pdf", params={"lens": "cohort", "id": "L7-2CS"})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.headers.get("content-type"), "application/pdf")
            self.assertIn("L7-2CS_timetable.pdf", res.headers.get("content-disposition", ""))
            self.assertTrue(res.content.startswith(b"%PDF-"))
            self.assertGreater(len(res.content), 1000)

            # Unknown entity returns 404
            missing = client.get(
                "/api/public/export/pdf",
                params={"lens": "cohort", "id": "NON_EXISTENT_COHORT"},
            )
            self.assertEqual(missing.status_code, 404)

    def test_master_pdf_requires_auth_and_returns_multipage_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client, headers = self._make_client(tmpdir)

            # Unauthenticated -> 401
            unauth = client.get("/api/export/master-pdf", params={"lens": "cohort"})
            self.assertEqual(unauth.status_code, 401)

            # Authenticated -> 200 multi-page PDF
            res = client.get(
                "/api/export/master-pdf",
                params={"lens": "cohort"},
                headers=headers,
            )
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.headers.get("content-type"), "application/pdf")
            self.assertIn(
                "master_cohort_timetables.pdf",
                res.headers.get("content-disposition", ""),
            )
            self.assertTrue(res.content.startswith(b"%PDF-"))
            # Verify multi-page PDF (121 cohorts -> multiple page objects)
            self.assertGreater(res.content.count(b"/Type /Page"), 10)

    def test_adjacent_identical_sessions_merge_without_crossing_breaks(self) -> None:
        from src.api.pdf_export import merge_adjacent_sessions

        base = {
            "module_code": "CSU 07318",
            "session_type": "Lab",
            "venue_id": 10,
            "venue_name": "Comp R42 Lab",
            "lecturers": ["Abdulkadir Kirobo"],
            "cohorts": ["L7-2CS"],
            "day": "MONDAY",
        }
        # P1-P2 + P3-P4 (no break between P2 and P3) -> MUST merge into P1-P4 (duration 4)
        # P5-P6 (after Tea break at P4) -> MUST NOT merge across break after P4!
        day_sessions = [
            {**base, "session_id": "A1", "start_period": 1, "duration_periods": 2},
            {**base, "session_id": "A2", "start_period": 3, "duration_periods": 2},
            {**base, "session_id": "A3", "start_period": 5, "duration_periods": 2},
        ]
        merged = merge_adjacent_sessions(day_sessions, break_slots={4, 6})
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["start_period"], 1)
        self.assertEqual(merged[0]["duration_periods"], 4)
        self.assertEqual(merged[1]["start_period"], 5)
        self.assertEqual(merged[1]["duration_periods"], 2)


if __name__ == "__main__":
    unittest.main()

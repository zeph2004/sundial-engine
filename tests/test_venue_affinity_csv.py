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


class TestVenueAffinityOnUploadedCsvs(unittest.TestCase):
    def test_cs_it_labs_stay_in_computer_labs_not_unrelated_dept_labs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = AppStateManager(root=root, state_path=Path(tmpdir) / "app_state.json")
            mgr.uploads_dir = Path(tmpdir) / "uploads"
            client = TestClient(create_app(state_manager=mgr))
            headers = {"Authorization": f"Bearer {create_access_token('admin')}"}

            venues_csv = (
                "venue_id,name,capacity,venue_type,department_prefix\n"
                "1,Room A1,100,Theory / Lecture Room,GEN\n"
                "2,Comp R21 Lab,45,Computer / Digital Lab,CSU;ITU;CST;ITT\n"
                "3,Comp R42 Lab,45,Computer / Digital Lab,CSU;ITU;CST;ITT\n"
                "4,Biology Lab,40,Engineering / Science Lab,BIO\n"
                "5,Hydraulics Lab,40,Engineering / Science Lab,CE;CEU\n"
                "6,Soil and Bitumen Lab,40,Engineering / Science Lab,CE;CEU\n"
            ).encode("utf-8")

            lecturers_csv = (
                "lecturer_id,name,department\n"
                "L001,Dr. Juma,Computer Science\n"
                "L002,Dr. Amina,Biology\n"
                "L003,Eng. Mollel,Civil Engineering\n"
            ).encode("utf-8")

            sessions_csv = (
                "module_code,module_name,session_type,hours_per_week,cohorts,lecturers,is_evening_stream,preferred_venue,split_override\n"
                "CSU 07311,Computer Networks,Lab,3,L7-2CS,Dr. Juma,false,Comp R21 Lab,\n"
                "ITU 07312,Web Systems,Lab,3,L7-2CS,Dr. Juma,false,,\n"
                "BIO 07101,Microbiology,Lab,1.5,L7-1BIO,Dr. Amina,false,,\n"
                "CEU 07201,Fluid Mechanics,Lab,1.5,L7-1CE,Eng. Mollel,false,,\n"
                "CSU 07311,Computer Networks,Theory,1.5,L7-2CS,Dr. Juma,false,Room A1,\n"
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
            self.assertEqual(
                client.post(
                    "/api/onboarding/upload/sessions",
                    headers=headers,
                    files={"file": ("sessions.csv", sessions_csv, "text/csv")},
                ).status_code,
                200,
            )

            # Raise prefer_exact_module_venue weight via schema_override
            schema = mgr.state["schema"]
            schema["soft_constraints"]["prefer_exact_module_venue"]["enabled"] = True
            schema["soft_constraints"]["prefer_exact_module_venue"]["weight"] = 150.0

            solve_res = client.post(
                "/api/solve",
                headers=headers,
                json={"schema_override": schema, "use_pins": False},
            )
            self.assertEqual(solve_res.status_code, 200, solve_res.text)
            body = solve_res.json()
            self.assertEqual(body["hard_violations"], 0)

            unrelated = {"Biology Lab", "Hydraulics Lab", "Soil and Bitumen Lab"}
            for s in body["timetable"]:
                if s["session_type"] == "Lab" and s["module_code"].startswith(("CSU", "ITU")):
                    self.assertIn(
                        s["venue_name"],
                        {"Comp R21 Lab", "Comp R42 Lab"},
                        f"CS/IT lab {s['module_code']} placed in unrelated room {s['venue_name']}",
                    )
                    self.assertNotIn(s["venue_name"], unrelated)
                if s["module_code"].startswith("BIO"):
                    self.assertEqual(s["venue_name"], "Biology Lab")
                if s["module_code"].startswith("CEU"):
                    self.assertIn(s["venue_name"], {"Hydraulics Lab", "Soil and Bitumen Lab"})


if __name__ == "__main__":
    unittest.main()

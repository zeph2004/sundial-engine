import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from src.api.auth import create_access_token, verify_access_token
from src.api.main import create_app
from src.api.state import DEFAULT_BRANDING, AppStateManager
from src.csp.domain import build_domains, load_json
from src.csp.optimizer import SimulatedAnnealingOptimizer
from src.csp.solver import TimetableCSPSolver, verify_solution


class TestSprint1PinningAndFastAPI(unittest.TestCase):
    root: Path
    schema: Dict[str, Any]
    dataset: Dict[str, Any]
    csp_raw: Dict[str, Any]
    affinity_cfg: Dict[str, Any]
    all_sessions: List[Dict[str, Any]]
    primary_sessions: List[Dict[str, Any]]
    venues: List[Dict[str, Any]]
    domains_a: Dict[str, List[Tuple[str, int, int | str]]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.schema = load_json(cls.root / "configs" / "institution_schema.json")
        cls.dataset = load_json(cls.root / "data" / "raw" / "atc" / "atc-timetable-dataset.json")
        cls.csp_raw = load_json(cls.root / "data" / "raw" / "atc" / "atc-csp-sessions.json")
        cls.affinity_cfg = load_json(cls.root / "configs" / "atc_venue_affinity.json")
        cls.all_sessions = cls.csp_raw["sessions"]
        cls.primary_sessions = [
            s for s in cls.all_sessions if int(s["sessionId"][1:]) <= 1233
        ]
        cls.venues = cls.dataset["venues"]
        cls.domains_a = build_domains(
            cls.primary_sessions,
            cls.venues,
            cls.schema,
            affinity_config=cls.affinity_cfg,
        )

    def test_pin_validation_errors(self) -> None:
        solver = TimetableCSPSolver(
            sessions=self.primary_sessions,
            venues=self.venues,
            schema=self.schema,
            affinity_config=self.affinity_cfg,
        )

        # 1. Non-existent session_id
        with self.assertRaises(ValueError) as ctx1:
            solver.solve(pinned_assignments={"S9999": (0, 1, 1)})
        self.assertIn("S9999", str(ctx1.exception))

        # 2. Invalid time slot for S0001 (e.g. evening period 15 for a Full-Time session)
        s1_compat_vid = solver.compatible_venues["S0001"][0]
        with self.assertRaises(ValueError) as ctx2:
            solver.solve(pinned_assignments={"S0001": (0, 15, s1_compat_vid)})
        self.assertIn("S0001", str(ctx2.exception))

        # 3. Incompatible venue_id for S0001
        with self.assertRaises(ValueError) as ctx3:
            solver.solve(pinned_assignments={"S0001": (0, 1, "INVALID_VENUE_999")})
        self.assertIn("S0001", str(ctx3.exception))

        # 4. Pairwise conflict between two pinned sessions sharing a cohort/lecturer or venue
        nb_sid = next(iter(solver.adj["S0001"]))
        nb_compat_vid = solver.compatible_venues[nb_sid][0]
        with self.assertRaises(ValueError) as ctx4:
            solver.solve(
                pinned_assignments={
                    "S0001": (0, 1, s1_compat_vid),
                    nb_sid: (0, 1, nb_compat_vid),
                }
            )
        self.assertIn("S0001", str(ctx4.exception))
        self.assertIn(nb_sid, str(ctx4.exception))

    def test_solver_and_sa_optimizer_honor_pinned_sessions(self) -> None:
        # Pick 3 non-conflicting sessions and pin them to specific valid (day_idx, start_period, venue_id) slots
        probe_solver = TimetableCSPSolver(
            sessions=self.primary_sessions,
            venues=self.venues,
            schema=self.schema,
            affinity_config=self.affinity_cfg,
        )
        # Pin S0001 to Wednesday (day_idx=2), start_period=7 (valid 4p block P7-P10), and its 2nd compatible venue
        vid_1 = probe_solver.compatible_venues["S0001"][min(1, len(probe_solver.compatible_venues["S0001"]) - 1)]
        # Find an independent session S0500 and pin to Thursday (day_idx=3), start_period=1
        vid_500 = probe_solver.compatible_venues["S0500"][0]

        pins: Dict[str, Tuple[int | str, int, int | str]] = {
            "S0001": (2, 7, vid_1),     # WEDNESDAY, P7
            "S0500": (3, 1, vid_500),   # THURSDAY, P1
        }

        solver = TimetableCSPSolver(
            sessions=self.primary_sessions,
            venues=self.venues,
            schema=self.schema,
            affinity_config=self.affinity_cfg,
        )
        csp_assignments, stats = solver.solve(pinned_assignments=pins)
        self.assertEqual(stats.status, "SOLVED")
        self.assertEqual(csp_assignments["S0001"], ("WEDNESDAY", 7, vid_1))
        self.assertEqual(csp_assignments["S0500"], ("THURSDAY", 1, vid_500))

        # Run Simulated Annealing with pinned_session_ids={"S0001", "S0500"}
        optimizer = SimulatedAnnealingOptimizer(
            sessions=self.primary_sessions,
            venues=self.venues,
            schema=self.schema,
            initial_assignments=csp_assignments,
            compatible_venues=solver.compatible_venues,
            venue_tier_label=solver.venue_tier_label,
            affinity_config=self.affinity_cfg,
            pinned_session_ids=set(pins.keys()),
        )
        opt_assignments, opt_stats = optimizer.optimize(max_iterations=5000)
        self.assertEqual(opt_assignments["S0001"], ("WEDNESDAY", 7, vid_1))
        self.assertEqual(opt_assignments["S0500"], ("THURSDAY", 1, vid_500))

        ver = verify_solution(
            self.primary_sessions,
            opt_assignments,
            self.domains_a,
            venue_tier_labels=solver.venue_tier_label,
        )
        self.assertTrue(ver["valid"])

    def test_auth_and_app_state_preload_and_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "app_state.json"
            self.assertFalse(state_file.exists())

            # First boot preloads ATC Clean Primary Dataset (Mode A) & default branding
            manager = AppStateManager(root=self.root, state_path=state_file)
            self.assertTrue(state_file.exists())
            self.assertEqual(manager.state["branding"], DEFAULT_BRANDING)
            self.assertEqual(len(manager.state["sessions"]), 1233)

            app = create_app(state_manager=manager)
            client = TestClient(app)

            # Protected endpoint without token -> 401
            resp_unauth = client.get("/api/auth/me")
            self.assertEqual(resp_unauth.status_code, 401)

            # Login with invalid password -> 401
            resp_bad = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong-password"},
            )
            self.assertEqual(resp_bad.status_code, 401)

            # Login with valid default admin credentials -> 200 + HMAC token
            resp_login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "sundial-admin"},
            )
            self.assertEqual(resp_login.status_code, 200)
            token = resp_login.json()["access_token"]
            claims = verify_access_token(token)
            self.assertEqual(claims["sub"], "admin")

            headers = {"Authorization": f"Bearer {token}"}
            resp_me = client.get("/api/auth/me", headers=headers)
            self.assertEqual(resp_me.status_code, 200)

            # Pin a session via API
            vid_s1 = manager.state["assignments"]["S0001"]["venue_id"]
            resp_pin = client.post(
                "/api/pins",
                headers=headers,
                json={
                    "session_id": "S0001",
                    "day": 1,  # TUESDAY
                    "start_period": 1,
                    "venue_id": vid_s1,
                },
            )
            self.assertEqual(resp_pin.status_code, 200)
            self.assertEqual(resp_pin.json()["pin"]["day"], "TUESDAY")

            # Expired token -> 401
            expired_token = create_access_token("admin", expires_in=-10)
            resp_exp = client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
            )
            self.assertEqual(resp_exp.status_code, 401)


if __name__ == "__main__":
    unittest.main()

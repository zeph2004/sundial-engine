from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.csp.domain import build_domains, load_json
from src.csp.optimizer import SimulatedAnnealingOptimizer
from src.csp.solver import TimetableCSPSolver, verify_solution


class TestSolverInvariants(unittest.TestCase):
    root: Path
    schema: Dict[str, Any]
    affinity_cfg: Dict[str, Any]
    venues: List[Dict[str, Any]]
    all_sessions: List[Dict[str, Any]]
    mode_a_sessions: List[Dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.schema = load_json(cls.root / "configs" / "institution_schema.json")
        cls.affinity_cfg = load_json(cls.root / "configs" / "atc_venue_affinity.json")
        dataset = load_json(cls.root / "data" / "raw" / "atc" / "atc-timetable-dataset.json")
        csp_raw = load_json(cls.root / "data" / "raw" / "atc" / "atc-csp-sessions.json")
        cls.venues = dataset["venues"]
        cls.all_sessions = csp_raw["sessions"]
        cls.mode_a_sessions = [
            s for s in cls.all_sessions if int(s["sessionId"][1:]) <= 1233
        ]

    def _hard_violation_count(self, ver: Dict[str, Any]) -> int:
        return (
            ver["unassigned_count"]
            + ver["unary_violations"]
            + ver["lecturer_overlaps"]
            + ver["cohort_overlaps"]
            + ver["venue_double_bookings"]
        )

    def test_mode_a_solves_zero_backtracks_zero_hard_violations(self) -> None:
        self.assertEqual(len(self.mode_a_sessions), 1233)
        domains = build_domains(
            self.mode_a_sessions,
            self.venues,
            self.schema,
            affinity_config=self.affinity_cfg,
        )
        solver = TimetableCSPSolver(
            sessions=self.mode_a_sessions,
            venues=self.venues,
            schema=self.schema,
            affinity_config=self.affinity_cfg,
        )
        assignments, stats = solver.solve()
        self.assertEqual(stats.status, "SOLVED")
        self.assertEqual(stats.backtracks, 0)
        self.assertEqual(len(assignments), 1233)

        ver = verify_solution(
            self.mode_a_sessions,
            assignments,
            domains,
            venue_tier_labels=solver.venue_tier_label,
        )
        self.assertTrue(ver["valid"])
        self.assertEqual(self._hard_violation_count(ver), 0)

    def test_mode_b_solves_zero_backtracks_zero_hard_violations(self) -> None:
        self.assertEqual(len(self.all_sessions), 1299)
        domains = build_domains(
            self.all_sessions,
            self.venues,
            self.schema,
            affinity_config=self.affinity_cfg,
        )
        solver = TimetableCSPSolver(
            sessions=self.all_sessions,
            venues=self.venues,
            schema=self.schema,
            affinity_config=self.affinity_cfg,
        )
        assignments, stats = solver.solve()
        self.assertEqual(stats.status, "SOLVED")
        self.assertEqual(stats.backtracks, 0)
        self.assertEqual(len(assignments), 1299)

        ver = verify_solution(
            self.all_sessions,
            assignments,
            domains,
            venue_tier_labels=solver.venue_tier_label,
        )
        self.assertTrue(ver["valid"])
        self.assertEqual(self._hard_violation_count(ver), 0)

    def test_phase4_sa_preserves_zero_violations_and_delta_parity(self) -> None:
        domains = build_domains(
            self.mode_a_sessions,
            self.venues,
            self.schema,
            affinity_config=self.affinity_cfg,
        )
        solver = TimetableCSPSolver(
            sessions=self.mode_a_sessions,
            venues=self.venues,
            schema=self.schema,
            affinity_config=self.affinity_cfg,
        )
        csp_assignments, csp_stats = solver.solve()
        self.assertEqual(csp_stats.status, "SOLVED")

        optimizer = SimulatedAnnealingOptimizer(
            sessions=self.mode_a_sessions,
            venues=self.venues,
            schema=self.schema,
            initial_assignments=csp_assignments,
            compatible_venues=solver.compatible_venues,
            venue_tier_label=solver.venue_tier_label,
            affinity_config=self.affinity_cfg,
        )
        opt_assignments, opt_stats = optimizer.optimize(max_iterations=10000)

        # 1. Zero hard-constraint violations preserved
        ver = verify_solution(
            self.mode_a_sessions,
            opt_assignments,
            domains,
            venue_tier_labels=solver.venue_tier_label,
        )
        self.assertTrue(ver["valid"])
        self.assertEqual(self._hard_violation_count(ver), 0)

        # 2. Exact parity between incremental delta scoring and full objective evaluation
        full_eval = optimizer.engine.evaluate_full_breakdown(opt_assignments)
        self.assertAlmostEqual(
            opt_stats.final_objective,
            full_eval.total_objective,
            places=2,
        )
        self.assertLessEqual(opt_stats.final_objective, opt_stats.initial_objective)

    def test_session_pinning_locked_through_phase3_and_phase4(self) -> None:
        probe = TimetableCSPSolver(
            sessions=self.mode_a_sessions,
            venues=self.venues,
            schema=self.schema,
            affinity_config=self.affinity_cfg,
        )
        vid_1 = probe.compatible_venues["S0001"][0]
        vid_500 = probe.compatible_venues["S0500"][0]
        pins = {
            "S0001": (2, 7, vid_1),   # WEDNESDAY, P7
            "S0500": (3, 1, vid_500), # THURSDAY, P1
        }

        solver = TimetableCSPSolver(
            sessions=self.mode_a_sessions,
            venues=self.venues,
            schema=self.schema,
            affinity_config=self.affinity_cfg,
        )
        csp_assignments, stats = solver.solve(pinned_assignments=pins)
        self.assertEqual(stats.status, "SOLVED")
        self.assertEqual(csp_assignments["S0001"], ("WEDNESDAY", 7, vid_1))
        self.assertEqual(csp_assignments["S0500"], ("THURSDAY", 1, vid_500))

        optimizer = SimulatedAnnealingOptimizer(
            sessions=self.mode_a_sessions,
            venues=self.venues,
            schema=self.schema,
            initial_assignments=csp_assignments,
            compatible_venues=solver.compatible_venues,
            venue_tier_label=solver.venue_tier_label,
            affinity_config=self.affinity_cfg,
            pinned_session_ids=set(pins.keys()),
        )
        opt_assignments, _ = optimizer.optimize(max_iterations=5000)
        self.assertEqual(opt_assignments["S0001"], ("WEDNESDAY", 7, vid_1))
        self.assertEqual(opt_assignments["S0500"], ("THURSDAY", 1, vid_500))

    def test_zero_back_to_back_venue_hopping_invariant(self) -> None:
        domains = build_domains(
            self.mode_a_sessions,
            self.venues,
            self.schema,
            affinity_config=self.affinity_cfg,
        )
        solver = TimetableCSPSolver(
            sessions=self.mode_a_sessions,
            venues=self.venues,
            schema=self.schema,
            affinity_config=self.affinity_cfg,
        )
        csp_assignments, stats = solver.solve()
        self.assertEqual(stats.status, "SOLVED")

        ver_p3 = verify_solution(
            self.mode_a_sessions,
            csp_assignments,
            domains,
            venue_tier_labels=solver.venue_tier_label,
        )
        self.assertEqual(ver_p3["venue_hopping_violations"], 0)

        optimizer = SimulatedAnnealingOptimizer(
            sessions=self.mode_a_sessions,
            venues=self.venues,
            schema=self.schema,
            initial_assignments=csp_assignments,
            compatible_venues=solver.compatible_venues,
            venue_tier_label=solver.venue_tier_label,
            affinity_config=self.affinity_cfg,
        )
        opt_assignments, _ = optimizer.optimize(max_iterations=8000)
        ver_p4 = verify_solution(
            self.mode_a_sessions,
            opt_assignments,
            domains,
            venue_tier_labels=solver.venue_tier_label,
        )
        self.assertTrue(ver_p4["valid"])
        self.assertEqual(ver_p4["venue_hopping_violations"], 0)


if __name__ == "__main__":
    unittest.main()

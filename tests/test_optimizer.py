import sys
import unittest
from copy import deepcopy
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.csp.domain import build_domains, load_json
from src.csp.optimizer import SimulatedAnnealingOptimizer, SoftConstraintEngine
from src.csp.solver import TimetableCSPSolver, verify_solution


class TestPhase4SoftConstraintOptimizer(unittest.TestCase):
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

        cls.solver_a = TimetableCSPSolver(
            sessions=cls.primary_sessions,
            venues=cls.venues,
            schema=cls.schema,
            affinity_config=cls.affinity_cfg,
        )
        cls.init_assignments_a, cls.solve_stats_a = cls.solver_a.solve()
        cls.domains_a = build_domains(
            cls.primary_sessions,
            cls.venues,
            cls.schema,
            affinity_config=cls.affinity_cfg,
        )

    def test_declarative_schema_sections_exist(self) -> None:
        self.assertIn("soft_constraints", self.schema)
        self.assertIn("optimizer", self.schema)
        sc = self.schema["soft_constraints"]
        for expected_rule in (
            "minimize_saturday_theory",
            "minimize_saturday_overflow",
            "minimize_evening_twilight",
            "minimize_cohort_idle_gaps",
            "balance_daily_workload",
            "prefer_exact_module_venue",
        ):
            self.assertIn(expected_rule, sc)
            self.assertTrue(sc[expected_rule]["enabled"])
            self.assertGreater(sc[expected_rule]["weight"], 0.0)

    def test_custom_pluggable_rule_registration_and_toggling(self) -> None:
        custom_schema = deepcopy(self.schema)
        custom_schema["soft_constraints"]["minimize_saturday_theory"]["enabled"] = False

        engine = SoftConstraintEngine(
            sessions=self.primary_sessions,
            venues=self.venues,
            schema=custom_schema,
            venue_tier_label=self.solver_a.venue_tier_label,
        )
        bd_without_sat_theory = engine.evaluate_full_breakdown(self.init_assignments_a)
        self.assertEqual(
            bd_without_sat_theory.weighted_by_rule["minimize_saturday_theory"], 0.0
        )

        # Register a custom session rule penalizing Friday P9-P12 sessions
        engine.register_custom_session_rule(
            name="penalize_friday_late_afternoon",
            weight=50.0,
            evaluator=lambda sid, day, sp, vid, s: 1.0 if (day == "FRIDAY" and sp >= 9) else 0.0,
            enabled=True,
        )
        bd_with_custom = engine.evaluate_full_breakdown(self.init_assignments_a)
        self.assertIn("penalize_friday_late_afternoon", bd_with_custom.weighted_by_rule)
        self.assertGreater(
            bd_with_custom.weighted_by_rule["penalize_friday_late_afternoon"], 0.0
        )
        self.assertAlmostEqual(
            bd_with_custom.total_objective,
            bd_without_sat_theory.total_objective
            + bd_with_custom.weighted_by_rule["penalize_friday_late_afternoon"],
            places=5,
        )

    def test_simulated_annealing_improves_objective_and_preserves_hard_constraints(self) -> None:
        optimizer = SimulatedAnnealingOptimizer(
            sessions=self.primary_sessions,
            venues=self.venues,
            schema=self.schema,
            initial_assignments=self.init_assignments_a,
            compatible_venues=self.solver_a.compatible_venues,
            venue_tier_label=self.solver_a.venue_tier_label,
            affinity_config=self.affinity_cfg,
        )
        opt_assignments, opt_stats = optimizer.optimize()

        # 1. Verify strictly reduced total soft-constraint objective
        self.assertLess(opt_stats.final_objective, opt_stats.initial_objective)
        self.assertGreater(opt_stats.improvement_pct, 15.0)

        # 2. Verify Saturday Theory count and Cohort Idle Gaps both improve
        init_counts = opt_stats.initial_breakdown.counts_by_rule
        final_counts = opt_stats.final_breakdown.counts_by_rule
        self.assertLess(
            final_counts["minimize_saturday_theory"],
            init_counts["minimize_saturday_theory"],
        )
        self.assertLess(
            final_counts["minimize_cohort_idle_gaps"],
            init_counts["minimize_cohort_idle_gaps"],
        )

        # 3. Verify 100% hard-constraint satisfaction after 40,000 SA moves
        verification = verify_solution(
            self.primary_sessions,
            opt_assignments,
            self.domains_a,
            venue_tier_labels=self.solver_a.venue_tier_label,
        )
        self.assertTrue(verification["valid"])
        self.assertEqual(verification["unary_violations"], 0)
        self.assertEqual(verification["lecturer_overlaps"], 0)
        self.assertEqual(verification["cohort_overlaps"], 0)
        self.assertEqual(verification["venue_double_bookings"], 0)
        self.assertEqual(
            verification["specialized_locked_ok"],
            verification["specialized_total"],
        )
        self.assertEqual(
            verification["saturday_report"]["csp_saturday_cond2_count"], 0
        )


if __name__ == "__main__":
    unittest.main()

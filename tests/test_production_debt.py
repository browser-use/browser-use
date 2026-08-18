import importlib.util
import os
import sys
import unittest

# Load module directly
file_path = os.path.join(
    os.path.dirname(__file__),
    "../browser_use/agent/production_debt.py",
)
spec = importlib.util.spec_from_file_location("browser_use_production_debt", file_path)
production_debt_mod = importlib.util.module_from_spec(spec)
sys.modules["browser_use_production_debt"] = production_debt_mod
spec.loader.exec_module(production_debt_mod)

ProductionDebtBrowserGate = production_debt_mod.ProductionDebtBrowserGate
TechnicalDueDiligenceLedger = production_debt_mod.TechnicalDueDiligenceLedger
GENESIS_HASH = production_debt_mod.GENESIS_HASH


class TestProductionDebtBrowserGate(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = ProductionDebtBrowserGate(
            never_equate_intent_to_approval=True,
            max_acceptable_bdi=12.0,
        )

    def test_clean_browser_action_passes_readiness(self) -> None:
        report = self.gate.evaluate_action(
            session_id="session_live_01",
            action_type="click_element",
            context_tokens=1000,
            vision_tokens=100,
            step_latency_seconds=1.1,
            dom_loop_count=0,
            un_gated_mutations=0,
        )
        self.assertTrue(report.is_production_ready)
        self.assertLessEqual(report.bdi_score, 12.0)
        self.assertEqual(len(report.critical_smells), 0)
        self.assertTrue(bool(report.receipt_hash))

    def test_degraded_browser_action_fails_debt(self) -> None:
        report = self.gate.evaluate_action(
            session_id="session_runaway_loop",
            action_type="delete_account",
            context_tokens=1000,
            vision_tokens=3000,  # High vision token inflation (4.0x)
            step_latency_seconds=8.5,  # High latency
            dom_loop_count=4,  # 4 DOM loops
            un_gated_mutations=2,  # 2 un-gated destructive mutations
        )
        self.assertFalse(report.is_production_ready)
        self.assertGreater(report.bdi_score, 50.0)
        self.assertIn("HIGH_VISION_TOKEN_INFLATION_4.00X", report.critical_smells)
        self.assertIn("HIGH_DOM_ACTION_LATENCY_8.50S", report.critical_smells)
        self.assertIn("DETECTED_4_DOM_NAVIGATION_LOOPS", report.critical_smells)
        self.assertIn("DETECTED_2_UNGATED_MUTATIONS", report.critical_smells)

    def test_cryptographic_ledger_integrity(self) -> None:
        self.gate.evaluate_action("sess-1")
        self.gate.evaluate_action("sess-2")
        self.gate.evaluate_action("sess-3")

        entries = self.gate.ledger.get_ledger_entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["prev_hash"], GENESIS_HASH)
        self.assertEqual(entries[1]["prev_hash"], entries[0]["curr_hash"])
        self.assertEqual(entries[2]["prev_hash"], entries[1]["curr_hash"])
        self.assertTrue(self.gate.ledger.verify_ledger_integrity())


if __name__ == "__main__":
    unittest.main()

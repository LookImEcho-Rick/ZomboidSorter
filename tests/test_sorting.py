from __future__ import annotations

import unittest
from pathlib import Path

from zomboid_mod_manager.discovery.scanner import scan_mods
from zomboid_mod_manager.sorting.dependency_order import propose_dependency_order
from zomboid_mod_manager.sorting.user_rules import UserOrderRule

FIXTURES = Path(__file__).parent / "fixtures" / "dependencies"


class DependencyOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entries = scan_mods(workshop_roots=[FIXTURES]).entries

    def test_requires_and_game_order_fields_become_before_after_edges(self) -> None:
        proposal = propose_dependency_order(
            self.entries,
            ("AfterCore", "Unsorted", "Core", "BeforeOther", "Other"),
        )
        self.assertEqual(
            proposal.suggested,
            ("Unsorted", "Core", "AfterCore", "BeforeOther", "Other"),
        )
        self.assertTrue(
            any(
                edge.reason == "AfterCore loadModAfter Core"
                for edge in proposal.constraints
            )
        )
        self.assertTrue(
            any(
                edge.reason == "BeforeOther declares loadModBefore Other"
                for edge in proposal.constraints
            )
        )

    def test_manual_order_is_retained_when_no_constraints_apply(self) -> None:
        original = ("Other", "Unsorted", "Core")
        proposal = propose_dependency_order(self.entries, original)
        self.assertEqual(proposal.suggested, original)
        self.assertFalse(proposal.changed)

    def test_candidate_specific_constraints_are_skipped(self) -> None:
        original = ("Variant", "Core")
        proposal = propose_dependency_order(self.entries, original)
        self.assertEqual(proposal.suggested, original)
        self.assertTrue(
            any(
                "differing dependency/order metadata" in item
                for item in proposal.unresolved
            )
        )

    def test_exact_game_build_orders_from_its_selected_candidate(self) -> None:
        before_version_update = propose_dependency_order(
            self.entries,
            ("Variant", "Core"),
            target_build="42.19.0",
        )
        self.assertEqual(
            before_version_update.suggested,
            ("Core", "Variant"),
        )
        self.assertTrue(
            any(
                edge.before == "Core"
                and edge.after == "Variant"
                and edge.source.name == "mod.info"
                and edge.source.parent.name == "common"
                for edge in before_version_update.constraints
            )
        )

        at_version_update = propose_dependency_order(
            self.entries,
            ("Variant", "Core"),
            target_build="42.20.0",
        )
        self.assertEqual(at_version_update.suggested, ("Variant", "Core"))
        self.assertFalse(at_version_update.constraints)
        self.assertTrue(
            any("NeverInstalled" in message for message in at_version_update.unresolved)
        )

    def test_order_cycle_does_not_change_the_original_list(self) -> None:
        original = ("OrderCycleA", "OrderCycleB")
        proposal = propose_dependency_order(self.entries, original)
        self.assertEqual(proposal.cycles, (("OrderCycleA", "OrderCycleB"),))
        self.assertEqual(proposal.suggested, original)

    def test_duplicate_active_ids_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            propose_dependency_order(self.entries, ("Core", "Core"))

    def test_user_rule_changes_order_without_metadata_constraints(self) -> None:
        proposal = propose_dependency_order(
            self.entries,
            ("Unsorted", "Other"),
            (UserOrderRule("Other", "Unsorted"),),
        )
        self.assertEqual(proposal.suggested, ("Other", "Unsorted"))
        self.assertTrue(
            any("User rule" in edge.reason for edge in proposal.constraints)
        )

    def test_user_rule_for_inactive_mod_is_reported_and_skipped(self) -> None:
        proposal = propose_dependency_order(
            self.entries,
            ("Unsorted", "Other"),
            (UserOrderRule("Uninstalled", "Other"),),
        )
        self.assertEqual(proposal.suggested, ("Unsorted", "Other"))
        self.assertTrue(
            any("not in the active list" in item for item in proposal.unresolved)
        )

    def test_conflicting_user_rule_stops_and_preserves_original_order(self) -> None:
        original = ("Core", "Consumer")
        proposal = propose_dependency_order(
            self.entries,
            original,
            (UserOrderRule("Consumer", "Core"),),
        )
        self.assertEqual(proposal.suggested, original)
        self.assertEqual(set(proposal.cycles[0]), {"Core", "Consumer"})


if __name__ == "__main__":
    unittest.main()

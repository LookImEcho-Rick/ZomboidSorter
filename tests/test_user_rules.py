from __future__ import annotations

import unittest

from zomboid_mod_manager.sorting.user_rules import (
    UserOrderRule,
    parse_user_order_rules,
    serialize_user_order_rules,
    validate_user_order_rules,
)


class UserOrderRuleTests(unittest.TestCase):
    def test_rules_round_trip_as_compact_json(self) -> None:
        rules = (UserOrderRule("Core", "Addon"), UserOrderRule("Base", "Patch"))
        serialized = serialize_user_order_rules(rules)
        self.assertEqual(serialized, '[["Core","Addon"],["Base","Patch"]]')
        self.assertEqual(parse_user_order_rules(serialized), rules)

    def test_malformed_or_unsafe_rules_are_rejected(self) -> None:
        for invalid in (
            "{",
            "{}",
            '[["Core"]]',
            '[["Core", "Core"]]',
            '[[" Core", "Addon"]]',
            '[["Core,Other", "Addon"]]',
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_user_order_rules(invalid)
        with self.assertRaises(TypeError):
            parse_user_order_rules(None)

    def test_duplicate_rules_are_rejected(self) -> None:
        duplicate = (
            UserOrderRule("Core", "Addon"),
            UserOrderRule("Core", "Addon"),
        )
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_user_order_rules(duplicate)


if __name__ == "__main__":
    unittest.main()

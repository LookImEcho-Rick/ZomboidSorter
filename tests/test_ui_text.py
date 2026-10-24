from __future__ import annotations

import unittest

from zomboid_mod_manager.ui.text import counted


class UiTextTests(unittest.TestCase):
    def test_counted_formats_singular_plural_and_explicit_irregular_plural(
        self,
    ) -> None:
        self.assertEqual(counted(0, "Mod ID"), "0 Mod IDs")
        self.assertEqual(counted(1, "mod entry", "mod entries"), "1 mod entry")
        self.assertEqual(counted(2, "mod entry", "mod entries"), "2 mod entries")


if __name__ == "__main__":
    unittest.main()

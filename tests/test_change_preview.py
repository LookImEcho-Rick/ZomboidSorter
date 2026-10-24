from __future__ import annotations

import unittest

from zomboid_mod_manager.ui.change_preview import format_ordered_list_change


class ChangePreviewTests(unittest.TestCase):
    def test_long_reorder_preview_shows_the_moved_id(self) -> None:
        before = tuple(f"Mod{index}" for index in range(24))
        after = (before[20], *before[:20], *before[21:])

        preview = format_ordered_list_change("Mod IDs", before, after)

        self.assertIn("  Order changes (− current, + result):", preview)
        self.assertIn("    + Mod20", preview)
        self.assertIn("    - Mod20", preview)
        self.assertNotIn(
            f"  Current order: {', '.join(before[:12])}, … and 12 more", preview
        )

    def test_large_reorder_diff_is_bounded(self) -> None:
        before = tuple(f"Mod{index}" for index in range(24))
        after = tuple(reversed(before))

        preview = format_ordered_list_change("Mod IDs", before, after)

        self.assertIn("    … and ", preview[-1])
        self.assertIn("more order-change lines", preview[-1])
        self.assertLessEqual(
            sum(line.startswith(("    + ", "    - ")) for line in preview), 12
        )


if __name__ == "__main__":
    unittest.main()

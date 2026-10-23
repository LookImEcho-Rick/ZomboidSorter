from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage

from zomboid_mod_manager.discovery.scanner import scan_mods
from zomboid_mod_manager.ui.mod_details import find_preview, format_entry_details


class ModDetailsTests(unittest.TestCase):
    def test_versioned_poster_in_common_and_candidate_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry_root = root / "Example"
            common = entry_root / "common"
            version = entry_root / "42.20"
            common.mkdir(parents=True)
            version.mkdir()
            (common / "mod.info").write_text(
                "name=Example Shared\nid=Example\nrequire=BaseLib\n"
                "description=Shared text\n",
                encoding="utf-8",
            )
            (version / "mod.info").write_text(
                "name=Example Versioned\nid=Example\n"
                "poster=../common/art.png\nversionMin=42.20\n"
                "description=Versioned text\n",
                encoding="utf-8",
            )
            image = QImage(32, 20, QImage.Format.Format_ARGB32)
            image.fill(QColor("#64a7dc"))
            self.assertTrue(image.save(str(common / "art.png")))
            entry = scan_mods(local_roots=[root]).entries[0]
            choice = find_preview(entry)
            self.assertIsNotNone(choice)
            self.assertEqual(choice.path, common / "art.png")
            self.assertEqual(choice.candidate.version_folder, "42.20")
            text = format_entry_details(entry, (entry,), ["Example"])
            self.assertIn("Author (first metadata candidate)", text)
            self.assertIn("BaseLib — not installed", text)
            self.assertIn("Declared game version minimum: 42.20", text)
            self.assertIn("Shared text", text)
            self.assertIn("Versioned text", text)
            self.assertIn("no active build candidate has been selected", text)

    def test_preview_rejects_path_outside_mod_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry_root = root / "Example"
            entry_root.mkdir()
            (entry_root / "mod.info").write_text(
                "name=Example\nid=Example\nposter=../outside.png\n",
                encoding="utf-8",
            )
            image = QImage(4, 4, QImage.Format.Format_ARGB32)
            image.fill(QColor("red"))
            self.assertTrue(image.save(str(root / "outside.png")))
            entry = scan_mods(local_roots=[root]).entries[0]
            self.assertIsNone(find_preview(entry))


if __name__ == "__main__":
    unittest.main()

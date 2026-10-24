from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage

from zomboid_mod_manager.discovery.scanner import scan_mods
from zomboid_mod_manager.ui.mod_details import (
    candidates_for_build,
    find_preview,
    find_preview_choices_for_candidates,
    format_entry_description,
    format_entry_details,
    format_workshop_description_html,
)
from zomboid_mod_manager.ui.window_workers import PreviewWorker


class ModDetailsTests(unittest.TestCase):
    def test_build_filter_uses_observed_metadata_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry_root = root / "Example"
            (entry_root / "common").mkdir(parents=True)
            (entry_root / "42.21").mkdir()
            (entry_root / "mod.info").write_text(
                "name=Example\nid=Example\ndescription=Build 41 description\n",
                encoding="utf-8",
            )
            (entry_root / "common" / "mod.info").write_text(
                "name=Example\nid=Example\ndescription=Shared description\n",
                encoding="utf-8",
            )
            (entry_root / "42.21" / "mod.info").write_text(
                "name=Example\nid=Example\ndescription=Build 42 description\n",
                encoding="utf-8",
            )

            entry = scan_mods(local_roots=[root]).entries[0]

        self.assertEqual(
            [candidate.layout for candidate in candidates_for_build(entry, "41")],
            ["root (Build 41 style)"],
        )
        self.assertEqual(
            [candidate.layout for candidate in candidates_for_build(entry, "42")],
            ["common (shared)", "versioned (42.21)"],
        )
        self.assertEqual(
            [
                candidate.version_folder
                for candidate in candidates_for_build(entry, "42.21.0")
            ],
            ["42.21"],
        )
        self.assertEqual(len(candidates_for_build(entry, "all")), 3)
        self.assertEqual(format_entry_description(entry, "41"), "Build 41 description")
        self.assertEqual(
            format_entry_description(entry, "42"),
            "common (shared)\n\nShared description\n\n"
            "versioned (42.21)\n\nBuild 42 description",
        )
        self.assertEqual(
            format_entry_description(entry, "42.21.0"), "Build 42 description"
        )
        self.assertIn(
            "Using version folder 42.21",
            format_entry_details(entry, (entry,), [], "42.21.0"),
        )

    def test_workshop_description_renders_allowed_tags_and_escapes_html(self) -> None:
        rendered = format_workshop_description_html(
            "[h1]News[/h1]\n[b]Bold[/b]\n"
            "<script>alert(1)</script>\n"
            "[url=javascript:alert(1)]click[/url]"
        )

        self.assertIn("<h2", rendered)
        self.assertIn("<strong>Bold</strong>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("javascript:", rendered)

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
            self.assertEqual(choice.path, (common / "art.png").resolve())
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

    def test_preview_skips_video_and_tries_next_decodable_gif_or_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry_root = root / "Example"
            entry_root.mkdir()
            (entry_root / "mod.info").write_text(
                "name=Example\nid=Example\n"
                "poster=trailer.mp4\n"
                "poster=broken.png\n"
                "poster=animated.gif\n"
                "poster=backup.png\n",
                encoding="utf-8",
            )
            (entry_root / "trailer.mp4").write_bytes(b"video fixture")
            (entry_root / "broken.png").write_bytes(b"not a png")
            (entry_root / "animated.gif").write_bytes(
                base64.b64decode(
                    "R0lGODlhCAAIAIEAAP8AAAAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQADAAAACwAAAAACAAIAAAIDwABCBxIsKDBgwgTKkwYEAAh+QQBDAABACwAAAAACAAIAIEAAP8AAAAAAAAAAAAIDwABCBxIsKDBgwgTKkwYEAA7"
                )
            )
            fallback = QImage(40, 30, QImage.Format.Format_ARGB32)
            fallback.fill(QColor("#64a7dc"))
            self.assertTrue(fallback.save(str(entry_root / "backup.png")))
            entry = scan_mods(local_roots=[root]).entries[0]
            choices = find_preview_choices_for_candidates(entry, entry.candidates)
            self.assertEqual(
                [choice.path.suffix for choice in choices], [".png", ".gif", ".png"]
            )

            loaded = []
            worker = PreviewWorker(choices, 1)
            worker.loaded.connect(lambda *result: loaded.append(result))
            worker.run()

            self.assertTrue(Path(loaded[0][0]).samefile(entry_root / "animated.gif"))
            self.assertFalse(loaded[0][2].isNull())

    def test_build_42_details_keep_the_discovered_name_for_root_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry_root = root / "Example"
            entry_root.mkdir()
            (entry_root / "mod.info").write_text(
                "name=Legacy Example\nid=Example\n", encoding="utf-8"
            )
            entry = scan_mods(local_roots=[root]).entries[0]

        details = format_entry_details(entry, (entry,), [], "42.21.0")
        self.assertTrue(details.startswith("Legacy Example\n"))
        self.assertIn("Build 42 ignores root-level mod files", details)


if __name__ == "__main__":
    unittest.main()

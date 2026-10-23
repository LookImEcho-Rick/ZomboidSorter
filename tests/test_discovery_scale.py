from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from zomboid_mod_manager.diagnostics.file_overlaps import analyze_file_overlaps
from zomboid_mod_manager.discovery.scanner import ScanCancelled, scan_mods


class DiscoveryScaleTests(unittest.TestCase):
    def test_large_library_scan_and_overlap_work_stay_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local_root = root / "local-mods"
            workshop_root = root / "workshop"
            local_count = 250
            workshop_count = 1_000

            for index in range(local_count):
                entry = local_root / f"Local-{index:04d}"
                scripts = entry / "media" / "scripts"
                scripts.mkdir(parents=True)
                (entry / "mod.info").write_text(
                    f"name=Local {index}\nid=LocalStress{index:04d}\n",
                    encoding="utf-8",
                )
                (scripts / "shared.lua").write_text(
                    "same shared content", encoding="utf-8"
                )

            for index in range(workshop_count):
                item = workshop_root / str(900_000_000 + index)
                scripts = item / "media" / "scripts"
                scripts.mkdir(parents=True)
                (item / "mod.info").write_text(
                    f"name=Workshop {index}\nid=WorkshopStress{index:04d}\n",
                    encoding="utf-8",
                )
                (scripts / "shared.lua").write_text(
                    "same shared content", encoding="utf-8"
                )

            started = time.monotonic()
            result = scan_mods(local_roots=[local_root], workshop_roots=[workshop_root])
            scan_seconds = time.monotonic() - started

            self.assertEqual(len(result.local_entries), local_count)
            self.assertEqual(len(result.workshop_items), workshop_count)
            self.assertEqual(len(result.entries), local_count + workshop_count)
            self.assertEqual(
                result.metadata_candidate_count, local_count + workshop_count
            )
            self.assertEqual(result.diagnostics, ())
            self.assertLess(scan_seconds, 30.0)

            diagnostic_started = time.monotonic()
            report = analyze_file_overlaps(result)
            diagnostic_seconds = time.monotonic() - diagnostic_started

            self.assertEqual(report.entry_count, local_count + workshop_count)
            self.assertEqual(report.files_scanned, local_count + workshop_count)
            self.assertTrue(report.truncated)
            self.assertEqual(report.overlap_count, 0)
            self.assertLess(diagnostic_seconds, 30.0)

            cancel_requested = False
            progress_messages: list[str] = []

            def progress(message: str) -> None:
                nonlocal cancel_requested
                progress_messages.append(message)
                if message == "Scanning Workshop items: 25 checked":
                    cancel_requested = True

            with self.assertRaises(ScanCancelled):
                scan_mods(
                    workshop_roots=[workshop_root],
                    cancelled=lambda: cancel_requested,
                    progress=progress,
                )
            self.assertIn("Scanning Workshop items: 25 checked", progress_messages)


if __name__ == "__main__":
    unittest.main()

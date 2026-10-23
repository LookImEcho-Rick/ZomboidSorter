from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.diagnostics.console_log import (
    ConsoleLogError,
    analyze_console_log,
    parse_console_log,
)


class ConsoleLogTests(unittest.TestCase):
    def test_recognizes_high_signal_signatures_and_mod_attribution(self) -> None:
        text = """ERROR: General f:0> ERROR: template "MissingTemplate" not found
ScriptManager.PostWorldDictionaryInit> Exception thrown: Fluid not found: Alcohol. line: fluid 0.1 [Alcohol]
ERROR: Lua((MOD:ExampleMod)).init> Exception thrown: sample exception
WorldDictionaryException: World loading could not proceed after script errors.
WARN : Lua f:0> require("Vanilla/Module") failed"""
        report = parse_console_log(text)
        self.assertEqual(
            [finding.category for finding in report.findings],
            [
                "missing-template",
                "missing-fluid",
                "mod-lua-exception",
                "world-load-failure",
            ],
        )
        self.assertEqual(report.findings[2].mod_name, "ExampleMod")
        self.assertIn("MissingTemplate", report.findings[0].summary)
        self.assertIn("Alcohol", report.findings[1].summary)

    def test_generic_engine_errors_and_require_warnings_are_not_attributed(
        self,
    ) -> None:
        report = parse_console_log(
            "ERROR: General texture missing\n"
            'WARN : Lua f:0> require("ISUI/SomeModule") failed\n'
            "LOG  : General f:0> operation completed without errors"
        )
        self.assertEqual(report.findings, ())

    def test_log_reader_rejects_symlinks_and_reads_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "console.txt"
            path.write_text(
                "WorldDictionaryException: World loading could not proceed",
                encoding="utf-8",
            )
            self.assertEqual(len(analyze_console_log(path).findings), 1)

            link = Path(temporary) / "linked-console.txt"
            try:
                link.symlink_to(path)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is not available in this environment.")
            with self.assertRaises(ConsoleLogError):
                analyze_console_log(link)


if __name__ == "__main__":
    unittest.main()

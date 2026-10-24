from __future__ import annotations

import unittest
from pathlib import Path

from zomboid_mod_manager.diagnostics.dependencies import (
    analyze_dependencies,
    format_dependency_finding,
    parse_mod_references,
)
from zomboid_mod_manager.discovery.scanner import scan_mods

FIXTURES = Path(__file__).parent / "fixtures" / "dependencies"


class DependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entries = scan_mods(workshop_roots=[FIXTURES]).entries

    def test_build_42_backslash_prefix_is_normalized_for_matching(self) -> None:
        parsed = parse_mod_references(r"\Core, Other", field_name="require")
        self.assertEqual(parsed.identifiers, ("Core", "Other"))
        self.assertEqual(parsed.stripped_b42_prefixes, 1)
        self.assertFalse(parsed.diagnostics)

    def test_missing_and_inactive_requirements_and_incompatibilities(self) -> None:
        report = analyze_dependencies(self.entries, ("Consumer", "Other"))
        self.assertTrue(
            any(
                f.kind == "inactive-dependency" and "Core" in f.message
                for f in report.findings
            )
        )
        self.assertTrue(
            any(
                f.kind == "missing-dependency" and "MissingMod" in f.message
                for f in report.findings
            )
        )
        self.assertTrue(
            any(
                f.kind == "incompatible" and f.mod_id in {"Consumer", "Other"}
                for f in report.findings
            )
        )

    def test_formatted_finding_names_source_mod_and_candidate_once(self) -> None:
        report = analyze_dependencies(self.entries, ("Consumer",))
        finding = next(
            finding
            for finding in report.findings
            if finding.kind == "missing-dependency"
        )

        self.assertEqual(finding.mod_id, "Consumer")
        self.assertNotIn("Candidate:", finding.message)
        formatted = format_dependency_finding(finding)
        self.assertIn("Mod 'Consumer':", formatted)
        self.assertEqual(formatted.count(str(finding.candidate_path)), 1)

    def test_dependency_cycles_are_reported_for_active_mods(self) -> None:
        report = analyze_dependencies(self.entries, ("CycleA", "CycleB"))
        self.assertEqual(report.cycles, (("CycleA", "CycleB"),))

    def test_candidate_specific_dependencies_are_not_collapsed(self) -> None:
        report = analyze_dependencies(self.entries, ("Variant", "Core"))
        self.assertTrue(
            any(
                f.kind == "candidate-variation" and f.mod_id == "Variant"
                for f in report.findings
            )
        )
        self.assertTrue(
            any(
                f.kind == "missing-dependency" and "NeverInstalled" in f.message
                for f in report.findings
            )
        )
        self.assertFalse(report.cycles)

    def test_exact_game_build_uses_only_the_selected_metadata_candidate(self) -> None:
        before_version_update = analyze_dependencies(
            self.entries, ("Variant",), target_build="42.19.0"
        )
        self.assertTrue(
            any(
                finding.kind == "inactive-dependency" and "Core" in finding.message
                for finding in before_version_update.findings
            )
        )
        self.assertFalse(
            any(
                finding.kind == "missing-dependency"
                and "NeverInstalled" in finding.message
                for finding in before_version_update.findings
            )
        )

        at_version_update = analyze_dependencies(
            self.entries, ("Variant",), target_build="42.20.0"
        )
        self.assertTrue(
            any(
                finding.kind == "missing-dependency"
                and "NeverInstalled" in finding.message
                for finding in at_version_update.findings
            )
        )
        self.assertFalse(
            any(
                finding.kind == "inactive-dependency" and "Core" in finding.message
                for finding in at_version_update.findings
            )
        )

    def test_unsupported_separator_is_reported_without_guessing(self) -> None:
        parsed = parse_mod_references("One;Two", field_name="require")
        self.assertFalse(parsed.identifiers)
        self.assertTrue(parsed.diagnostics)


if __name__ == "__main__":
    unittest.main()

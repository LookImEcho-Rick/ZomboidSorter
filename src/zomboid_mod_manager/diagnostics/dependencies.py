"""Dependency checks using declarations from discovered ``mod.info`` files."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from zomboid_mod_manager.discovery.version_selection import (
    resolve_entry_metadata,
)
from zomboid_mod_manager.domain import MetadataCandidate, ModEntry


@dataclass(frozen=True)
class ParsedIdentifiers:
    identifiers: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()
    stripped_b42_prefixes: int = 0


@dataclass(frozen=True)
class DependencyFinding:
    kind: str
    message: str
    mod_id: str | None = None
    candidate_path: Path | None = None


@dataclass(frozen=True)
class DependencyReport:
    findings: tuple[DependencyFinding, ...]
    cycles: tuple[tuple[str, ...], ...]


def format_dependency_finding(finding: DependencyFinding) -> str:
    """Format a finding with its source Mod ID and candidate evidence once."""
    source = f"Mod '{finding.mod_id}': " if finding.mod_id else ""
    message = f"{source}{finding.message}"
    if finding.candidate_path is not None:
        message += f"\n  Metadata file: {finding.candidate_path}"
    return message


def parse_mod_references(raw: str, *, field_name: str) -> ParsedIdentifiers:
    """Parse comma-separated mod references; keep unsupported syntax explicit.

    Real Build 42 metadata in the installed library uses an optional leading
    backslash on references. One such prefix is removed for Mod ID matching;
    the original field remains available on the metadata candidate.
    """
    value = raw.strip()
    if not value:
        return ParsedIdentifiers(())
    if ";" in value:
        return ParsedIdentifiers(
            (), (f"'{field_name}' uses an unsupported semicolon separator; kept raw.",)
        )

    parts = value.split(",")
    identifiers: list[str] = []
    diagnostics: list[str] = []
    stripped_prefixes = 0
    for part in parts:
        reference = part.strip()
        if not reference:
            diagnostics.append(f"'{field_name}' contains an empty reference; kept raw.")
            continue
        if reference.startswith("\\"):
            reference = reference[1:]
            stripped_prefixes += 1
            if not reference or reference.startswith("\\"):
                diagnostics.append(
                    f"'{field_name}' has an ambiguous backslash prefix; kept raw."
                )
                continue
        if reference != reference.strip() or "\n" in reference or "\r" in reference:
            diagnostics.append(
                f"'{field_name}' contains an invalid reference; kept raw."
            )
            continue
        identifiers.append(reference)

    if len(identifiers) != len(set(identifiers)):
        diagnostics.append(f"'{field_name}' repeats a reference.")
    return ParsedIdentifiers(
        tuple(dict.fromkeys(identifiers)), tuple(diagnostics), stripped_prefixes
    )


def _candidate_field(candidate: MetadataCandidate, key: str) -> ParsedIdentifiers:
    return parse_mod_references(candidate.fields.get(key, ""), field_name=key)


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> tuple[tuple[str, ...], ...]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for adjacent in sorted(graph.get(node, set())):
            if adjacent not in indices:
                visit(adjacent)
                lowlinks[node] = min(lowlinks[node], lowlinks[adjacent])
            elif adjacent in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[adjacent])

        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                adjacent = stack.pop()
                on_stack.remove(adjacent)
                component.append(adjacent)
                if adjacent == node:
                    break
            if len(component) > 1 or node in graph.get(node, set()):
                components.append(tuple(sorted(component, key=str.casefold)))

    for node in sorted(graph, key=str.casefold):
        if node not in indices:
            visit(node)
    return tuple(
        sorted(
            components,
            key=lambda component: tuple(part.casefold() for part in component),
        )
    )


def analyze_dependencies(
    entries: Iterable[ModEntry],
    active_mod_ids: Iterable[str],
    *,
    target_build: str = "all",
) -> DependencyReport:
    """Report dependency issues for all candidates or the selected game build."""
    all_entries = tuple(entries)
    active_ids = tuple(dict.fromkeys(active_mod_ids))
    active = set(active_ids)
    by_id: dict[str, list[ModEntry]] = {}
    for entry in all_entries:
        if entry.mod_id:
            by_id.setdefault(entry.mod_id, []).append(entry)

    findings: list[DependencyFinding] = []
    graph: dict[str, set[str]] = {mod_id: set() for mod_id in active_ids}
    cycle_eligible: set[str] = set()
    incompatibility_pairs: set[tuple[str, str]] = set()

    for mod_id in active_ids:
        matches = by_id.get(mod_id, [])
        if len(matches) != 1:
            continue
        entry = matches[0]
        if not entry.candidates:
            continue

        selection = resolve_entry_metadata(entry, target_build)
        if not selection.candidates:
            if target_build != "all":
                findings.append(
                    DependencyFinding(
                        "candidate-selection",
                        selection.message,
                        mod_id,
                    )
                )
            continue

        requirement_sets: list[tuple[str, ...]] = []
        incompatible_sets: list[tuple[str, ...]] = []
        for candidate in selection.candidates:
            location = candidate.path
            requirements = _candidate_field(candidate, "require")
            incompatible = _candidate_field(candidate, "incompatible")
            requirement_sets.append(requirements.identifiers)
            incompatible_sets.append(incompatible.identifiers)
            for diagnostic in requirements.diagnostics:
                findings.append(
                    DependencyFinding(
                        "metadata",
                        diagnostic,
                        mod_id,
                        location,
                    )
                )
            for diagnostic in incompatible.diagnostics:
                findings.append(
                    DependencyFinding(
                        "metadata",
                        diagnostic,
                        mod_id,
                        location,
                    )
                )
            if requirements.stripped_b42_prefixes:
                findings.append(
                    DependencyFinding(
                        "normalization",
                        f"Normalized {requirements.stripped_b42_prefixes} leading Build 42 backslash prefix(es) for dependency matching.",
                        mod_id,
                        location,
                    )
                )

            for required_id in requirements.identifiers:
                providers = by_id.get(required_id, [])
                if not providers:
                    findings.append(
                        DependencyFinding(
                            "missing-dependency",
                            f"Requires '{required_id}', which was not found in the scanned folders.",
                            mod_id,
                            location,
                        )
                    )
                elif len(providers) > 1:
                    findings.append(
                        DependencyFinding(
                            "ambiguous-dependency",
                            f"Requires '{required_id}', but {len(providers)} installed entries share that Mod ID.",
                            mod_id,
                            location,
                        )
                    )
                elif required_id not in active:
                    findings.append(
                        DependencyFinding(
                            "inactive-dependency",
                            f"Requires '{required_id}', which is installed but not active.",
                            mod_id,
                            location,
                        )
                    )

            for incompatible_id in incompatible.identifiers:
                if incompatible_id not in active:
                    continue
                pair = tuple(sorted((mod_id, incompatible_id), key=str.casefold))
                if pair not in incompatibility_pairs:
                    incompatibility_pairs.add(pair)
                    findings.append(
                        DependencyFinding(
                            "incompatible",
                            f"'{incompatible_id}' is declared incompatible with this active mod.",
                            mod_id,
                            location,
                        )
                    )

        if requirement_sets and all(
            values == requirement_sets[0] for values in requirement_sets
        ):
            cycle_eligible.add(mod_id)
            graph[mod_id].update(
                required_id
                for required_id in requirement_sets[0]
                if required_id in active and len(by_id.get(required_id, [])) == 1
            )
        elif len(set(requirement_sets)) > 1:
            findings.append(
                DependencyFinding(
                    "candidate-variation",
                    "Required Mod IDs differ across metadata candidates; cycle analysis is skipped for this entry.",
                    mod_id,
                )
            )

        if len(set(incompatible_sets)) > 1:
            findings.append(
                DependencyFinding(
                    "candidate-variation",
                    "Incompatibility declarations differ across metadata candidates; findings above are candidate-specific.",
                    mod_id,
                )
            )

    for related_ids in graph.values():
        related_ids.intersection_update(cycle_eligible)
    cycles = _strongly_connected_components(graph)
    for component in cycles:
        findings.append(
            DependencyFinding(
                "dependency-cycle",
                "Active dependency cycle: " + " → ".join(component + (component[0],)),
            )
        )

    return DependencyReport(tuple(findings), cycles)

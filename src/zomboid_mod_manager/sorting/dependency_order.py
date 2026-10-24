"""Stable ordering proposals from verified Build 42 mod constraints."""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from zomboid_mod_manager.diagnostics.dependencies import (
    _strongly_connected_components,
    parse_mod_references,
)
from zomboid_mod_manager.discovery.version_selection import (
    resolve_entry_metadata,
)
from zomboid_mod_manager.domain import ModEntry
from zomboid_mod_manager.sorting.user_rules import (
    UserOrderRule,
    validate_user_order_rules,
)


@dataclass(frozen=True)
class OrderConstraint:
    before: str
    after: str
    reason: str
    source: Path


@dataclass(frozen=True)
class SortProposal:
    original: tuple[str, ...]
    suggested: tuple[str, ...]
    constraints: tuple[OrderConstraint, ...]
    unresolved: tuple[str, ...]
    cycles: tuple[tuple[str, ...], ...]

    @property
    def changed(self) -> bool:
        return self.original != self.suggested


def propose_dependency_order(
    entries: Iterable[ModEntry],
    active_mod_ids: Iterable[str],
    user_rules: Iterable[UserOrderRule] = (),
    *,
    target_build: str = "all",
) -> SortProposal:
    """Topologically order active IDs, retaining current order for ready ties.

    With no target build, only declarations identical across all metadata
    candidates are used. When a build is selected, only its resolved candidate
    contributes metadata constraints.
    """
    original = tuple(active_mod_ids)
    if len(original) != len(set(original)):
        raise ValueError("Active Mod IDs must be unique before sorting.")
    active = set(original)
    positions = {mod_id: index for index, mod_id in enumerate(original)}
    by_id: dict[str, list[ModEntry]] = {}
    for entry in entries:
        if entry.mod_id:
            by_id.setdefault(entry.mod_id, []).append(entry)

    constraints: list[OrderConstraint] = []
    unresolved: list[str] = []
    for mod_id in original:
        matches = by_id.get(mod_id, [])
        if len(matches) != 1:
            if len(matches) > 1:
                unresolved.append(
                    f"'{mod_id}' has duplicate installations; its constraints were skipped."
                )
            continue
        entry = matches[0]
        if not entry.candidates:
            continue

        selection = resolve_entry_metadata(entry, target_build)
        if not selection.candidates:
            if target_build != "all":
                unresolved.append(f"'{mod_id}': {selection.message}")
            continue

        parsed_by_candidate: list[
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]
        ] = []
        for candidate in selection.candidates:
            parsed_fields = tuple(
                parse_mod_references(candidate.fields.get(key, ""), field_name=key)
                for key in ("require", "loadmodafter", "loadmodbefore")
            )
            for result in parsed_fields:
                if result.diagnostics:
                    unresolved.extend(
                        f"{message} Candidate: {candidate.path}"
                        for message in result.diagnostics
                    )
            parsed_by_candidate.append(
                tuple(result.identifiers for result in parsed_fields)
            )

        if len(set(parsed_by_candidate)) > 1:
            unresolved.append(
                f"'{mod_id}' has differing dependency/order metadata across candidates; constraints were skipped."
            )
            continue
        requires, after, before = parsed_by_candidate[0]
        for related_id, reason in (
            *((related_id, "requires") for related_id in requires),
            *((related_id, "loadModAfter") for related_id in after),
        ):
            if related_id not in active:
                if related_id not in by_id:
                    unresolved.append(
                        f"'{mod_id}' {reason} '{related_id}', which was not found in the scanned folders."
                    )
                elif len(by_id[related_id]) > 1:
                    unresolved.append(
                        f"'{mod_id}' {reason} ambiguous Mod ID '{related_id}'."
                    )
                # An installed but inactive target is a validation warning; no active-order edge applies.
                continue
            constraints.append(
                OrderConstraint(
                    related_id,
                    mod_id,
                    f"{mod_id} {reason} {related_id}",
                    selection.candidates[0].path,
                )
            )
        for related_id in before:
            if related_id not in active:
                if related_id not in by_id:
                    unresolved.append(
                        f"'{mod_id}' declares loadModBefore '{related_id}', which was not found in the scanned folders."
                    )
                elif len(by_id[related_id]) > 1:
                    unresolved.append(
                        f"'{mod_id}' declares loadModBefore ambiguous Mod ID '{related_id}'."
                    )
                continue
            constraints.append(
                OrderConstraint(
                    mod_id,
                    related_id,
                    f"{mod_id} declares loadModBefore {related_id}",
                    selection.candidates[0].path,
                )
            )

    normalized_user_rules = tuple(user_rules)
    validate_user_order_rules(normalized_user_rules)
    for rule in normalized_user_rules:
        if rule.before_id not in active or rule.after_id not in active:
            unresolved.append(
                f"User ordering rule '{rule.label}' references a Mod ID not in the active list; it was skipped."
            )
            continue
        constraints.append(
            OrderConstraint(
                rule.before_id,
                rule.after_id,
                f"User rule: {rule.label}",
                Path("<user rule>"),
            )
        )

    unique_constraints: dict[tuple[str, str], OrderConstraint] = {}
    for constraint in constraints:
        unique_constraints.setdefault((constraint.before, constraint.after), constraint)
    constraints = list(unique_constraints.values())
    graph: dict[str, set[str]] = {mod_id: set() for mod_id in original}
    indegree = {mod_id: 0 for mod_id in original}
    for constraint in constraints:
        if constraint.after not in graph[constraint.before]:
            graph[constraint.before].add(constraint.after)
            indegree[constraint.after] += 1

    ready = [
        (positions[mod_id], mod_id)
        for mod_id, degree in indegree.items()
        if degree == 0
    ]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        _position, mod_id = heapq.heappop(ready)
        ordered.append(mod_id)
        for adjacent in sorted(graph[mod_id], key=lambda item: positions[item]):
            indegree[adjacent] -= 1
            if indegree[adjacent] == 0:
                heapq.heappush(ready, (positions[adjacent], adjacent))

    cycles: tuple[tuple[str, ...], ...] = ()
    if len(ordered) != len(original):
        cycles = _strongly_connected_components(graph)
        unresolved.extend(
            "Ordering cycle: " + " → ".join(component + (component[0],))
            for component in cycles
        )
        suggested = original
    else:
        suggested = tuple(ordered)

    return SortProposal(
        original=original,
        suggested=suggested,
        constraints=tuple(constraints),
        unresolved=tuple(dict.fromkeys(unresolved)),
        cycles=cycles,
    )

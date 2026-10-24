"""Compact ordered-list previews for guarded game-file writes."""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import unified_diff

_PREVIEW_LIMIT = 12
_FILE_DIFF_LIMIT = 24
_INI_ASSIGNMENT = re.compile(r"^(\s*[^#;][^=]*?)(\s*=\s*)(.*)$")
_SENSITIVE_SETTING_PARTS = (
    "password",
    "passphrase",
    "secret",
    "token",
    "apikey",
    "credential",
    "webhook",
)


def _format_values(values: Sequence[str]) -> str:
    shown = ", ".join(values[:_PREVIEW_LIMIT])
    if len(values) > _PREVIEW_LIMIT:
        shown += f", … and {len(values) - _PREVIEW_LIMIT} more"
    return shown or "none"


def format_ordered_list_change(
    label: str, before: Sequence[str], after: Sequence[str]
) -> list[str]:
    """Describe additions, removals, and order changes with bounded detail."""
    if tuple(before) == tuple(after):
        return [f"{label}: unchanged ({len(before)})"]

    before_set = set(before)
    after_set = set(after)
    added = tuple(value for value in after if value not in before_set)
    removed = tuple(value for value in before if value not in after_set)
    shared_before = tuple(value for value in before if value in after_set)
    shared_after = tuple(value for value in after if value in before_set)

    lines = [f"{label}: {len(before)} → {len(after)}"]
    if added:
        lines.append(f"  Added: {_format_values(added)}")
    if removed:
        lines.append(f"  Removed: {_format_values(removed)}")
    if shared_before != shared_after:
        order_diff = [
            line
            for line in unified_diff(shared_before, shared_after, n=0, lineterm="")
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        lines.append("  Order changes (− current, + result):")
        lines.extend(
            f"    {line[0]} {line[1:]}" for line in order_diff[:_PREVIEW_LIMIT]
        )
        if len(order_diff) > _PREVIEW_LIMIT:
            lines.append(
                f"    … and {len(order_diff) - _PREVIEW_LIMIT} more order-change lines"
            )
    elif tuple(before) != tuple(after):
        lines.append(f"  Result order: {_format_values(after)}")
    return lines


def _format_ini_diff_line(line: str) -> str:
    sign, body = line[0], line[1:]
    match = _INI_ASSIGNMENT.fullmatch(body)
    if match is not None:
        setting = re.sub(r"[^a-z0-9]", "", match.group(1).casefold())
        if any(part in setting for part in _SENSITIVE_SETTING_PARTS):
            body = f"{match.group(1)}{match.group(2)}<redacted>"
    return f"{sign} {body}"


def format_ini_file_diff(before: bytes, after: bytes) -> list[str]:
    """Show bounded changed INI lines while masking secret-like values."""
    old_lines = before.decode("utf-8-sig").splitlines()
    new_lines = after.decode("utf-8-sig").splitlines()
    changed = [
        line
        for line in unified_diff(old_lines, new_lines, n=0)
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    if not changed:
        return ["No setting-line differences."]
    lines = [_format_ini_diff_line(line) for line in changed[:_FILE_DIFF_LIMIT]]
    if len(changed) > _FILE_DIFF_LIMIT:
        lines.append(f"… and {len(changed) - _FILE_DIFF_LIMIT} more changed lines")
    return lines

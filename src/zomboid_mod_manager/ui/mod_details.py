"""Read-only presentation of discovered mod metadata and local preview paths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path

from zomboid_mod_manager.diagnostics.dependencies import parse_mod_references
from zomboid_mod_manager.discovery.version_selection import (
    resolve_entry_metadata,
)
from zomboid_mod_manager.domain import MetadataCandidate, ModEntry

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
_KNOWN_FIELDS = {
    "id",
    "name",
    "author",
    "authors",
    "description",
    "modversion",
    "version",
    "poster",
    "icon",
    "require",
    "incompatible",
    "loadmodafter",
    "loadmodbefore",
    "versionmin",
    "versionmax",
    "url",
}


@dataclass(frozen=True)
class PreviewChoice:
    path: Path
    candidate: MetadataCandidate


def find_preview(entry: ModEntry) -> PreviewChoice | None:
    """Find the first declared local poster, without selecting a runtime candidate."""
    return find_preview_for_candidates(entry, entry.candidates)


def candidates_for_build(
    entry: ModEntry, target_build: str
) -> tuple[MetadataCandidate, ...]:
    """Return candidates selected for a target build or preview mode."""
    return resolve_entry_metadata(entry, target_build).candidates


def find_preview_for_candidates(
    entry: ModEntry, candidates: tuple[MetadataCandidate, ...]
) -> PreviewChoice | None:
    """Find the first declared, supported local image among these candidates."""
    choices = find_preview_choices_for_candidates(entry, candidates)
    return choices[0] if choices else None


def find_preview_choices_for_candidates(
    entry: ModEntry, candidates: tuple[MetadataCandidate, ...]
) -> tuple[PreviewChoice, ...]:
    """Return supported local images in metadata order, skipping video media."""
    try:
        entry_root = entry.entry_path.resolve()
    except OSError:
        return ()
    choices: list[PreviewChoice] = []
    seen: set[Path] = set()
    for candidate in candidates:
        references = candidate.fields.get("poster", "").splitlines()
        references += candidate.fields.get("icon", "").splitlines()
        for reference in references:
            reference = reference.strip()
            if not reference or ":" in reference or reference.startswith(("/", "\\")):
                continue
            try:
                path = (candidate.path.parent / reference).resolve()
                if (
                    path.is_relative_to(entry_root)
                    and path.suffix.casefold() in _IMAGE_EXTENSIONS
                    and path.is_file()
                    and path not in seen
                ):
                    choices.append(PreviewChoice(path, candidate))
                    seen.add(path)
            except OSError:
                continue
    return tuple(choices)


def format_entry_description(entry: ModEntry, target_build: str = "all") -> str:
    """Return candidate descriptions as readable plain text, preserving paragraphs."""
    candidates = candidates_for_build(entry, target_build)
    if target_build != "all" and not candidates:
        return resolve_entry_metadata(entry, target_build).message
    sections = []
    for candidate in candidates:
        description = _clean_description(candidate.fields.get("description", ""))
        if description:
            if len(candidates) > 1:
                sections.append(f"{candidate.layout}\n\n{description}")
            else:
                sections.append(description)
    if sections:
        return "\n\n".join(sections)
    return "No description is provided by the selected metadata candidate."


def format_entry_description_html(entry: ModEntry, target_build: str = "all") -> str:
    """Render descriptions as escaped, readable HTML for a rich-text view."""
    candidates = candidates_for_build(entry, target_build)
    if target_build != "all" and not candidates:
        message = resolve_entry_metadata(entry, target_build).message
        return (
            '<p style="margin:4px 0; color:#9cadbd; font-style:italic;">'
            f"{escape(message)}</p>"
        )
    descriptions: dict[str, list[str]] = {}
    for candidate in candidates:
        cleaned = _clean_description(candidate.fields.get("description", ""))
        if cleaned:
            descriptions.setdefault(cleaned, []).append(candidate.layout)
    if not descriptions:
        return (
            '<p style="margin:4px 0; color:#9cadbd; font-style:italic;">'
            "No description is provided by the selected metadata candidate."
            "</p>"
        )

    sections = []
    for description, layouts in descriptions.items():
        body = _description_body_html(description)
        if len(descriptions) > 1:
            layout_label = ", ".join(dict.fromkeys(layouts))
            sections.append(
                '<div style="margin:0 0 12px 0;">'
                f'<p style="margin:0 0 7px 0; color:#8fbbe0; font-size:9pt; '
                f'font-weight:600;">{escape(layout_label)}</p>'
                f"{body}</div>"
            )
        else:
            sections.append(body)
    return "".join(sections)


def format_workshop_description_html(raw: str) -> str:
    """Render Steam's common Workshop heading, emphasis, and list tags safely."""
    if not raw.strip():
        return (
            '<p style="margin:4px 0; color:#9cadbd; font-style:italic;">'
            "No Workshop description is available.</p>"
        )
    description = raw.replace("\r\n", "\n").replace("\r", "\n")
    list_blocks: list[tuple[str, str]] = []

    def replace_list(match: re.Match[str]) -> str:
        kind = "ol" if match.group("kind").casefold() == "olist" else "ul"
        items = re.split(r"\[\*\]", match.group("body"), flags=re.IGNORECASE)
        rendered_items = "".join(
            f"<li>{_render_workshop_inline(item.strip())}</li>"
            for item in items
            if item.strip()
        )
        token = f"\ue000WORKSHOP_LIST_{len(list_blocks)}\ue001"
        list_blocks.append((token, f"<{kind}>{rendered_items}</{kind}>"))
        return token

    description = re.sub(
        r"\[(?P<kind>list|olist)\](?P<body>.*?)\[/\1\]",
        replace_list,
        description,
        flags=re.IGNORECASE | re.DOTALL,
    )
    rendered = _render_workshop_inline(description)
    for token, list_html in list_blocks:
        rendered = rendered.replace(token, list_html)
    return rendered


def _render_workshop_inline(text: str) -> str:
    tag_pattern = re.compile(
        r"\[(?P<close>/)?(?P<name>h[1-6]|b|i|u|s|strike|spoiler|quote|code|url|br|hr|\*)"
        r"(?:=[^\]]*)?\]",
        re.IGNORECASE,
    )
    tags = {
        "h1": (
            '<h2 style="color:#58b6ff; font-size:16pt; margin:8px 0 12px 0;">',
            "</h2>",
        ),
        "h2": (
            '<h3 style="color:#58b6ff; font-size:13pt; margin:14px 0 8px 0;">',
            "</h3>",
        ),
        "h3": (
            '<h4 style="color:#8bc8f2; font-size:11pt; margin:12px 0 6px 0;">',
            "</h4>",
        ),
        "h4": ("<h4>", "</h4>"),
        "h5": ("<h5>", "</h5>"),
        "h6": ("<h6>", "</h6>"),
        "b": ("<strong>", "</strong>"),
        "i": ("<em>", "</em>"),
        "u": ("<u>", "</u>"),
        "s": ("<s>", "</s>"),
        "strike": ("<s>", "</s>"),
        "spoiler": (
            '<span style="background:#344453; color:#344453;">',
            "</span>",
        ),
        "quote": (
            (
                '<blockquote style="border-left:3px solid #58b6ff; margin:8px 0; '
                'padding-left:10px; color:#bdcbd8;">'
            ),
            "</blockquote>",
        ),
        "code": (
            '<code style="background:#233241; color:#dce8f2;">',
            "</code>",
        ),
        "url": (
            '<span style="color:#58b6ff; text-decoration:underline;">',
            "</span>",
        ),
        "br": ("<br>", ""),
        "hr": (
            '<hr style="border:0; border-top:1px solid #40576a; margin:12px 0;">',
            "",
        ),
        "*": ("<br>• ", ""),
    }
    output = []
    cursor = 0
    for match in tag_pattern.finditer(text):
        output.append(escape(text[cursor : match.start()]).replace("\n", "<br>"))
        name = match.group("name").casefold()
        opening, closing = tags[name]
        output.append(closing if match.group("close") else opening)
        cursor = match.end()
    output.append(escape(text[cursor:]).replace("\n", "<br>"))
    return "".join(output)


def _clean_description(raw: str) -> str:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines = []
    last_was_blank = False
    for line in normalized.split("\n"):
        line = line.rstrip()
        is_blank = not line.strip()
        if is_blank:
            if not last_was_blank:
                cleaned_lines.append("")
        else:
            cleaned_lines.append(line)
        last_was_blank = is_blank
    return "\n".join(cleaned_lines).strip()


def _description_body_html(description: str) -> str:
    paragraphs = re.split(r"\n\s*\n", description)
    rendered = []
    for paragraph in paragraphs:
        lines = paragraph.splitlines()
        if not lines:
            continue
        if all(re.match(r"^\s*[-*•–]\s+", line) for line in lines):
            items = "".join(
                "<li>" + escape(re.sub(r"^\s*[-*•–]\s+", "", line)) + "</li>"
                for line in lines
            )
            rendered.append(
                f'<ul style="margin:2px 0 10px 0; padding-left:22px;">{items}</ul>'
            )
        elif all(re.match(r"^\s*\d+[.)]\s+", line) for line in lines):
            items = "".join(
                "<li>" + escape(re.sub(r"^\s*\d+[.)]\s+", "", line)) + "</li>"
                for line in lines
            )
            rendered.append(
                f'<ol style="margin:2px 0 10px 0; padding-left:22px;">{items}</ol>'
            )
        else:
            text = "<br>".join(escape(line) for line in lines)
            rendered.append(
                f'<p style="margin:0 0 10px 0; line-height:145%;">{text}</p>'
            )
    return "".join(rendered)


def _reference_status(
    raw: str, field: str, installed: dict[str, int], active: set[str]
) -> list[str]:
    parsed = parse_mod_references(raw, field_name=field)
    lines = []
    for mod_id in parsed.identifiers:
        count = installed.get(mod_id, 0)
        if count == 0:
            status = "not found in scanned folders"
        elif count > 1:
            status = "multiple installations"
        elif mod_id in active:
            status = "active"
        else:
            status = "inactive"
        lines.append(f"  • {mod_id} — {status}")
    lines.extend(f"  ! {warning}" for warning in parsed.diagnostics)
    if not lines and raw.strip():
        lines.append(f"  Raw value: {raw.strip()}")
    return lines


def format_entry_details(
    entry: ModEntry,
    entries: tuple[ModEntry, ...],
    active_mod_ids: list[str],
    target_build: str = "all",
    include_description: bool = True,
) -> str:
    """Render all candidates, a broad layout preview, or the selected build candidate."""
    selection = resolve_entry_metadata(entry, target_build)
    candidates = selection.candidates
    representative_candidate = candidates[0] if candidates else None
    representative_fields = (
        representative_candidate.fields if representative_candidate else {}
    )
    display_name = representative_fields.get("name", "").strip() or entry.name
    display_author = (
        representative_fields.get("author", "").strip()
        or representative_fields.get("authors", "").strip()
        or ("" if target_build != "all" else entry.author)
    )
    display_version = (
        representative_fields.get("modversion", "").strip()
        or representative_fields.get("version", "").strip()
        or ("" if target_build != "all" else entry.version)
    )
    installed: dict[str, int] = {}
    for found in entries:
        if found.mod_id:
            installed[found.mod_id] = installed.get(found.mod_id, 0) + 1
    active = set(active_mod_ids)
    representative = (
        " (first metadata candidate)"
        if target_build == "all" and len(candidates) > 1
        else " (first matching candidate)"
        if len(candidates) > 1
        else ""
    )
    lines = [
        display_name,
        "",
        f"Mod ID: {entry.mod_id or '(missing)'}",
        f"Workshop ID: {entry.workshop_id or '(none)'}",
        f"Source: {'Workshop' if entry.source == 'workshop' else 'Local'}",
        f"Author{representative}: {display_author or '(not provided)'}",
        f"Version{representative}: {display_version or '(not provided)'}",
        f"Entry folder: {entry.entry_path}",
        f"Installation folder: {entry.installation_path}",
    ]
    if candidates:
        try:
            modified = candidates[0].path.stat().st_mtime
            lines.append(
                "Metadata modified: "
                + datetime.fromtimestamp(modified)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S %Z")
            )
        except OSError, OverflowError, ValueError:
            pass
    if target_build != "all":
        build_name = (
            "Build 41"
            if selection.status == "build-41"
            else "Build 42"
            if target_build == "42"
            else f"game build {target_build}"
        )
        lines.extend(
            (
                "",
                f"{selection.message}",
                f"This {build_name} metadata selection does not verify that the mod's content is compatible with the game.",
            )
        )
    elif len(candidates) > 1:
        lines.extend(
            (
                "",
                "Metadata candidates are shown separately; no active build candidate has been selected.",
            )
        )
    if installed.get(entry.mod_id or "", 0) > 1:
        lines.extend(
            ("", "Warning: this Mod ID appears in multiple installed entries.")
        )
    entry_diagnostics = list(entry.diagnostics)
    if selection.status in {
        "build-41",
        "selected-version",
        "selected-common",
    }:
        selected_paths = {candidate.path for candidate in candidates}
        entry_diagnostics = [
            message
            for message in entry_diagnostics
            if message
            != "Metadata candidates have different names; no active build was selected."
            and not any(
                message.startswith(f"{candidate.path}:")
                and candidate.path not in selected_paths
                for candidate in entry.candidates
            )
        ]
    if entry_diagnostics:
        lines.extend(("", "Entry warnings:"))
        lines.extend(f"  ! {warning}" for warning in entry_diagnostics)

    for candidate in candidates:
        fields = candidate.fields
        lines.extend(("", f"[{candidate.layout}]", str(candidate.path)))
        if candidate.version_folder:
            lines.append(f"Version folder: {candidate.version_folder}")
        for key, label in (
            ("name", "Name"),
            ("id", "Mod ID"),
            ("author", "Author"),
            ("authors", "Authors"),
        ):
            if fields.get(key):
                lines.append(f"{label}: {fields[key]}")
        for key, label in (
            ("modversion", "Mod version"),
            ("version", "Version"),
            ("versionmin", "Declared game version minimum"),
            ("versionmax", "Declared game version maximum"),
            ("url", "Homepage"),
        ):
            if fields.get(key):
                lines.append(f"{label}: {fields[key]}")
        for key, label in (
            ("require", "Declared requirements"),
            ("incompatible", "Declared incompatibilities"),
            ("loadmodafter", "Declared load after"),
            ("loadmodbefore", "Declared load before"),
        ):
            if fields.get(key):
                lines.append(f"{label}:")
                lines.extend(_reference_status(fields[key], key, installed, active))
        if fields.get("poster"):
            lines.append(
                "Declared posters: " + ", ".join(fields["poster"].splitlines())
            )
        if fields.get("icon"):
            lines.append(f"Declared icon: {fields['icon']}")
        if include_description and fields.get("description"):
            lines.extend(("", "Description:", fields["description"].strip()))
        other = sorted(set(fields) - _KNOWN_FIELDS)
        if other:
            lines.extend(("", "Other metadata:"))
            lines.extend(f"  {key}: {fields[key]}" for key in other)
        if candidate.diagnostics:
            lines.extend(("", "Candidate warnings:"))
            lines.extend(f"  ! {warning}" for warning in candidate.diagnostics)
    return "\n".join(lines)

"""Conservative, read-only extraction of high-signal PZ console findings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_MAX_LOG_BYTES = 32 * 1024 * 1024
_MAX_FINDINGS = 200
_WORLD_LOAD_FAILURE = re.compile(
    r"WorldDictionaryException:.*World loading could not proceed", re.IGNORECASE
)
_MISSING_DEFINITION = re.compile(
    r"ERROR:\s*(?P<kind>template|part)\s+[\"']?(?P<name>.+?)[\"']?\s+not found\b",
    re.IGNORECASE,
)
_MISSING_FLUID = re.compile(r"Fluid not found:\s*(?P<name>[^\]\r\n]+)", re.IGNORECASE)
_MOD_LUA_EXCEPTION = re.compile(
    r"Lua\(\(MOD:\s*(?P<mod>[^)]+)\)\).*Exception thrown",
    re.IGNORECASE,
)


class ConsoleLogError(ValueError):
    """The selected log cannot be read safely or is not a supported text log."""


@dataclass(frozen=True)
class ConsoleFinding:
    line_number: int
    category: str
    summary: str
    mod_name: str | None
    excerpt: str


@dataclass(frozen=True)
class ConsoleLogReport:
    lines_read: int
    findings: tuple[ConsoleFinding, ...]
    truncated: bool


def parse_console_log(text: str) -> ConsoleLogReport:
    """Extract known signatures without treating generic warnings as mod faults."""
    findings: list[ConsoleFinding] = []
    lines = text.splitlines()
    for line_number, line in enumerate(lines, start=1):
        category: str | None = None
        summary = ""
        mod_name: str | None = None

        if _WORLD_LOAD_FAILURE.search(line):
            category = "world-load-failure"
            summary = "The game reports that world loading stopped after script errors."
        else:
            definition = _MISSING_DEFINITION.search(line)
            fluid = _MISSING_FLUID.search(line)
            mod_exception = _MOD_LUA_EXCEPTION.search(line)
            if definition:
                kind = definition.group("kind").casefold()
                name = definition.group("name").strip().strip("\"'")
                category = f"missing-{kind}"
                summary = f"The game could not resolve {kind} '{name}'."
            elif fluid:
                name = fluid.group("name").strip().strip("\"'")
                category = "missing-fluid"
                summary = f"The game could not resolve fluid '{name}'."
            elif mod_exception:
                category = "mod-lua-exception"
                mod_name = mod_exception.group("mod").strip()
                summary = f"The log attributes a Lua exception to mod '{mod_name}'."

        if category:
            findings.append(
                ConsoleFinding(line_number, category, summary, mod_name, line[:400])
            )
            if len(findings) >= _MAX_FINDINGS:
                return ConsoleLogReport(len(lines), tuple(findings), True)
    return ConsoleLogReport(len(lines), tuple(findings), False)


def analyze_console_log(path: Path) -> ConsoleLogReport:
    """Read one explicitly selected console log; never follows a file symlink."""
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise ConsoleLogError("Choose a regular Project Zomboid console log file.")
    try:
        size = path.stat(follow_symlinks=False).st_size
        if size > _MAX_LOG_BYTES:
            raise ConsoleLogError("The log exceeds the 32 MiB safety limit.")
        with path.open("rb") as stream:
            raw = stream.read(_MAX_LOG_BYTES + 1)
    except OSError as exc:
        raise ConsoleLogError(f"Could not read the selected log: {exc}") from exc
    if len(raw) > _MAX_LOG_BYTES:
        raise ConsoleLogError(
            "The log exceeded the 32 MiB safety limit while being read."
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    return parse_console_log(text)


def format_console_log_report(path: Path, report: ConsoleLogReport) -> str:
    lines = [f"Read-only console diagnostics: {path} ({report.lines_read} lines)."]
    if report.truncated:
        lines.append(f"Only the first {_MAX_FINDINGS} findings are shown.")
    if not report.findings:
        lines.append(
            "No recognized high-signal findings were detected. Generic ERROR/WARN and require-failure lines are omitted because the game also logs benign and vanilla failures in those forms."
        )
        return "\n".join(lines)
    lines.append(
        f"Found {len(report.findings)} recognized line(s). The excerpt is evidence; it does not prove a mod is solely responsible."
    )
    for finding in report.findings:
        lines.extend(
            (
                f"{finding.category.upper()} at line {finding.line_number}: {finding.summary}",
                f"  {finding.excerpt}",
            )
        )
    return "\n".join(lines)

# Roadmap

Build 42 is the primary target; Build 41 root metadata remains supported. Work has proceeded milestone by milestone under `docs/ARCHITECTURE.md`. The current request authorizes continuing through the roadmap sequentially.

| Milestone | Status | Acceptance and limits |
| --- | --- | --- |
| 0 — Research and foundation | Complete | RimSort and PZ research, architecture, license notes, and incremental project structure recorded. No REA used. |
| 1 — Read-only discovery | Complete | Detect Steam/game paths; scan local and Workshop trees; parse root/common/versioned `mod.info`; preserve multiple entries and candidates. Fixture and real-library scans pass. |
| 2 — Mod management | Complete in code | Stage enable/disable/reorder and apply only the verified global `default.txt` with backup/atomic validation. Writer tests use temporary fixtures; the real game file remains untouched. |
| 3 — Profiles | Complete | App-owned ordered profiles, schema migration, import/export, missing IDs, overwrite recovery, and reversible deletion. |
| 4 — Dependencies | Complete | Candidate-aware requirements/incompatibilities, missing/inactive references, duplicate IDs, and cycles. Unsupported declarations remain visible rather than guessed. |
| 5 — Sorting | Complete as a proposal | Deterministic dependency/order-field proposal, persisted explicit before/after rules, stable manual-order ties, and cycle reporting. Game runtime equivalence is not claimed. |
| 6 — Workshop | Complete, read-only | Public item/page metadata, collection import, local/missing-item matching, and profile creation. No subscription, install, or update actions; Steam calls are mock-tested, not live-tested. |
| 7 — Advanced diagnostics | Complete, bounded | Duplicate IDs, opt-in `media/` file-overlap analysis, and conservative console-log parsing. Findings include evidence and do not claim runtime causality. |
| 8 — Usability | Complete for the initial app and follow-ups | Dark Qt palette, search, multi-selection/bulk controls, internal drag reordering, saved paths/window geometry and ordering rules, asynchronous scanning and diagnostics, and quick Mod Pack save/load in the main workspace. Fixture UI tests and a real-library UI scan pass. |
| 9 — Packaging and reliability | Local installer built | PyInstaller onedir and Inno Setup installer compile on this machine; a local install/launch check passed. Clean-machine and real-game checks remain release gates. |

## Remaining release gates

- Test the installer on a clean Windows account or VM, including persistence and recovery.
- Complete the exact Qt/PySide6/WebEngine third-party notice and corresponding-source obligations before binary publication. The original code is GPL-3.0-or-later.
- The local installer is unsigned; assess code signing before broad distribution.
- Keep per-save/server writes, Workshop subscription/download actions, and build-specific conflict guarantees out of scope until their formats and runtime behavior are independently verified.

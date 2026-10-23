# Roadmap

Build 42 is the primary target; Build 41 root metadata remains supported. Work has proceeded milestone by milestone under `docs/ARCHITECTURE.md`. The current request authorizes continuing through the roadmap sequentially.

| Milestone | Status | Acceptance and limits |
| --- | --- | --- |
| 0 — Research and foundation | Complete | RimSort and PZ research, architecture, license notes, and incremental project structure recorded. No REA used. |
| 1 — Read-only discovery | Complete | Detect Steam/game paths; scan local and Workshop trees; parse root/common/versioned `mod.info`; preserve multiple entries and candidates. Fixture and real-library scans pass. |
| 2 — Mod management | Complete in code; local game check passed | Stage enable/disable/reorder and apply only the verified global `default.txt` with backup/atomic validation. A temporary marker was applied to the local Build 42.21.0 global list, observed in the startup log, then removed; the original file was restored byte-for-byte. No save was opened, and gameplay was not tested. |
| 3 — Profiles | Complete | App-owned ordered profiles, schema migration, import/export, missing IDs, overwrite recovery, and reversible deletion. |
| 4 — Dependencies | Complete | Candidate-aware requirements/incompatibilities, missing/inactive references, duplicate IDs, and cycles. Unsupported declarations remain visible rather than guessed. |
| 5 — Sorting | Complete as a proposal | Deterministic dependency/order-field proposal, persisted explicit before/after rules, stable manual-order ties, and cycle reporting. Game runtime equivalence is not claimed. |
| 6 — Workshop | Complete, read-only | Public item/page metadata, collection import, local/missing-item matching, and profile creation. No subscription, install, or update actions; Steam calls are mock-tested, not live-tested. |
| 7 — Advanced diagnostics | Complete, bounded | Duplicate IDs, opt-in `media/` file-overlap analysis, and conservative console-log parsing. Findings include evidence and do not claim runtime causality. |
| 8 — Usability | Complete for the initial app and follow-ups | Dark Qt palette, search, multi-selection/bulk controls, internal drag reordering, saved paths/window geometry and ordering rules, asynchronous scanning and diagnostics, and quick Mod Pack save/load in the main workspace. Fixture UI tests and a real-library UI scan pass. |
| 9 — Packaging and reliability | Installer modes, version display, rolling updater, CI smoke checks, and provenance added | The version appears in the app window and installer metadata; the installer filename stays `ZomboidSorter-windows-setup.exe`. Pushed app changes build and smoke-test on GitHub before the verified installer is published to the rolling update channel. The Update button downloads it, closes the app, applies the installer, and relaunches. Stable `v<version>` releases remain available. The rolling and stable workflows passed for commit `1cbe22f`; the local updater helper relaunched v0.1.5, and the published rolling download passed updater verification. The app button was not run through a full published-update cycle; update-data preservation, Windows 10, and other-PC checks remain open. |
| 10 — Build-aware metadata | Complete with stated limits | An exact user-entered build selects the newest numeric version folder at or below that version; Build 41 uses root metadata, and shared metadata is used when no compatible versioned candidate exists. The selection informs details, dependency diagnostics, sort proposals, and file-overlap scans. File-overlap scans default to staged active IDs and the selected target; users can include all discovered entries or all metadata candidates. This is not automatic game-version detection and does not verify content compatibility or conflict behavior against the loader. |

## Remaining release gates

- Testing on another PC is unavailable in this setup. The updater-launched installer path, Windows 10, and preservation through that update path still need direct verification.
- The Qt/PySide6/WebEngine technical inventory, installer notices, and written source offer are prepared and recorded in `packaging/RELEASE_READY`; keep the offer available and re-review if bundled components or versions change. The original code is GPL-3.0-or-later.
- Releases are intentionally unsigned. Explain the expected SmartScreen warning in the README, and direct users to the official Releases page and the published checksum before running an installer.
- Keep per-save/server writes, Workshop subscription/download actions, and build-specific conflict guarantees out of scope until their formats and runtime behavior are independently verified.

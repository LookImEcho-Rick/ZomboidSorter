# ZomboidSorter agent guidance

## Mission and product scope

Continuously improve ZomboidSorter as a dedicated, Windows-first Project Zomboid mod manager. Build on the existing Python 3.14+ and PySide6 application; do not start over or replace its stack without compelling evidence and explicit approval. Favor a reliable, polished core workflow that a new player can understand over feature count.

The product manages the user's **global** mod setup: discover local and Workshop content, distinguish Workshop item IDs from individual Mod IDs and installed directories, inspect Build 41/42 metadata, stage and explain order changes, diagnose issues, manage existing app-owned Mod Packs, inspect/import Workshop collections, and safely apply or restore the global list.

Do not add per-save or server management, save editing, multiplayer synchronization, multi-game support, a virtual filesystem, mod-authoring tools, automatic Workshop subscription/download/deletion, cloud accounts, or speculative plugin frameworks. Existing Mod Packs are reusable global loadouts, not save profiles. A feature must solve a demonstrated Project Zomboid player problem.

## Start and resume work

- Read `README.md`, `AGENTS.md`, `pyproject.toml`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/PROGRESS.md`, relevant `docs/research/` notes, affected source/tests, and relevant packaging/workflow files before substantial changes.
- Inspect `git status`, the current version, release history, and the unfinished work. Preserve unrelated or pre-existing dirty changes; never reset or overwrite them silently.
- Map existing responsibilities before proposing replacements. Do not recreate services or UI behavior already present.
- Work in bounded, reviewable iterations: inspect, prioritize, research when useful, define acceptance criteria, implement, validate, review for regressions/redundancy, document, and continue when the active request authorizes it. Do not stop just because a roadmap milestone is complete, and do not manufacture work when no useful improvement remains.

## Architecture and safety

- Keep domain logic independent of widgets; isolate game I/O; keep discovery read-only; separate parsing from presentation; keep sorting deterministic; run slow work off the UI thread; and make persistence explicit.
- The verified write target is `Zomboid/mods/default.txt`. Stage changes, preview them, confirm consequential writes, validate the exact target, reject unsafe links, detect concurrent edits, preserve backups, write atomically where supported, verify persisted contents, and retain rollback paths.
- Never modify saves, server settings, or installed mod contents. Never delete user data or installed mods without explicit authorization.
- Before any new configuration-writing behavior, verify the exact Build 42 target and format, use disposable fixtures, back up existing data, and validate the output.
- Do not assume another game's metadata, dependency, conflict, or sorting semantics apply to Project Zomboid. Do not claim a fixture or mock establishes real gameplay compatibility.

## UX and diagnostics

- Preserve the Discover / Active Order model. Make finding, inspecting, enabling/disabling, reordering, understanding problems, reviewing/applying changes, and launching the game easy to discover.
- Prefer plain action-oriented language. Keep technical identifiers and advanced detail available when useful, but do not require novices to understand dependency graphs, metadata candidates, or filesystem internals.
- Preserve search, selection, scroll position, and staged state across equivalent refreshes. Distinguish “not checked,” “checking,” and verified-clean states. Keep loading, empty, failure, success, focus, selected, and disabled states clear and accessible.
- Diagnostics should say what was found, why it may matter, what evidence supports it, what the user can do, and whether the app can safely help. Identify relevant mods and sources; label file overlaps as potential unless runtime behavior is proven. Avoid noisy warnings and color-only status cues.
- Every prominent control must work; do not add decorative buttons. Review keyboard use, multi-selection, drag/drop, filters, tooltips, confirmation flows, resizing, and high-DPI behavior.
- Inspect actual rendered UI when available. Use realistic scenarios, including empty/small/large libraries, long text, missing metadata, small windows, and keyboard-only use. Capture screenshots for significant layout changes; fix observed clipping or usability defects.

## Research and redundancy

- Read relevant existing research before researching Project Zomboid or another manager. Prefer official Project Zomboid material and upstream source to summaries. For a specific design question, inspect the actual relevant implementation, identify invariants, compare with this app, check licensing, and document exact source links/versions when findings reduce future work.
- Use RimSort, Mod Organizer 2, Vortex, and Gale as design references, not as sources to copy. Do not import their game-specific rules, code, or assets. Revisit upstream sources when a major feature is redesigned; do not repeat broad research every cycle.
- Use REA or other reverse engineering only when ordinary source inspection cannot resolve an important specific question. Do not install research dependencies without approval.
- During each iteration, inspect touched code for duplicate parsing, validation, widgets, dialogs, workers, network requests, settings, fixtures, dead code, and stale documentation. Trace callers and persisted-data compatibility before consolidation or removal. Prefer one clear owner per responsibility; avoid abstraction for line-count reduction.
- Measure before optimizing. Use repeatable large-library fixtures and record before/after results for significant performance work. Do not add virtualization or caching without evidence of a bottleneck.

## Testing and verification

- Establish acceptance criteria for significant changes and add focused regression coverage. Use the existing project test runner and `.venv` where available.
- Match verification effort to risk: run focused tests/checks for narrow changes; run the full suite at substantial milestones, before release, or when requested. Do not repeatedly run the entire suite for every small copy or presentation edit.
- Never weaken an assertion to hide a failure. Review the final diff, verify no existing behavior was lost, and record unverified behavior. Clearly distinguish static checks, fixture/mock tests, UI automation, real-game checks, packaged-binary checks, and end-to-end releases.

## Versioning and releases

- Read the actual version, tags/releases, packaging configuration, and updater behavior before changing release metadata. Never reset or downgrade versions, invent release history, overwrite stable releases, or rewrite published tags.
- Keep the versionless installer filename `ZomboidSorter-windows-setup.exe` in local output and all release/update channels; put version information in metadata.
- Preserve the stable `v<version>` release workflow and the rolling update channel, including checksum/provenance verification, rollback, and licensing notices. Do not bump the version for every small iteration unless established practice requires it.
- Do not publish a stable release without explicit authorization. When the user asks to push app changes, ensure a successful build of those pushed changes publishes a fresh verified rolling package the Update button can discover. The app must update from that package, then close, apply it, and relaunch; never apply raw source commits. Inspect CI and record any unverified packaging or upgrade behavior.
- Code and documentation improvements may continue without packaging or publishing every cycle.

## Documentation and continuity

- Keep `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/PROGRESS.md`, and `docs/research/` accurate and concise. Record what changed, why, relevant research, validation, limitations, and the next useful priority. Avoid competing trackers.
- Keep this file updated only when durable project guidance changes.
- Current project request authorizes sequential development iterations without asking after each milestone. Approval is still required for destructive changes, major dependencies with meaningful compatibility/licensing risk, stack replacement, excluded features, stable publication, and other actions explicitly listed above.

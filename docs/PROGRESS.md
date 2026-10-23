# Progress

## Public-source preparation and Windows installer (2026-10-22)

- Chose GPL-3.0-or-later for original code. Created an independent wordmark/icon, fixture screenshots, end-user README, pinned Windows packaging constraints, Inno Setup script, checksum builder, and tagged-release GitHub Actions workflow. The workflow blocks binary publication until a documented Qt/WebEngine redistribution review is committed as `packaging/RELEASE_READY`.
- Removed the unused generated `pysidedeploy.spec`, which contained an absolute developer-machine path. Generated caches, build output, virtual environments, and `.codex-checkpoints/` are Git-ignored. Useful fixtures, tests, and research remain.
- Windows 11 local checks: 69 unit tests passed with one symlink-environment skip; Ruff check/format and compileall passed. PyInstaller 6.22.3 on Python 3.14.7 built the onedir app; Inno Setup 6.7.3 compiled a 151,796,348-byte installer and SHA-256 checksum. A silent install to a temporary path returned 0, and its GUI process stayed alive for five seconds. An installer-only 0.1.0→0.1.1 upgrade simulation preserved an isolated Mod Pack file byte-for-byte; silent uninstall returned 0, removed the app executable, and left that Mod Pack file intact. This was not an application-code upgrade.
- A public GitHub repository was created at `LookImEcho-Rick/ZomboidSorter`. No installer has been attached to Releases. The actual Qt/WebEngine license-text, notice, and source-delivery review, clean-account/VM run, Windows 10 test, and real-game write/launch validation remain open. The app's global-list write tests used fixtures only.

Updated 2026-10-22 after the desktop UX refresh.

## Launcher name (2026-10-22)

- The application window, Qt application identity, installed GUI command, and PyInstaller output now use **ZomboidSorter**. Existing settings and profile storage locations remain stable.
- Validation: the UI title assertion passed, Ruff check passed, and the Windows onedir package built successfully as `dist/ZomboidSorter/ZomboidSorter.exe`. The executable was built but not launched for this check.

## Launch handoff checks (2026-10-22)

- A successful `QDesktopServices.openUrl()` now reports that Windows accepted the Steam link and clarifies that game startup is unconfirmed. Fixture tests cover canceled apply, externally changed config, failed apply, and successful/failed link handoff; they verify that blocked paths do not request a launch.
- Validation: all 20 UI tests passed; Ruff check and source formatting passed. Steam handoff was mocked; the game was not launched.

## Apply and launch wording (2026-10-22)

- The workspace button changes to **Apply & Launch…** when the staged list differs from the loaded list. Its confirmation explains that the global list will be saved and verified before Project Zomboid opens through Steam.
- Validation: all 17 UI tests passed; Ruff check and source formatting passed. The confirmation-cancel fixture verified that the temporary game config remains unchanged. No live game was launched.

## Launch readiness feedback (2026-10-22)

- Launch is disabled until a valid supported global `Zomboid/mods/default.txt` is loaded at the selected path and still matches the on-disk file. A short inline message explains whether to load the list, choose the global target, or reload a changed list; the click handler keeps its existing checks.
- Validation: all 17 UI tests passed and Ruff check passed. Ruff format check reports pre-existing formatting differences elsewhere in `tests/test_ui.py`; the changed source file is formatted. Validation used temporary config fixtures; no live game configuration was written or game launched.

## Desktop UX refresh (2026-10-22)

- Reworked Mod Workspace around Discover, Active Order, and selected details. Pack actions sit above the workspace, transfer/order controls sit with their lists, and the footer holds a single Refresh, Launch, Discard, and prominent Apply route. Advanced Preview remains a secondary header toggle; paths stay in Settings.
- Added a shared Zomboid-inspired dark theme, two-line painted mod rows with issue/new badges, visible selection and focus states, and consistent dialog styling. Empty, scanning, scan-error, and unapplied-change messages remain explicit. The row delegate paints visible items without creating a widget per mod.
- Native Windows fixture captures at 1440×850, 980×620, and 980×620 with 150% Qt scaling are in `build/ux-*.png`; the compact detail pane was tightened after visual review. These captures used temporary profile storage and fixture config only. No actual game configuration or installed mods were changed.
- Validation: 16 focused UI tests and the full 65-test suite passed (one environment symlink skip). Ruff check and format passed for source, tests, and the native capture helper. The UI has not been verified against a live game installation or a packaged clean-machine build.

## Mod Pack load and management window (2026-10-22)

- Combined pack selection, deletion, import/export, and recovery in the **Load Pack…** window. Saving the current staged list remains in Mod Workspace; existing app-owned JSON data remains compatible.
- **Apply** explicitly applies the selected pack to the verified global mod list in one action. It uses the existing timestamped backup, atomic replacement, concurrent-change check, and readback validation. Per-save and server lists remain protected.
- The primary button and its instruction now both use the shorter **Apply** label.
- Validation: UI fixtures cover saving the current order, selecting among multiple packs, global-list apply, map preservation, backup creation, and closing the manager without discarding staged changes. All 65 unit tests passed (one symlink test skipped); Ruff check/format and compileall passed. An offscreen capture confirmed the layout; that Qt platform rendered text as square glyphs, so a native-window visual check and real-game integration were not run. No actual game config, saves, Workshop subscriptions, or installed mod files were modified; config writes used temporary fixtures.

## Launch and button polish (2026-10-22)

- Added **Launch Project Zomboid** below **Select Filtered**. It requires the loaded target to be the supported global `Zomboid/mods/default.txt`, checks for external changes, and applies staged IDs with the existing confirmation, timestamped backup, atomic write, and readback validation before opening `steam://run/108600`. Cancelled, failed, stale, or unsupported configuration state prevents launch. Steam starts the game so its launch configuration is used; per-save and server lists remain protected.
- Updated multiword button labels to title case across the main window and dialogs.
- Validation: Ruff check/format and Python compile checks passed. Automated tests, native UI launch, and game launch were not run. No game configuration or installed files were written during validation.

## RimSort-inspired UI Phase A (2026-10-22)

- The default workspace now puts selected-mod details, inactive mods, and the staged active list in one horizontal, noncollapsible splitter. It saves splitter sizing in `QSettings`; each list has a count and search field. Existing list activation, ordering, profile, diagnostics, and confirmed global-list apply handlers remain in place.
- The large preview area intentionally shows a placeholder; finding and loading actual Project Zomboid preview images is Phase C. The full library table and diagnostics remain in a secondary tab, with paths and profiles in another tab. Discovery results populate the inactive list even when the global config cannot be loaded.
- Styling uses a compact dark palette inspired by RimSort, implemented independently. No RimSort code or assets were copied. A copy of the prior UI file is in `.codex-checkpoints/phase-a/` because this folder has no Git metadata.
- Validation: 57 unit tests passed (1 environment symlink skip); Ruff checks passed. A native Windows Qt launch and captured screenshot displayed the fixture lists with 2 active and 5 inactive IDs and readable text. An offscreen launch also succeeded but its software platform rendered square glyphs. These checks used fixtures; no game config, saves, or installed mods were modified.

## RimSort-inspired UI Phase B (2026-10-22)

- Inactive search now matches names, Mod IDs, and Workshop IDs; its source/warning filter and ascending/descending name/ID sort operate on scanned in-memory records. The active list has matching search and issue/source filters, while its visual order remains the staged global order.
- Both lists keep multiselection and double-click staging. Their context menus now offer relevant stage, copy ID, folder, Workshop-page, and select-visible actions. Shortcuts cover Ctrl+F, Ctrl+A, Enter, Escape, and Delete on the active list. Hidden selections are excluded from bulk stage actions.
- Drag reorder remains available in the unfiltered active list; it is disabled while a search/filter is active to avoid confusing hidden positions. Cross-list drag was added in the workspace follow-up below. The prior Phase A UI and tests are copied under `.codex-checkpoints/phase-b/` because this folder has no Git metadata.
- Validation: 59 unit tests passed (1 environment symlink skip); Ruff format/check and Python compileall passed. A native Windows Qt screenshot with fixture data showed no control overlap. These checks do not apply changes to the game configuration.

## RimSort-inspired UI Phase C (2026-10-22)

- The selected-mod pane now resolves declared `poster=` images (falling back to `icon=`), including versioned paths into `common/`, without permitting paths outside the mod entry. It decodes bounded images in a worker thread, caches recent previews, and shows the source candidate. Missing or unreadable images keep a clear placeholder.
- Details now separate every Build 41/42 metadata candidate, preserve descriptions and uncommon fields, show declared version bounds and dependency/order references with installed/active status, and identify duplicate IDs and parser warnings. Open-folder and Workshop-page actions use the selected entry's own paths and numeric Workshop ID.
- Validation: 62 unit tests passed (1 environment symlink skip); Ruff and compileall passed. After the final cache-generation guard, the 15 focused UI/detail tests and Ruff passed again. New tests cover candidate-specific formatting, safe path resolution, and asynchronous preview display using temporary fixtures. A read-only scan of the actual installation found 52 resolvable previews among 57 entries; a native Qt capture displayed one real poster. No game configuration, saves, or installed mod files were modified.

## RimSort-inspired UI Phase D (2026-10-22)

- The workspace shows discovery/dependency warning and error counts beside the active list, a compact footer with Refresh, activation actions, Discard changes, and Apply, plus a visible indicator for unapplied edits. Discard changes confirms before restoring the last loaded global list in memory; it does not write game files.
- Scan and optional diagnostic work show an indeterminate progress indicator in the status bar until their workers finish. It indicates activity, not item-by-item completion. The existing Apply confirmation, backup, and target checks remain in place. No speculative Run or download action was added.
- Validation: 63 unit tests passed (1 environment symlink skip); Ruff check/format and compileall passed. A native Windows Qt fixture capture at `.codex-checkpoints/phase-d/workspace-native.png` showed the controls without overlap at 1440×850. The new UI test checks counts, busy feedback, discard confirmation, and unchanged fixture config bytes. No game configuration, saves, or installed mod files were modified.

## RimSort-inspired UI Phase E (2026-10-22)

- Long names now elide within compact mod rows instead of opening horizontal scrollbars; every row tooltip retains its full name/ID and any issue explanation. Search, lists, details, and preview have accessible names, major actions have explanatory tooltips, and focused controls use a visible accent border. The ordering and Workshop dialogs wrap their introductions and label key fields for assistive technology.
- Native Qt captures at 980×620 and simulated 150% scale show the three panels, footer, and status without overlap. Captures of both secondary dialogs show the same dark theme. Compared with the modern RimSort reference, the main information/list proportions and compact controls are close; this app still uses plain text rows and tabs rather than RimSort's icon-rich rows and menu structure. No performance optimization was added without a measured bottleneck; hundreds-of-mod responsiveness remains unbenchmarked.
- Validation: 63 unit tests passed (1 environment symlink skip); Ruff check/format and compileall passed. Screens and tests used fixtures, not a full game integration run. No game configuration, saves, or installed mod files were modified. Pre-change source copies and captures are in `.codex-checkpoints/phase-e/`.

## Steam Workshop and tab navigation (2026-10-22)

- Steam Workshop now uses a compact browser toolbar and fills the rest of its tab with the embedded page. The page opens on first visit; Back, Forward, Reload, Home, title search, direct URL/ID navigation, and external-browser fallback remain available. Returning to Mod Workspace still triggers a fresh local scan.
- After a scan finds Workshop items or entries that were absent from the previous scan, the status bar reports the additions and matching mod rows receive a green `NEW` marker. Inactive and active headings show how many marked rows each list contains; the markers clear on the next successful scan with no new additions.
- Collection import now has a dedicated tab. It explains the read-only collection review/profile flow, stays unavailable until a library scan completes, and reports the saved profile. Library & Diagnostics remains hidden unless Advanced Preview is checked.
- Advanced Preview now sits in a slim row above the tabs instead of the tab corner, removing the corner divider, and no longer gets the blue focus border when clicked.
- The UI was validated with Ruff formatting/check and Python compile checks. Automated tests and native visual launch were not run. No game configuration, saves, Workshop subscriptions, or installed mod files were changed.

## Workspace drag staging and metadata build preview (2026-10-22)

- Dragging selected inactive entries to Active stages them at the drop position; dragging active entries to Inactive removes them from the staged order. Multi-selection is preserved. Internal active-list reordering remains available when unfiltered, and filtered active-list drops append to avoid implying a hidden row position.
- The details pane now filters candidate metadata and the declared poster/icon by All, Build 41, or Build 42. The filter follows observed layout: root-style candidates for Build 41 and shared/versioned candidates for Build 42. It is a display filter, not a compatibility check or runtime selection, and does not affect staged mods or game files.
- The selected mod now shows its full public Steam Workshop description when available, with Steam headings, lists, and emphasis formatted in the Description panel. Fetching is read-only and asynchronous; local `mod.info` descriptions appear while loading or if the Workshop listing is unavailable. A vertical splitter gives Description and Metadata separate, resizable panels. Identical local candidate descriptions collapse into one when used as fallback. Some item responses omit `consumer_appid`; the local PZ Workshop path supplies that context, while an explicit foreign app ID is rejected.
- Validation: Ruff formatting/check and Python compile checks passed. A read-only live lookup of Workshop item 3811472160 returned its title and 1,948-character BBCode description. Automated tests and native UI launch were not run for this follow-up. No game configuration, saves, Workshop subscriptions, or installed mod files were changed.

## Completed implementation

- **Research/foundation:** Python 3.11+ and PySide6, Windows first, modular discovery/game I/O/profile/diagnostic/sorting services. RimSort source was inspected for architecture and workflow; no code or assets were copied. See `docs/research/`.
- **Discovery:** Steam/game path detection, local and Workshop scanning, Build 41 root and Build 42 common/version candidates, multiple Mod IDs per Workshop item, duplicate-ID reporting, defensive metadata parsing, search/details/diagnostics. Repeated `description=` and documented repeatable `poster=` values are preserved.
- **Mod management:** staged global `default.txt` list, ordered enable/disable and move/drag actions, maps preservation, explicit apply confirmation, timestamp backup, atomic write/readback, concurrent-change check, and strict rejection of unsupported/save-scoped targets.
- **Profiles:** app-owned JSON profiles with stable order, unavailable Mod IDs and Workshop IDs, v1→v2 schema compatibility, import/export, overwrite backups, reversible deletion, and restore.
- **Dependencies/sorting:** candidate-specific `require`, `incompatible`, `loadModAfter`, and `loadModBefore` analysis. Explicit before/after rules are editable and persisted in app settings. The deterministic proposal retains current order as a tie-breaker and stops on cycles; it is not presented as a runtime guarantee.
- **Workshop:** read-only public collection/item metadata, URL links, PZ App ID filtering, installed/missing resolution, and profile creation. No subscription/download/update side effects.
- **Advanced diagnostics:** bounded opt-in overlap comparison under metadata candidate `media/` roots; conservative log signatures with explicit attribution only; exact paths retained in findings.
- **Usability:** dark Qt palette, searchable table, multi-select and bulk actions, filtered select, internal drag reorder, persisted paths/geometry, async scan/diagnostic workers.
- **Packaging:** PyInstaller onedir Windows output, `packaging/build_windows.ps1`, and packaged-folder documentation. The build isolates `PATH` during DLL collection to prevent unrelated applications from supplying incompatible Qt dependencies.

## Validation

- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`: 55 passed, with one symlink test skipped because this environment does not permit creating filesystem symlinks.
- `.\.venv\Scripts\ruff.exe check src tests` and `ruff format --check src tests`: passed.
- `.\.venv\Scripts\python.exe -m compileall -q src tests`: passed.
- PyInstaller 6.22.3 build on Windows 11/Python 3.14.7 completed with the sorting-rules UI included. A packaged launch displayed `Project Zomboid Mod Manager — Library Discovery` under the normal developer-shell `PATH`; Qt initialization succeeds.
- Real PZ 42.21.0 read-only scan: 57 entries, 50 Workshop items, 80 metadata candidates, zero metadata/duplicate diagnostics, and 15 global active IDs. No config was written.
- Real opt-in media scan: 17,120 candidate files; 2,732 potential differing/unverified path pairs. It displays up to 100 evidence rows and does not assert actual runtime conflict.
- Real `console.txt` read-only parse: 2,398 lines and zero recognized high-signal findings. Generic engine/vanilla messages are deliberately ignored.
- Profile writes and global-list writes were tested against temporary fixture paths only. No save directory contents, game config, or installed mod files were modified.

## Release limitations

- The packaged app has been smoke-tested on the development machine. A clean Windows account/VM, Windows 10, and real-game apply/launch checks remain outstanding.
- Workshop API integration is response-mock tested, not live-tested. Subscription, update, and download flows are absent.
- Exact Build 42 runtime selection/precedence, duplicate-Mod-ID winner behavior, and resource-specific file override/merge semantics remain unresolved. The UI labels candidate overlaps as potential.
- Per-save and server configurations are intentionally unsupported. The original code is GPL-3.0-or-later. The technical Qt/WebEngine notice and source review is recorded in `packaging/RELEASE_READY`; the maintainer remains responsible for fulfilling the written source offer.

## Public release preparation (2026-10-22)

- Created and pushed the public repository at `LookImEcho-Rick/ZomboidSorter`. The project has a GPL-3.0-or-later license, fixture-labeled README screenshots, the ZomboidSorter wordmark/icon, an Inno Setup per-user installer, and a tagged-release Actions workflow. The workflow requires `packaging/RELEASE_READY`, which now records the Qt/WebEngine notice and source review; clean-account and real-game checks remain separate release validation.
- Added the maintainer's written source offer for exact bundled Qt/PySide6/WebEngine sources. The installer displays it before installation and includes it with GPL/LGPL, CPython, and PyInstaller license texts. GitHub Issues are the request channel.
- Completed the pinned Qt redistribution inventory: offline appendices include all 138 Qt 6.12.0 attribution pages and 125 unique Qt WebEngine 6.140.0/Chromium 140 license pages, including their copyright lines and license texts. Added LGPL-2.1/3.0 and FDL-1.3 texts, runtime OpenSSL Apache-2.0, build-copied CPython/PyInstaller/Inno license texts, and a per-build component/version manifest. Added official source archive locations and recorded the source-offer commitment in `packaging/RELEASE_READY`.
- The original Windows PyInstaller build excluded parallel Qt WebEngine debug resource copies after checking their release counterparts. It retained the full QML tree pending a dependency-backed trim; the Qt bundle minimization below supersedes that bundle.
- Validation: 69 unit tests passed with one environment symlink skip; Ruff check/format and compileall passed. The trimmed-resource WebEngine smoke loaded a local HTML data page successfully from the development Python environment using the packaged resource path. The Inno installer compiled, installed to an isolated directory, launched for five seconds, and silently uninstalled; the installed executable was removed. Earlier installer-only 0.1.0→0.1.1 upgrade testing preserved an isolated Mod Pack fixture byte-for-byte, but the rebuilt optimized 0.1.0 installer was not separately upgrade-tested.
- The latest local installer is `dist/installer/ZomboidSorter-0.1.0-windows-setup.exe` with SHA-256 `6df0be0963b9008db427f1607b31e3226dc1011f59380f262f8dbb5b1ea5a905` (142,621,063 bytes). It was built with CPython 3.14.7, PyInstaller 6.22.3, OpenSSL 3.5.7, and Inno Setup 6.7.3 on Windows 11; the release workflow is configured for CPython 3.11 and Inno Setup 6.7.1. No GitHub Release exists yet.

## Isolated installer checks (2026-10-22)

- A fresh temporary Python 3.14.7 environment installed `.[dev,windows]` under the pinned Windows constraints. All 69 unit tests passed with one environment-only symlink skip; Ruff check, Ruff format check, and compileall passed.
- Rebuilt the 0.1.0 onedir app and Inno installer. An isolated per-user install into a temporary directory launched and stayed open for eight seconds. A same-version reinstall preserved a temporary Mod Pack and the app settings registry key; silent uninstall removed the executable and preserved both. The temporary registry changes were restored to their original values, and the test install was removed.
- The app's `MainWindow` created its embedded `QWebEngineView` in the fresh Qt environment and loaded the live Project Zomboid Steam Workshop page (`The Steam Workshop for Project Zomboid`, document ready state `complete`).
- This non-elevated Windows Home session had no ready-to-use VM tooling (Hyper-V cmdlets, Windows Sandbox executable, VirtualBox, or QEMU were unavailable), so the full clean-OS VM/account pass was not possible. Only Python 3.14.7 is installed; the release workflow's Python 3.11 build remains unverified here. The remote has no tags or GitHub Releases, so this pass could not test an upgrade from a previous installer; the earlier installer-only 0.1.0→0.1.1 simulation remains the only upgrade evidence.

## Qt bundle minimization (2026-10-22)

- Added project-local PyInstaller hooks to omit QML assets/debug tooling and unused touch/virtual-keyboard plugins. This app has no QML views; Qt WebEngine's required Core, Gui, Widgets, Qml, Quick, and WebEngine runtime dependencies remain.
- The clean PyInstaller build now contains 19 Qt6 runtime DLLs, no QML directory, and no generic-touch, platform-input-context, or QML-tooling plugins. The bundle-scoped Qt appendix contains 57 pages (4,047 lines), selected from the 138-page source inventory; the full 125-page WebEngine/Chromium appendix remains (11,518 lines). Full pinned source appendices are stored as gzip files and expanded into readable installer notices at build time.
- The notice generator checks the expected upstream page counts, inventories the actual runtime DLLs in `licenses/BUILD_COMPONENTS.txt`, and refuses to proceed if excluded QML/plugin groups reappear. The installer uses the generated notice set; readable HTML pages are staged under ignored `build/installer_payload/licenses/`, outside the app bundle.
- The tracked source now stores the 27,018-line upstream HTML appendices as two gzip files (about 295 KB combined). Only the installer payload expands readable notices; `dist/ZomboidSorter/` contains no generated HTML attribution files.
- PyInstaller clean build, notice generation, reduced-bundle app/WebEngine smoke, and installer compile passed. The 119,892,820-byte installer (`SHA-256 3ea0ea57e6a5eac9ce32b8f5dd17e49e8d783bf2b2f523f699e7e2aff0473265`) silently installed to a fresh temporary directory, launched under a system-only `PATH`, opened the Workshop tab with its bundled WebEngine process, and silently uninstalled. The preexisting app settings registry values were restored exactly. A full clean-OS VM check remains unavailable on this Windows Home host.

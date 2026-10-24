# Progress

## v0.2.3 metadata warnings and media previews (2026-10-24)

- Build 42 diagnostics now explain when an entry has only root-level Build 41 metadata, while the workspace and detail pane keep the discovered mod name instead of replacing it with “No matching metadata.” This reflects The Indie Stone's documented Build 42 folder requirement; it does not imply the scanner failed or repair third-party mod content.
- Discover now has **Show all**, **Build 41**, and **Build 42** filters based on root versus shared/versioned metadata. The selected build family scopes row warnings and the aggregate metadata/dependency diagnostics, so warnings for the other family are not shown.
- Preview selection tries declared local poster/icon images and GIFs in order, skips video references, and moves on when a file cannot be decoded. GIFs animate. If the target build has no preview candidate, artwork from another retained candidate may display with its source and an explicit illustration-only compatibility label.
- Validation passed: all 146 tests passed with one environment-only symlink skip; Ruff check/format, compileall, and `git diff --check` passed. Fixture coverage includes build-family filtering/warning scope, Build 42 root-only metadata, image fallback, GIF playback, global-list preflight, and backup preview. No live game files were read or changed and no game was launched. Hosted packaging and rolling-update publication are pending the 0.2.3 push.

## Global-list preflight, backup browser, and installed-app screenshots (2026-10-24)

- Added an advisory preflight before global-list writes and clean launches. It reports active IDs missing from the scan, duplicate active or installed IDs, and declared dependency findings; the user can cancel or explicitly continue. It does not block based on inferred compatibility.
- Replaced the native backup file picker with a newest-first browser. Selecting a backup validates and reads it, then previews the Mod IDs, maps, and ordered changes before the existing separate default-No restore confirmation. The guarded restore writer is unchanged.
- Replaced README screenshots with captures from the installed v0.2.2 app and its live library (23 active IDs; 55 Workshop items and 62 scanned entries). The Discover filter was set to Viewpoint for the workspace capture; scans were read-only and the global list was not changed.
- The installed v0.2.2 executable predates the current global-only source changes, so it still displays the retired **Apply Elsewhere…** control. The screenshots document the real installed app and do not demonstrate the new preflight or backup-browser UI. A local PyInstaller build completed successfully; Ruff check and format checks passed. Automated tests were not run.

## Global-list-only launcher scope (2026-10-24)

- Removed per-save apply, backup restore, reset-to-global, and save-list import, along with server settings apply and backup restore. The launcher now manages only the global `Zomboid/mods/default.txt` list; Mod Pack save/load, Workshop collection import, global backup restore, and launch remain available.
- Removed the unused UI/core modules and their dedicated save/server tests and fixtures. Updated the README and architecture guidance. No save, server, or game configuration files were read or changed during this cleanup. Automated tests were not run in this pass.

## v0.2.2 path setup UX polish (2026-10-24)

- Renamed the tabs to **Paths Settings** and **Library Diagnostics**. Added per-field **Auto Detect** actions and **Detect All**. All path detection is read-only; unavailable game or Workshop paths are kept, and multiple game installations prompt for a choice. Compact indicators show path health; tooltips and accessibility descriptions give the found, missing, unreadable, invalid, or partial state and expected location.
- All 52 UI tests passed, covering path updates, missing-path handling, multiple-install selection and cancellation, health indicators, minimum-window layout, and tab captions. A focused invalid-Workshop-path regression check also passed after review. Ruff and `git diff --check` passed. Detection follows known Steam libraries, so non-Steam game installs still require Browse. No live game files were changed.

## v0.2.1 apply previews and save/server backup restore (2026-10-24)

- Global, save, and server apply confirmations now preview ordered Mod ID changes; global and save previews include maps, while server previews include Workshop IDs. The Mod Pack manager compares the selected pack with the loaded global list before Apply. Long lists are shortened with counts.
- Ordered-list previews now show the specific IDs involved in reordering, even when they occur beyond the first 12 entries; long reorder details remain capped.
- **Apply Elsewhere…** can restore a timestamped backup for one selected save or server settings file. The UI validates and previews the selected sibling backup, asks with default No, and warns to close the game/server. The writer rechecks the current file, backs it up when it exists, restores the original bytes atomically, and verifies the result. Restoring a save backup creates an explicit list when that save currently inherits global settings. Server restore returns the entire `.ini` to the selected backup, including its other settings.
- **Reset save to inherit global list…** previews and backs up one explicit `mods.txt`, then removes it after default-No confirmation and stale-snapshot checks. This returns the save to global-list inheritance. Save and server target dialogs remember the last valid locations in `QSettings`. Server backup restore previews changed lines across the entire `.ini`; password-, token-, secret-, credential-, and webhook-like values are masked, and the preview is capped at 24 changed lines.
- Focused validation: 24 tests across save lists, server settings, change previews, and four selected UI flows; 23 passed and one environment-only symlink test was skipped. Ruff check/format and `git diff --check` passed for the changed files. All targets were temporary fixtures; no live save, server settings file, or installed game was changed. Packaged and live-game validation remain separate.

## v0.2.0 UX and UI polish (2026-10-23)

- Refined the existing dark olive workspace with clearer panel hierarchy, roomier controls, a visible Library & Diagnostics tab, and concise guidance for discovery, staging, settings, and Workshop browsing. On shorter windows, extra guidance collapses, action labels shorten, and the active controls use two rows so the mod lists retain space. The minimum window is 980×680.
- Filtered list headings now show visible versus total mods; transfer and ordering controls reflect the current selection. A missing or changed global-list target shows a direct route to Paths & Settings. Library rows can be opened in Mod Workspace with **Inspect Selected** or a double-click.
- Mod Packs now preview ordered Mod IDs, Workshop IDs, and maps before Apply. Workshop collection review clears stale results on a new fetch or failure, and its Create button requires a name. Save import, ordering rules, overlap results, and support-report dialogs use consistent headings and spacing. Paths & Settings scrolls at shorter heights, and selected-mod Description and Metadata use tabs so both remain readable.
- Validation: all 148 tests passed with two environment-only symlink skips; Ruff check/format, compileall, and `git diff --check` passed. Native fixture captures were reviewed at 1440×850 and 980×680. These are fixture UI checks; no game configuration, save, installed mod, or installed app was changed.
- Reworked the README around the app's purpose, screenshots, a short first-run path, and a compact action/target reference. Local link and Markdown structure checks passed.
- Final hosted rolling workflow [40050307907](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/40050307907) passed packaged install/launch and in-app update smoke checks. Its manifest identifies commit `48285567e01dae3315cfc7ca54c414ce1804ea0b`; the versionless installer SHA-256 is `e9ec67d31c6e41058c9af963d06d59ca491058b2bf253a0a2a5f27a38d751527`, matching the published checksum sidecar and GitHub asset digest. The rolling tag pointed to that commit at publication.
- Tagged [v0.2.0](https://github.com/LookImEcho-Rick/ZomboidSorter/releases/tag/v0.2.0) at the same commit. Hosted release workflow [40050954600](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/40050954600) passed tests, lint, build, upgrade smoke from the previous stable installer, standard/portable install smoke, and release publication. The stable release contains the versionless installer (120,203,938 bytes; SHA-256 `d63ec5a19c8742976ef057c5e37155bb79386dbc178d78a7238fc18e5f420753`); its checksum sidecar matches GitHub's asset digest. These hosted checks do not verify gameplay or modify this machine's installed app.

## v0.1.8 release verification (2026-10-23)

- Published [v0.1.8](https://github.com/LookImEcho-Rick/ZomboidSorter/releases/tag/v0.1.8) from commit `acafaf9e3e29e59bc445eb5360d18ad24a0bb455`. It includes the redacted support report, the UI layout split, larger-library coverage, and rolling-update recovery changes.
- Local validation passed: 129 tests with two environment-only symlink skips; Ruff check/format, compileall, PowerShell parsing, workflow YAML parsing, and `git diff --check`. No manual second-PC checks were run, as requested. No real game config or save was changed and no game was launched.
- The first rolling attempt exposed three Windows test assertions hidden by unchecked PowerShell exit codes and a temporary-folder cleanup failure after the updater itself passed. The tests now account for Windows path normalization and queued UI signals; both workflows check each native command's exit code, the smoke cleanup retries, and the rolling tag advances only after the update smoke passes.
- Final hosted Windows 2022 rolling workflow [40040897509](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/40040897509) passed tests, lint/format, compilation, packaged install/launch, provenance, and an update from the prior stable v0.1.8 build. It verified relaunch, receipt handling, portable profile/settings preservation, uninstall, and cleanup. The manifest identifies commit `acafaf9e3e29e59bc445eb5360d18ad24a0bb455`; the 120,229,538-byte rolling installer SHA-256 is `f709ee6a7197d7265a04779d9ca3caa18f248551ef9982c68b1ff0e1c5e56a83`, matching its checksum sidecar and manifest.
- Final tagged workflow [40041492180](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/40041492180) passed strict tests, lint/format, compilation, upgrade from v0.1.7, standard/portable install smoke, and provenance. The [stable release](https://github.com/LookImEcho-Rick/ZomboidSorter/releases/tag/v0.1.8) contains the versionless installer (120,175,343 bytes; SHA-256 `4eefa7c83481f867086082f5436d2eecb44b6a22c2c7038e754a50b08af5b4e9`); its checksum sidecar matches GitHub's asset digest.

## Redacted support reports and large-library coverage (2026-10-23)

- Added **Help → Save Support Report…**. It previews a JSON report before saving. The report includes app/runtime versions, OS type, aggregate path health, scan totals, and staged-list counts; it omits path strings, mod names and IDs, Workshop IDs, log text, and file contents. The freeform exact-build field is included only when it parses as a numeric game version.
- Added synthetic coverage for 1,250 entries (250 local and 1,000 Workshop), including scan timing, overlap-analysis truncation at its pair cap, and cancellation after the first 25 Workshop entries.
- Validation: all 129 tests passed with two environment-only symlink skips; this includes the support-report privacy/save-preview tests, 1,250-entry scale test, and all 41 UI tests. Ruff check/format, compileall, and `git diff --check` passed. No real game configuration, save, or installed mod was touched.

## Rolling release recovery, Windows target, and UI layout split (2026-10-23)

- The rolling workflow now saves the previous release assets and tag, verifies their manifest/hash/size agree, and restores them if publishing or the old-app update smoke fails. Rolling runs are serialized so a rollback cannot race a newer update. The candidate is still publicly visible during the end-to-end smoke window; rollback is the recovery path if that check fails.
- Windows 11 x64 is the verified target. Windows 10 Home/Pro is no longer a support target; its Microsoft support ended on October 14, 2025. Another-PC checks remain outside the current acceptance scope. Build 41/42 gameplay and loader behavior remain unverified; no game config or save was accessed for this work.
- Split the workspace and Workshop collection tab builders out of `window_layout.py` into focused UI modules without changing their behavior.
- Validation: all 39 UI tests passed; Ruff check/format, compileall, workflow YAML parsing, and the updater smoke script's PowerShell syntax check passed. The updated GitHub workflow and rollback path were not run on Actions.

## Map-aware Mod Packs, scan reuse, and Build 41/42 config checks (2026-10-23)

- Mod Pack schema v3 stores ordered map IDs alongside Mod IDs and Workshop IDs. Saving from the global workspace captures the global maps; **From Save…** captures the save's explicit map list. Applying a map-aware pack requires a default-No prompt before replacing global maps and writes both lists through the guarded, backed-up atomic writer. Legacy v1/v2 packs have no explicit map list and preserve the currently loaded maps.
- Repeated scans are reused for 30 seconds only when the previous scan took at least 250 ms and the selected roots are unchanged. **Refresh** always scans again. The real local library had 62 entries and 85 metadata files; three reads took 0.070, 0.067, and 0.069 seconds (0.069-second median), so its normal scans do not use the cache. Build 41 selection resolved 39 entries; exact Build 42.21.0 selection resolved 36.
- Build 41 and Build 42.21.0 config flows passed using separate temporary global-list files: both ordered lists were written and read back, and each backup matched the initial bytes. Real mod metadata was read for the scan measurements, but no real game config or save was accessed, no installed mod was changed, and no game was launched. The checks validate file and metadata-selection behavior, not gameplay or loader compatibility.
- The Windows 2022 rolling workflow [39936416492](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/39936416492) passed the full update path from the v0.1.6 portable installer: **Check for Updates**, helper handoff, verified v0.1.7 install and relaunch, success receipt/dialog, portable profile/settings preservation, clean close, and uninstall with data retained. The rolling manifest identifies commit `cb7a92e105d2531d98114d9628ab7473fb923af7`; its 120,151,323-byte installer SHA-256 is `cdcbeaf1b5e67a62df858cf4a9d235b1819c7334a0aab0bcbfb7db4e2c546bf5`. [Rolling package attestation](https://github.com/LookImEcho-Rick/ZomboidSorter/attestations/59027292).
- The Windows 2022 tagged release workflow [39937388410](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/39937388410) passed tests, lint/format, compilation, v0.1.6 upgrade and standard/portable install smoke, and provenance attestation. It published [v0.1.7](https://github.com/LookImEcho-Rick/ZomboidSorter/releases/tag/v0.1.7) with the required versionless installer (120,135,965 bytes; SHA-256 `446378f999a18e7a249a213bbaa449161de8a178a3df3dbb3fcd7f9673d69e3d`); the published checksum sidecar matches GitHub's asset digest. [Stable installer attestation](https://github.com/LookImEcho-Rick/ZomboidSorter/attestations/59029941).
- Local validation passed: 125 tests with two environment-only symlink skips, Ruff check/format, compileall, PowerShell parsing, workflow YAML parsing, and a Windows onedir PyInstaller build. Build 41 and exact Build 42.21.0 config-flow checks used disposable files; no game config or save was written and no game was launched. Gameplay/loader behavior, Windows 10, and another-PC checks remain open.

## Update results, global backup restore, and save-list import (2026-10-23)

- The update helper now checks that the installed executable and `BUILD_ID` match the downloaded package, records a one-time result, and relaunches the app. On startup, the app reports verified success or failure and shows the temporary error-log path when available.
- Added **Restore Backup…** for the supported global list. It previews ordered Mod ID/map changes and staged edits, requires a default-No confirmation, restores through the guarded atomic writer, and creates a fresh backup of the current file first.
- Added **Mod Packs → From Save…**. Discovery reads only immediate per-save `mods.txt` files under the selected Saves root. It shows each list's Mod IDs and maps, notes saves that inherit the global list, and copies ordered Mod IDs into an app-owned pack. Maps are preview-only under the existing Mod Pack schema; applying or importing never writes to a save.
- Validation: all 121 unit tests passed with two environment-only symlink skips; Ruff check/format, compileall, and `git diff --check` passed. Focused coverage includes success/failure update receipts and dialogs, backup restore, save-list discovery, and UI flows. A read-only inspection of one local save `mods.txt` found version 1 with 11 Mod IDs and no maps; it does not establish compatibility across all game builds.
- The PowerShell helper was exercised end-to-end with a fresh local installer and isolated temporary portable install. It applied the installer, checked `BUILD_ID`, relaunched the packaged app, showed the success dialog, consumed the receipt, and preserved seeded portable settings and a Mod Pack. This reapplied the same build. The updater module then discovered the published 0.1.6 package while simulating the previous v0.1.5 build, downloaded the 120,133,206-byte installer, and verified its SHA-256 and Windows executable header. The old packaged app's button-to-helper handoff was not run. Windows 10 and another-PC behavior remain unverified. No game configuration or save files were written during this work.
- GitHub-hosted rolling workflow [39926597501](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/39926597501) passed tests, lint/format, compilation, installer build, packaged-install smoke, and provenance attestation. It published the v0.1.6 rolling manifest and versionless installer for commit `2864edc39c88ce7c4566e565408bb3c0854fcb7e`; SHA-256 `6bf5414ddfc7c06983e40befa38af108aefb94cd0fc63964b45a68b622551b50`.
- GitHub-hosted stable workflow [39926601286](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/39926601286) passed tests, lint/format, compilation, upgrade and install smoke checks, and provenance attestation. It published the v0.1.6 installer (120,155,294 bytes; SHA-256 `90274eab86d3daed7e07439e28bd0882ac24e657d1d99f5fd00e9f22e9f3f431`); the checksum sidecar matches GitHub's asset digest. [Stable release](https://github.com/LookImEcho-Rick/ZomboidSorter/releases/tag/v0.1.6).

## Rolling updater and versionless v0.1.5 release (2026-10-23)

- The app now displays v0.1.5 in its window title and header; the installer also carries version 0.1.5 in its metadata. Installer output and stable/rolling GitHub assets use the versionless name `ZomboidSorter-windows-setup.exe`.
- The Update button checks the published rolling package for a new commit, verifies the manifest, installer size, and SHA-256, then hands off to a Windows helper that waits for the app to exit, installs silently, and relaunches. Source-run development builds do not offer a packaged self-update.
- All 109 tests passed with one environment-only symlink skip; Ruff check/format, compileall, workflow YAML parsing, PowerShell parser checks, and `git diff --check` passed. The local Windows 11 installer compiled successfully as `ZomboidSorter-windows-setup.exe` (120,120,771 bytes; SHA-256 `acef06816b7637fc90cdc0538db94c2293c5ef710e508f1b84fc8ef0123c1ea2`) with CPython 3.14.7, PyInstaller 6.22.3, and Inno Setup 6.7.3.
- The temporary portable-install simulation used the local installer and update helper; the app relaunched as `ZomboidSorter v0.1.5` and closed cleanly. Separately, the updater module downloaded the published rolling installer (120,120,328 bytes), verified its manifest/checksum/Windows executable header, and correctly reported that build `1cbe22f1` was current.
- GitHub-hosted Windows 2022 rolling workflow [39920312458](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/39920312458) passed tests, lint/format, app/installer build, packaged-install smoke, and artifact attestation; it published the rolling prerelease from commit `1cbe22f1fcb4bf5690a44dc412612892a3959f28`.
- GitHub-hosted Windows 2022 stable release workflow [39920316030](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/39920316030) passed and published `ZomboidSorter-windows-setup.exe` for v0.1.5 (120,197,462 bytes, SHA-256 `5c39240540b826dd4e27fd8cb363d3425ec746ef0af798cb2556f6f7349ba382`). The checksum sidecar matches GitHub's asset digest. [Stable release](https://github.com/LookImEcho-Rick/ZomboidSorter/releases/tag/v0.1.5).
- The local helper simulation and a real rolling download were validated separately; the app button was not run through a full published-update cycle, and update-data preservation, Windows 10, and another PC remain unverified. No Project Zomboid config, saves, installed mods, or Workshop subscriptions were changed.

## Build-aware overlap triage and packaged launch checks (2026-10-23)

- File-overlap scans now use the selected metadata target and, by default, only Mod IDs in the staged active order. A checkbox includes all discovered mods; selecting **All candidates** includes every metadata version. The report states its scope. It retains every grouped path within existing scan limits, searches the full result set, and loads table rows in pages of 250.
- Added a pull-request/manual Windows installer smoke workflow that builds a fresh installer and verifies launch plus clean close in standard and portable modes. The tagged-release smoke test now performs the same launch checks in addition to its existing upgrade/reinstall, mode-refusal, uninstall, and data-preservation checks.
- Validation: all 8 file-overlap fixture tests and all 32 UI tests passed; Ruff checks and formatting, PowerShell parser validation, and `git diff --check` passed. GitHub-hosted workflow execution is pending a push to a branch. Steam reports the installed `legacy41` branch as Build 41.78.21. A read-only scan found 62 entries, 39 Build 41 root metadata candidates, and 12,058 media files; the all-discovered overlap pass found 1,389 differing comparisons across 344 paths. The 23 staged active IDs produced 3 root candidates but no indexable media files, so the active-scope result is inconclusive for runtime conflicts. No game launch, save edit, or Workshop write was performed; the prior Build 42.21 directory was copied to `C:\Games\ProjectZomboid-Build42.21-backup`.

## Repeatable installer smoke workflow (2026-10-23)

- Added a GitHub-hosted Windows smoke test for standard and portable installs, upgrading from the previous stable installer when available, refusing silent cross-mode changes, uninstalling, and checking seeded Mod Pack/settings sentinels survive. The script is restricted to GitHub Actions and retains install logs when it fails.
- The release workflow now downloads and checksum-verifies the previous release installer before using it, then runs the smoke test before publishing. First-release and rerun cases reinstall the current installer when there is no earlier stable version.
- Validation: PowerShell parser validation and `git diff --check` passed. The hosted workflow and installer were not executed in this task; no local installer, app settings, game config, or game files were touched. This automated check does not cover the GUI, Workshop browser, updater handoff, interactive cross-mode prompts, Windows 10, or another PC.

## Grouped file-overlap triage (2026-10-23)

- The opt-in overlap report now counts differing and unverified comparisons separately and groups them by shared relative path. A non-modal table shows the paths with the most pairs, Mod IDs, and status counts; search matches paths or Mod IDs, and a status filter narrows groups to different-content or unverified findings. Selecting a path shows bounded source examples.
- Validation: all five file-overlap fixture tests and all 30 UI tests passed; Ruff checks and formatting passed. Results remain simulated on fixtures, and overlaps still do not establish a runtime conflict.

## GitHub release provenance (2026-10-23)

- The Windows release workflow now creates GitHub artifact attestations for the installer and checksum using GitHub's OIDC-backed signing flow. The README and packaging guide include a GitHub CLI command that verifies the downloaded installer against the repository and release workflow.
- The installer remains Authenticode-unsigned, so SmartScreen may still warn. The workflow change has not yet run on GitHub; the already published v0.1.4 predates the attestation step and has no attestation from it.
- Validation: workflow permissions and action syntax were checked against GitHub's current artifact-attestation documentation. Attestation creation and consumer verification await a future tagged workflow run.

## Version 0.1.4 release preparation (2026-10-23)

- Added standard and portable installer modes with optional shortcuts, retained setup type on upgrades, and warned/refused when changing data modes interactively/silently. Portable mode stores settings and Mod Packs next to the app; uninstall and mode changes preserve the old data location.
- Removed Authenticode enforcement from in-app updates. The updater checks the version-matched release asset's advertised size, SHA-256 sidecar, and Windows executable header before launching the installer. Split `MainWindow` into focused layout, discovery, library, staging, profile, configuration, details, diagnostics, update, worker, widget, and lifecycle modules.
- The installer is intentionally unsigned. The README includes a cropped SmartScreen warning, explains the unknown-publisher message, and describes checking the official release and checksum before choosing **Run anyway**.
- Local installer: `ZomboidSorter-0.1.4-windows-setup.exe`, 120,105,547 bytes, SHA-256 `f9539c6b30cc3ed3705cdafd4d4edb47412134edb84dcd7fe282da7b1fe786e8`; built with CPython 3.14.7, PyInstaller 6.22.3, and Inno Setup 6.7.3. The sidecar checksum matches.
- Validation: the local PyInstaller bundle and Inno Setup installer compiled; Ruff check/format, compileall, and `git diff --check` passed. GitHub Actions run [39909889025](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/39909889025) passed hosted tests, lint, formatting, compilation, and the Windows app/installer builds.
- Published installer: `ZomboidSorter-0.1.4-windows-setup.exe`, 120,167,672 bytes, SHA-256 `53fd2d4e6c4fa80474f063165a2af05006d7bf1f16aafed7516357a9ef47f066`. The `.sha256` asset returned HTTP 200 and its digest matches GitHub's installer asset digest. [Release page](https://github.com/LookImEcho-Rick/ZomboidSorter/releases/tag/v0.1.4).
- The initial signing-gated run [39908628919](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/39908628919) stopped before publication. The unsigned release tag now points at commit `5f19b82`. The installed v0.1.4 GUI and interactive mode-switch prompt remain unverified.
- No game configuration, save files, Workshop subscriptions, or installed mod files were changed.

## Version 0.1.3 release preparation (2026-10-23)

- Added exact Build 42 metadata selection using the user-entered game version. The selected candidate drives mod names/details, active-list labels, dependency diagnostics, and sort proposals. Selection does not prove mod content compatibility or reproduce every game loader rule.
- Local Windows 11 installer: `ZomboidSorter-0.1.3-windows-setup.exe`, 120,145,953 bytes, SHA-256 `f2d68bddbe9da1092de26b02beedebdd3ecb00c4b9537a4e340b9b32e108fd60`; built with CPython 3.14.7, PyInstaller 6.22.3, and Inno Setup 6.7.3. No runtime dependencies, Qt modules, bundled assets, or license-delivery changes were made.
- Validation: 93 tests ran with one environment-only symlink skip; Ruff check/format, compileall, and `git diff --check` passed. An isolated direct installer upgrade from v0.1.2 to v0.1.3 and silent uninstall succeeded in a temporary directory. The actual app settings export and profile hashes stayed identical. The v0.1.3 app was not launched; Workshop loading and the updater-launched installer path remain unverified.
- GitHub Actions run [39904471238](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/39904471238) passed and published `ZomboidSorter-0.1.3-windows-setup.exe` (120,150,804 bytes, SHA-256 `6b62055b244b7503c1bb25e308ee5310d46a3f61bd076466e96f44b031d2ddf0`) and its checksum asset. The checksum matched GitHub's reported installer digest, and both assets returned HTTP 200. [Release page](https://github.com/LookImEcho-Rick/ZomboidSorter/releases/tag/v0.1.3).

## Build-aware metadata selection (2026-10-22)

- The exact-build selector now follows The Indie Stone's published examples: choose the newest numeric version folder at or below the entered game build. Build 41 uses root metadata; Build 42+ uses a compatible versioned candidate or shared `common/mod.info` when no compatible versioned metadata exists. If version folders change the Mod ID within one physical mod entry, only the selected ID is treated as the active metadata entry.
- The selected candidate drives details and poster previews, dependency diagnostics, active/inactive labels, and sort proposals. The Build 42 target version is user-entered and saved in settings because the app has no reliable installed-game version detector. File-overlap analysis remains candidate-wide. Selection does not validate content compatibility or reproduce every loader rule.
- Validation: focused fixture tests cover numeric version ordering, shared metadata fallback, versioned Mod ID changes, dependency findings, sorting constraints, and UI selection. These checks are fixture-based; actual candidate loading was not verified in-game.

## Cancellable discovery scans and shutdown (2026-10-22)

- Discovery now reports scan stages and periodic local-folder / Workshop-item counts. The status bar offers **Cancel scan**; cancellation is checked while enumerating directories, reading metadata candidates, and building discovery diagnostics, and keeps the previous scan results intact.
- Closing while background workers are active now requests interruption and continues closing from worker-finished signals instead of blocking the UI with unbounded `wait()` calls. Shutdown is asynchronous; a filesystem call or in-flight network request can finish before its worker stops.
- Validation: all 11 discovery tests and the two focused UI cancellation/shutdown tests passed; Ruff check and format passed for the changed Python files. The full suite was not run.

## Discovery hardening (2026-10-22)

- `mod.info` reads are capped at 1 MiB, including a bounded read if a file changes after its initial size check. Files too large to read, unreadable files, and files invalid as both UTF-8 and Windows-1252 remain visible with path-specific metadata diagnostics; one failure no longer aborts the scan.
- Discovery skips symbolic links and Windows junctions at configured roots, Workshop items, mod entry folders, version/shared metadata folders, and candidate `mod.info` files. Skips appear as path-specific scan diagnostics.
- Added focused scanner tests for oversized metadata, unreadable files, invalid UTF-8/Windows-1252 bytes, and skipped linked metadata. The linked-path case simulates link detection because this Windows environment does not permit creating symlinks.

## Focused UI regression checks (2026-10-22)

- Added checks that filtered active-list drops preserve the existing order, text and issue filters disable reorder controls, Build 41/42 previews select the observed root/shared/versioned metadata layouts, and Workshop BBCode renders while raw HTML and unsafe URL attributes stay escaped.
- Validation: all four `test_mod_details.py` tests and the focused filtered-workspace UI test passed. Ruff check/format and `git diff --check` passed for the changed test files.

## Real-game global-list acceptance (2026-10-22)

- Applied a temporary marker through the installed ZomboidSorter UI to the local Build 42.21.0 global list (`C:\Users\echos\Zomboid\mods\default.txt`). The game log reported `version=42.21.0` and `loading MoreDescriptionForTraits42`, confirming the game read the applied global list at startup.
- Project Zomboid reached its photosensitivity warning screen. Closed it without opening a save. Removed the marker through the app and restored the original global list byte-for-byte: 747 bytes, 23 Mod IDs, CRLF line endings, no UTF-8 BOM, SHA-256 `d00c9460bf9382b7f3086a69f47155ce17493b8315f8655552f2f39eb3215e40`. Timestamped backups from both applies remain in place.
- This verifies global-list apply, launch handoff, and startup loading on this local installation. Gameplay behavior and loading a save were not tested; Windows 10 remains unverified.

## Python 3.14 requirement (2026-10-22)

- Set Python 3.14 as the minimum supported version in package metadata and aligned the release workflow, development instructions, architecture notes, and project guidance with it. Existing local Python 3.14.7 build and test results are recorded below; the updated hosted release workflow has not run yet.

## Public-source preparation and Windows installer (2026-10-22)

- Chose GPL-3.0-or-later for original code. Created an independent wordmark/icon, fixture screenshots, end-user README, pinned Windows packaging constraints, Inno Setup script, checksum builder, and tagged-release GitHub Actions workflow. The workflow blocks binary publication until a documented Qt/WebEngine redistribution review is committed as `packaging/RELEASE_READY`.
- Removed the unused generated `pysidedeploy.spec`, which contained an absolute developer-machine path. Generated caches, build output, virtual environments, and `.codex-checkpoints/` are Git-ignored. Useful fixtures, tests, and research remain.
- Windows 11 local checks: 69 unit tests passed with one symlink-environment skip; Ruff check/format and compileall passed. PyInstaller 6.22.3 on Python 3.14.7 built the onedir app; Inno Setup 6.7.3 compiled a 151,796,348-byte installer and SHA-256 checksum. A silent install to a temporary path returned 0, and its GUI process stayed alive for five seconds. An installer-only 0.1.0→0.1.1 upgrade simulation preserved an isolated Mod Pack file byte-for-byte; silent uninstall returned 0, removed the app executable, and left that Mod Pack file intact. This was not an application-code upgrade.
- A public GitHub repository was created at `LookImEcho-Rick/ZomboidSorter`. No installer has been attached to Releases. At this point, the Qt/WebEngine license-text, notice, and source-delivery review, isolated installer checks, Windows 10 test, and real-game write/launch validation remained open. The app's global-list write tests used fixtures only; later results are recorded below.

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
- Validation: 16 focused UI tests and the full 65-test suite passed (one environment symlink skip). Ruff check and format passed for source, tests, and the native capture helper. At this stage, the UI had not been verified against a live game installation or a packaged installation.

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

- **Initial research/foundation:** Python 3.11+ and PySide6, Windows first, modular discovery/game I/O/profile/diagnostic/sorting services. RimSort source was inspected for architecture and workflow; no code or assets were copied. See `docs/research/`.
- **Discovery:** Steam/game path detection, local and Workshop scanning, Build 41 root and Build 42 common/version candidates, multiple Mod IDs per Workshop item, duplicate-ID reporting, defensive metadata parsing, search/details/diagnostics. Repeated `description=` and documented repeatable `poster=` values are preserved.
- **Mod management:** staged global `default.txt` list, ordered enable/disable and move/drag actions, maps preservation, explicit apply confirmation, timestamp backup, atomic write/readback, and concurrent-change checks. No save-list or server-settings actions are part of the current launcher.
- **Profiles:** app-owned JSON profiles with stable order, unavailable Mod IDs and Workshop IDs, v1→v2 schema compatibility, import/export, overwrite backups, reversible deletion, and restore.
- **Dependencies/sorting:** candidate-specific `require`, `incompatible`, `loadModAfter`, and `loadModBefore` analysis. Explicit before/after rules are editable and persisted in app settings. The deterministic proposal retains current order as a tie-breaker and stops on cycles; it is not presented as a runtime guarantee.
- **Workshop:** read-only public collection/item metadata, URL links, PZ App ID filtering, installed/missing resolution, and profile creation. Collection import can open a selected missing item's public Workshop page. No subscription/download/update side effects.
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

- The packaged app has been smoke-tested in isolated locations on the development machine. Windows 10 coverage and upgrade from a previous version of the optimized installer remain unverified. Real-game global-list apply/launch acceptance was completed later, as recorded above.
- Workshop API integration is response-mock tested, not live-tested. Subscription, update, and download flows are absent.
- Exact Build 42 runtime selection/precedence, duplicate-Mod-ID winner behavior, and resource-specific file override/merge semantics remain unresolved. The UI labels candidate overlaps as potential.
- Save-list and server-settings features described in earlier progress entries were retired from the current global-list-only app. The original code is GPL-3.0-or-later. The technical Qt/WebEngine notice and source review is recorded in `packaging/RELEASE_READY`; the maintainer remains responsible for fulfilling the written source offer.

## Public release preparation (2026-10-22)

- Created and pushed the public repository at `LookImEcho-Rick/ZomboidSorter`. The project has a GPL-3.0-or-later license, fixture-labeled README screenshots, the ZomboidSorter wordmark/icon, an Inno Setup per-user installer, and a tagged-release Actions workflow. The workflow requires `packaging/RELEASE_READY`, which records the Qt/WebEngine notice and source review. At this stage, isolated installer and real-game checks were still pending; later results are recorded below.
- Added the maintainer's written source offer for exact bundled Qt/PySide6/WebEngine sources. The installer displays it before installation and includes it with GPL/LGPL, CPython, and PyInstaller license texts. GitHub Issues are the request channel.
- Completed the pinned Qt redistribution inventory: offline appendices include all 138 Qt 6.12.0 attribution pages and 125 unique Qt WebEngine 6.140.0/Chromium 140 license pages, including their copyright lines and license texts. Added LGPL-2.1/3.0 and FDL-1.3 texts, runtime OpenSSL Apache-2.0, build-copied CPython/PyInstaller/Inno license texts, and a per-build component/version manifest. Added official source archive locations and recorded the source-offer commitment in `packaging/RELEASE_READY`.
- The original Windows PyInstaller build excluded parallel Qt WebEngine debug resource copies after checking their release counterparts. It retained the full QML tree pending a dependency-backed trim; the Qt bundle minimization below supersedes that bundle.
- Validation: 69 unit tests passed with one environment symlink skip; Ruff check/format and compileall passed. The trimmed-resource WebEngine smoke loaded a local HTML data page successfully from the development Python environment using the packaged resource path. The Inno installer compiled, installed to an isolated directory, launched for five seconds, and silently uninstalled; the installed executable was removed. Earlier installer-only 0.1.0→0.1.1 upgrade testing preserved an isolated Mod Pack fixture byte-for-byte, but the rebuilt optimized 0.1.0 installer was not separately upgrade-tested.
- The latest local installer is `dist/installer/ZomboidSorter-0.1.0-windows-setup.exe` with SHA-256 `6df0be0963b9008db427f1607b31e3226dc1011f59380f262f8dbb5b1ea5a905` (142,621,063 bytes). It was built with CPython 3.14.7, PyInstaller 6.22.3, OpenSSL 3.5.7, and Inno Setup 6.7.3 on Windows 11; at that point the release workflow was configured for CPython 3.11 and Inno Setup 6.7.1. No GitHub Release exists yet.

## Isolated installer checks (2026-10-22)

- A fresh temporary Python 3.14.7 environment installed `.[dev,windows]` under the pinned Windows constraints. All 69 unit tests passed with one environment-only symlink skip; Ruff check, Ruff format check, and compileall passed.
- Rebuilt the 0.1.0 onedir app and Inno installer. An isolated per-user install into a temporary directory launched and stayed open for eight seconds. A same-version reinstall preserved a temporary Mod Pack and the app settings registry key; silent uninstall removed the executable and preserved both. The temporary registry changes were restored to their original values, and the test install was removed.
- The app's `MainWindow` created its embedded `QWebEngineView` in the fresh Qt environment and loaded the live Project Zomboid Steam Workshop page (`The Steam Workshop for Project Zomboid`, document ready state `complete`).
- Only Python 3.14.7 is installed; the release workflow's Python 3.11 build (the configured version at that point) was not verified here. The remote had no tags or GitHub Releases at the time, so this pass could not test an upgrade from a previous installer; the earlier installer-only 0.1.0→0.1.1 simulation remains the only upgrade evidence.

## Qt bundle minimization (2026-10-22)

- Added project-local PyInstaller hooks to omit QML assets/debug tooling and unused touch/virtual-keyboard plugins. This app has no QML views; Qt WebEngine's required Core, Gui, Widgets, Qml, Quick, and WebEngine runtime dependencies remain.
- The clean PyInstaller build now contains 19 Qt6 runtime DLLs, no QML directory, and no generic-touch, platform-input-context, or QML-tooling plugins. The bundle-scoped Qt appendix contains 57 pages (4,047 lines), selected from the 138-page source inventory; the full 125-page WebEngine/Chromium appendix remains (11,518 lines). Full pinned source appendices are stored as gzip files and expanded into readable installer notices at build time.
- The notice generator checks the expected upstream page counts, inventories the actual runtime DLLs in `licenses/BUILD_COMPONENTS.txt`, and refuses to proceed if excluded QML/plugin groups reappear. The installer uses the generated notice set; readable HTML pages are staged under ignored `build/installer_payload/licenses/`, outside the app bundle.
- The tracked source now stores the 27,018-line upstream HTML appendices as two gzip files (about 295 KB combined). Only the installer payload expands readable notices; `dist/ZomboidSorter/` contains no generated HTML attribution files.
- PyInstaller clean build, notice generation, reduced-bundle app/WebEngine smoke, and installer compile passed. The 119,892,820-byte installer (`SHA-256 3ea0ea57e6a5eac9ce32b8f5dd17e49e8d783bf2b2f523f699e7e2aff0473265`) silently installed to a fresh temporary directory, launched under a system-only `PATH`, opened the Workshop tab with its bundled WebEngine process, and silently uninstalled. The preexisting app settings registry values were restored exactly. These checks were performed on the build host.

## MainWindow Workshop browser extraction (2026-10-22)

- Moved the Steam Workshop tab controls, navigation, URL parsing, and lazy WebEngine lifecycle into `ui/workshop_browser.py` as `WorkshopBrowserPanel`. `MainWindow` now mounts the panel and opens its home page when the tab is first selected, reducing its Workshop-specific responsibilities while preserving lazy loading.
- Validation: the two focused panel tests and the existing fixture-based MainWindow tab-switch test passed. The full 76-test suite passed with one environment-only symlink skip; Ruff check, project-wide formatting, and compileall passed. No separate live-page verification was run for this refactor.

## MainWindow active-configuration workflow extraction (2026-10-22)

- Moved global-list loading, selected-target matching, supported-target checks, stale-snapshot detection, and the guarded apply call into `configuration.py`. `MainWindow` keeps confirmation dialogs, visible status, and widget updates; `gameio/active_mods.py` still owns parsing and safe disk writes. Updated the existing apply-failure test to patch the new service boundary.
- Validation: Ruff check/format and Python compile checks passed. Automated tests were not run for this refactor. No Project Zomboid configuration or save files were written.

## In-app update checker (2026-10-22)

- Set the source version to 0.1.2 and added a **Check for Updates** button. It checks the latest stable GitHub Release off the UI thread, compares numeric versions, and only accepts the repository's version-matched Windows installer and checksum assets. After confirmation it downloads the installer, checks its advertised size, SHA-256 sidecar, and Windows executable header, then opens the regular per-user Inno Setup installer and exits the app.
- Validation: the 82-test suite passed with one environment-only symlink skip; Ruff check, Ruff format check, and `git diff --check` passed. GitHub Actions run [39898572140](https://github.com/LookImEcho-Rick/ZomboidSorter/actions/runs/39898572140) passed and published both release assets. The live updater detected v0.1.2, downloaded the 120,090,071-byte installer, verified its release SHA-256, and removed the temporary download.
- Release limitation: an isolated install/upgrade/uninstall smoke test and settings/profile preservation through the updater launch path have not been run. Updating opens the standard installer wizard rather than silently replacing files. Release package evidence is recorded in `packaging/RELEASE_READY`.

## Installer modes, shortcut choices, and unsigned release policy (2026-10-23)

- Added a standard/portable setup type to the Inno installer. Portable mode stores Mod Packs under `data/profiles` and Qt settings in `data/settings.ini` beside the application. The installer offers optional Start menu and desktop shortcuts for standard installs.
- The setup type selection is part of the installer; no separate portable ZIP is produced. The release workflow publishes an unsigned installer and its SHA-256 sidecar. In-app updates validate the release asset's size, checksum, and executable header.
- SmartScreen can show **Unknown publisher** for the unsigned installer. The README explains why this prompt appears and tells users to proceed only with the official release and a matching checksum.
- Validation at this milestone: 95 tests passed with the existing symlink-only skip; Ruff check/format, compileall, and `git diff --check` passed. The PyInstaller Windows bundle built and Inno Setup compiled. A silent `/TYPE=portable` install installed the marker and executable and then uninstalled. The Qt UI test verified that closing the app writes `data/settings.ini` in portable mode. A visible launch of the packaged executable and cross-PC SmartScreen behavior were not verified.

## Build detection, save/server targets, and Workshop recovery (2026-10-23)

- Added **Use Installed** detection: Build 41 comes from Steam's `legacy41` branch, Build 42 from the installed `Core.class` marker, and an exact version is read from `Zomboid/version.txt` only when its timestamp is at least as new as Steam's `LastUpdated` value and its family matches. The version remains editable. The real local install detected as Build 41 with no current exact version because its saved version file predates the Steam install update; stale Build 42 data was not reused.
- Added **Apply Elsewhere…** with separate save and server actions. Save apply accepts only one immediate `<Saves>/<mode>/<save>/mods.txt`, preserves existing maps and encoding, creates explicit lists for saves inheriting the global list, and confirms before writing. Server apply updates only the separate `Mods` and `WorkshopItems` keys after resolving staged IDs against one unique scan entry per Mod ID. Both adapters back up existing files, reject linked/malformed/stale targets, replace atomically, and verify readback.
- Workshop collection import now opens the selected missing/unavailable PZ item page directly. Foreign Steam app rows are disabled, and opening a page never subscribes or downloads.
- Build 42.21 source inspection confirms its Mod Selector validator requires declared dependencies to appear before dependents. A new fixture checks that invariant. The isolated game runtime probe stopped during Lua initialization because the preserved backup could not load `media/lua/shared/a_requires.lua`; it never loaded the test mods. Runtime ordering remains unverified.
- Validation: all 147 unit tests passed with two symlink-only skips; Ruff check, Ruff formatting check, `git diff --check`, and compileall passed. UI apply flows wrote only disposable save/server fixtures. No live save or server settings were modified. Release signing/package changes were outside this work.

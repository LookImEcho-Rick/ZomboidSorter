# Architecture decisions

## Technology

- **Python 3.14+ and PySide6/Qt 6.** RimSort already uses this UI stack and layered Python structure; it gives a native desktop UI and avoids introducing a second implementation language. The `pyproject.toml` sets the dependency boundary.
- **Windows first, portable core.** Use `pathlib` and isolated platform path discovery so filesystem parsing and domain logic remain portable. Keep Windows/Steam detection behind a service.
- **No runtime database for the first milestone.** Discovery can operate on filesystem paths and in-memory records. Add persistence only when a milestone needs it.

The project's original code uses GPL-3.0-or-later. PySide6 has LGPLv3/GPLv3 and commercial licensing options; the exact Qt/WebEngine redistribution materials remain a binary release gate. RimSort is GPL-3.0: we are reusing its documented ideas and independently implementing behavior, not copying its source. If source code is later copied or adapted, revisit the source attribution and license compatibility before distribution.

## Boundaries

- **Domain:** `WorkshopItem` (numeric Workshop identity and installation path) contains zero or more **ModEntry** records (one per `mod.info`, with its own Mod ID, name, version folder, and source). Keep physical installations distinct so duplicate Mod IDs can be diagnosed instead of silently merged.
- **Discovery:** read-only path detection, directory traversal, and metadata parsing. A scanner returns records and diagnostics; it never writes to the game.
- **Game I/O:** keep Build 41, Build 42, client/save, and server configuration surfaces separate. `gameio/active_mods.py` supports only the verified global `Zomboid/mods/default.txt` version-1 shape; it refuses unknown syntax, save paths, symlink targets, duplicate identifiers, and concurrent changes. It backs up before an atomic replacement and validates the result. Save-specific and server config adapters are not implemented.
- **Application/UI:** thin PySide6 views call services and display state. Keep filesystem and parsing logic outside widgets. Present warnings as evidence-backed diagnostics.
- **Profiles:** app-owned JSON profiles (shown as Mod Packs in the UI) live under the platform config directory, separate from game files. **Apply** from the pack manager is an explicit action that writes the selected ordered IDs to the verified global list using its backup, atomic replacement, and validation safeguards. Manual list edits remain staged until the user applies them.
- **Dependencies/sorting:** parse declared constraints from each `mod.info` candidate. Apply an order edge only when candidate declarations agree. Explicit user before/after rules are stored in app settings and combined with metadata constraints for proposals. The orderer returns a deterministic proposal, uses the current list as its tie-breaker, and refuses to force a cyclic result; it does not claim full Java loader equivalence.
- **Workshop:** use public read-only Steam Remote Storage endpoints for collection and item metadata. Collection profiles retain both Mod IDs and numeric Workshop IDs. No login, subscription, download, or update action is performed.
- **Advanced diagnostics:** overlap checks walk only candidate `media/` trees, skip symlinks, cap file/pair/hash work, and compare shared relative paths. Console parsing is opt-in, size-limited, and recognizes only specific high-signal signatures. Both return evidence rather than inferred runtime causality.
- **UI/persistence:** PySide6 views call service modules; scans and expensive diagnostics run in `QThread`. `QSettings` stores window geometry and selected paths. Profiles are stored under the app config directory, separate from game data.
- **Packaging:** PyInstaller produces a Windows onedir app, and Inno Setup wraps its complete output folder in a per-user installer. Upgrades and uninstall keep app-owned profiles/settings outside the install directory. A clean-machine pass and Qt/WebEngine redistribution review remain binary release gates.

## Initial source layout

`src/zomboid_mod_manager/` is the package root. Keep the existing `discovery/`, `gameio/`, `diagnostics/`, `sorting/`, and `ui/` modules focused, with realistic fixtures under `tests/`. The embedded Steam Workshop tab is isolated in `ui/workshop_browser.py`; it owns its controls, navigation, and lazy WebEngine view. Avoid adding abstraction layers before a concrete milestone requires them.

The discovery records preserve source path/type, Workshop item ID when available, Mod ID, every observed B42 version candidate, raw metadata, and parse warnings. No active B42 candidate is selected yet. A Workshop item is not a mod entry: one item can provide several Mod IDs.

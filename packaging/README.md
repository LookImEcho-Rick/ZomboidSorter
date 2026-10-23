# Windows installer and release

The Windows build has two stages: PyInstaller creates a complete `dist/ZomboidSorter/` onedir application, then Inno Setup wraps that folder in a per-user installer. Keep the full onedir tree together. The installer has a stable AppId, Start menu entries, and an uninstaller. Upgrades use the same app directory. Neither upgrade nor uninstall removes `%APPDATA%\ProjectZomboidModManager\profiles`, Qt settings in HKCU, or game-list backups.

## Local build

Use Windows 11/10 x64, Python 3.11, and Inno Setup 6. The CI build uses the versions in `constraints-windows.txt` and Inno Setup 6.7.1. Python 3.11 is the release build interpreter even if newer versions work locally.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,windows]" -c packaging\constraints-windows.txt
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check src tests
.\packaging\build_installer.ps1
```

This produces `dist/installer/ZomboidSorter-<version>-windows-setup.exe` and a matching `.sha256` file. `build_windows.ps1` limits DLL search paths during PyInstaller collection, excludes the unused QML asset/plugin tree (this app has no QML views), and removes only the parallel Qt WebEngine **debug** resource copies after checking that the release resource files exist. The remaining Qt and WebEngine runtime files must stay in `_internal`. The installer and Qt window icons use project assets under `assets/`. The build copies the actual bundled interpreter's CPython license, PyInstaller license, and version manifest into the ignored `build/installer_payload/licenses/` staging directory. It generates the Qt attribution appendix from the actual bundled Qt DLL inventory; the complete WebEngine/Chromium appendix remains because QtWebEngineCore is shipped. Expanded HTML notices are staged for the installer only; the PyInstaller app folder in `dist/ZomboidSorter/` stays free of generated license pages. The installer also includes the FDL and applicable license texts, the Inno Setup license, and the written source offer.

## Release

1. Review the source and assets for private data and rights issues. Check the exact PySide6/Qt/WebEngine package versions, their third-party notices, and source availability. Record the reviewer, date, exact bundle version, license/source delivery method, and evidence in `packaging/RELEASE_READY`. The workflow intentionally refuses to publish without it.
2. Run installer install, launch, same-version reinstall, upgrade from the previous version, and uninstall on a clean Windows VM/account. Check that the embedded Workshop page loads and user settings/Mod Packs remain after upgrade and uninstall. Test a real Project Zomboid global config only with an explicit safe test plan.
3. Set `project.version` in `pyproject.toml`, update `src/zomboid_mod_manager/__init__.py`, and commit. Push the commit and a matching `v<version>` tag to the GitHub repository. The `release-windows.yml` workflow checks that tag and version agree, runs tests/lint/format, builds the installer and checksum, and creates or updates the tagged GitHub Release with both assets.
4. Verify both assets are downloadable from the Release page and that the checksum matches the installer.

The workflow needs repository Actions enabled and `contents: write` permission for `GITHUB_TOKEN`. The public repository is [LookImEcho-Rick/ZomboidSorter](https://github.com/LookImEcho-Rick/ZomboidSorter). The legal review record is in `packaging/RELEASE_READY`.

## Third-party redistribution review

The app uses PySide6 6.12.0 and PySide6 WebEngine/PDF 6.12.0.140 (Qt WebEngine 6.140.0 with Chromium 140). Qt for Python is available under LGPL-3.0/GPL-3.0 or a commercial license. Qt WebEngine incorporates Chromium under additional terms, including LGPL-2.1. The install directory permits replacement of compatible dynamic libraries. The installer includes attribution pages for bundled Qt modules, the complete WebEngine/Chromium attribution, GPL/LGPL and runtime/tool license texts, and a written source offer with GitHub Issues as the request channel.

The full pinned source appendices are stored as gzip-compressed files in `licenses/`; the build expands and filters Qt 6.12.0 pages against the runtime DLL inventory. It keeps the complete Qt WebEngine/Chromium inventory. Exact Qt, PySide6, and WebEngine source locations are in `SOURCE_OFFER.md`. Recheck the notice inventory and source links when the Qt pins or bundled Qt modules change. Qt says an upstream link alone may be insufficient, so fulfill requests with the exact corresponding source archive.

Primary references: [Qt for Python licensing](https://doc.qt.io/qtforpython-6/), [Qt LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations), [Qt WebEngine licensing](https://doc.qt.io/qt-6/qtwebengine-licensing.html), and [Inno Setup AppId/upgrades](https://jrsoftware.org/ishelp/topic_setup_appid.htm). The ZomboidSorter logo is a custom project mark inspired by Project Zomboid's visual style; official game-logo files and RimSort assets are not bundled. The README identifies the app as an unaffiliated fan tool.

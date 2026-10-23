# Windows installer and release

The Windows build creates a complete `dist/ZomboidSorter/` onedir application, then Inno Setup wraps that folder in a per-user installer. Keep the full onedir tree together. Setup offers standard and portable data modes. Standard mode keeps app data in `%APPDATA%` and HKCU; portable mode keeps it in `data/` beside the app and requires a writable destination folder. The installer remembers the previous mode on upgrades. Changing modes requires an interactive install, warns that the old data remains in place, and begins using the selected mode's separate data folder; silent cross-mode upgrades are refused. Mod Packs can be exported/imported between modes, while settings are not migrated. The installer offers Start menu and desktop shortcuts as optional tasks. Upgrades and uninstall do not delete user data or game-list backups.

## Local build

Use Windows 11/10 x64, Python 3.14+, and Inno Setup 6. The release workflow builds with CPython 3.14 and uses the package versions in `constraints-windows.txt` with Inno Setup 6.7.1.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,windows]" -c packaging\constraints-windows.txt
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check src tests
.\packaging\build_installer.ps1
```

This produces `dist/installer/ZomboidSorter-<version>-windows-setup.exe` and a matching `.sha256` file. The portable choice is included in this installer; there is no separate portable ZIP. `build_windows.ps1` limits DLL search paths during PyInstaller collection, excludes the unused QML asset/plugin tree (this app has no QML views), and removes only the parallel Qt WebEngine **debug** resource copies after checking that the release resource files exist. The remaining Qt and WebEngine runtime files must stay in `_internal`. The installer and Qt window icons use project assets under `assets/`. The build copies the actual bundled interpreter's CPython license, PyInstaller license, and version manifest into the ignored `build/installer_payload/licenses/` staging directory. It generates the Qt attribution appendix from the actual bundled Qt DLL inventory; the complete WebEngine/Chromium appendix remains because QtWebEngineCore is shipped. Expanded HTML notices are staged for the installer only; the PyInstaller app folder in `dist/ZomboidSorter/` stays free of generated license pages. The installer also includes the FDL and applicable license texts, the Inno Setup license, and the written source offer.

## Release

1. Review the source and assets for private data and rights issues. Check the exact PySide6/Qt/WebEngine package versions, their third-party notices, and source availability. Record the reviewer, date, exact bundle version, license/source delivery method, and evidence in `packaging/RELEASE_READY`. The workflow intentionally refuses to publish without it.
2. Run fresh standard and portable installs, same-mode upgrades, both cross-mode attempts, launch, and uninstall in isolated Windows install/accounts. Check that the embedded Workshop page loads and user settings/Mod Packs remain after same-mode upgrades and uninstall. Verify a cross-mode prompt appears interactively and a silent cross-mode upgrade is refused. Test a real Project Zomboid global config only with an explicit safe test plan.
3. Set `project.version` in `pyproject.toml`, update `src/zomboid_mod_manager/__init__.py`, and commit. Push the commit and a matching `v<version>` tag to the GitHub repository. The workflow checks that tag and version agree, runs tests/lint/format, builds the installer, and creates or updates the tagged GitHub Release with the installer and checksum.
4. Verify the release asset and checksum. ZomboidSorter installers are unsigned, so Windows SmartScreen may say **Unknown publisher** or warn that Windows protected your PC. The README explains how to verify the official download and continue. A checksum match helps detect corruption or an incomplete download; only download installers from the official [Releases page](https://github.com/LookImEcho-Rick/ZomboidSorter/releases).

The workflow needs repository Actions enabled, a committed `packaging/RELEASE_READY`, and `contents: write` permission for `GITHUB_TOKEN`. The public repository is [LookImEcho-Rick/ZomboidSorter](https://github.com/LookImEcho-Rick/ZomboidSorter). The technical license review record is in `packaging/RELEASE_READY`.

## Third-party redistribution review

The app uses PySide6 6.12.0 and PySide6 WebEngine/PDF 6.12.0.140 (Qt WebEngine 6.140.0 with Chromium 140). Qt for Python is available under LGPL-3.0/GPL-3.0 or a commercial license. Qt WebEngine incorporates Chromium under additional terms, including LGPL-2.1. The install directory permits replacement of compatible dynamic libraries. The installer includes attribution pages for bundled Qt modules, the complete WebEngine/Chromium attribution, GPL/LGPL and runtime/tool license texts, and a written source offer with GitHub Issues as the request channel.

The full pinned source appendices are stored as gzip-compressed files in `licenses/`; the build expands and filters Qt 6.12.0 pages against the runtime DLL inventory. It keeps the complete Qt WebEngine/Chromium inventory. Exact Qt, PySide6, and WebEngine source locations are in `SOURCE_OFFER.md`. Recheck the notice inventory and source links when the Qt pins or bundled Qt modules change. Qt says an upstream link alone may be insufficient, so fulfill requests with the exact corresponding source archive.

Primary references: [Qt for Python licensing](https://doc.qt.io/qtforpython-6/), [Qt LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations), [Qt WebEngine licensing](https://doc.qt.io/qt-6/qtwebengine-licensing.html), and [Inno Setup AppId/upgrades](https://jrsoftware.org/ishelp/topic_setup_appid.htm). The ZomboidSorter logo is a custom project mark inspired by Project Zomboid's visual style; official game-logo files and RimSort assets are not bundled. The README identifies the app as an unaffiliated fan tool.

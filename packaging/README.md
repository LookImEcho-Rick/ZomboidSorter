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

This produces `dist/installer/ZomboidSorter-<version>-windows-setup.exe` and a matching `.sha256` file. `build_windows.ps1` limits DLL search paths during PyInstaller collection. Its bundled Qt and WebEngine plugins/resources must be kept in `_internal`. The installer and Qt window icons use project assets under `assets/`.

## Release

1. Review the source and assets for private data and rights issues. Check the exact PySide6/Qt/WebEngine package versions, their third-party notices, and source availability. See the obligations below. Once the redistribution requirements are met, commit a `packaging/RELEASE_READY` file recording the reviewer, date, exact bundle version, license/source delivery method, and evidence. The workflow intentionally refuses to publish without it.
2. Run installer install, launch, same-version reinstall, upgrade from the previous version, and uninstall on a clean Windows VM/account. Check that the embedded Workshop page loads and user settings/Mod Packs remain after upgrade and uninstall. Test a real Project Zomboid global config only with an explicit safe test plan.
3. Set `project.version` in `pyproject.toml`, update `src/zomboid_mod_manager/__init__.py`, and commit. Push the commit and a matching `v<version>` tag to the GitHub repository. The `release-windows.yml` workflow checks that tag and version agree, runs tests/lint/format, builds the installer and checksum, and creates or updates the tagged GitHub Release with both assets.
4. Verify both assets are downloadable from the Release page and that the checksum matches the installer.

The workflow needs repository Actions enabled and `contents: write` permission for `GITHUB_TOKEN`. The public repository is [LookImEcho-Rick/ZomboidSorter](https://github.com/LookImEcho-Rick/ZomboidSorter); the release job must remain gated until the redistribution review is complete.

## Third-party redistribution review

The app uses PySide6 6.12.0, dynamically loaded Qt libraries, and Qt WebEngine. Qt for Python is available under LGPL-3.0/GPL-3.0 or a commercial license. Qt WebEngine incorporates Chromium under additional terms, including LGPL-2.1. The install directory permits replacement of compatible dynamic libraries. The installer includes `THIRD_PARTY_NOTICES.md` and the app's GPL text.

Before public distribution, include the complete applicable third-party license texts/notices for the **actual** bundle and make the corresponding Qt/PySide6/WebEngine source available, or provide a valid written source offer and fulfill it. Qt says an upstream link alone may be insufficient. The present notice inventory is not a completed legal compliance review; publication remains gated on this step.

Primary references: [Qt for Python licensing](https://doc.qt.io/qtforpython-6/), [Qt LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations), [Qt WebEngine licensing](https://doc.qt.io/qt-6/qtwebengine-licensing.html), and [Inno Setup AppId/upgrades](https://jrsoftware.org/ishelp/topic_setup_appid.htm). The source and logo assets are original to this project; RimSort and Project Zomboid art are not bundled.

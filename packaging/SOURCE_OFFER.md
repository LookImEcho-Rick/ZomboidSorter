# Written offer for bundled Qt source

ZomboidSorter installers contain unmodified, dynamically linked PySide6/Qt
libraries, including Qt WebEngine and components derived from Chromium. The
exact binary versions are recorded in `licenses/BUILD_COMPONENTS.txt` and the
Qt third-party notices distributed with each installer.

For at least three years after the last distribution of an installer containing
these libraries, the ZomboidSorter maintainer offers any recipient the complete
corresponding source code for the exact bundled versions, including relevant
build scripts, patches, and license notices, at no charge by electronic
download. This offer also covers LGPL components used by Qt WebEngine.

The corresponding source packages for the current pinned build are published
by Qt at these locations:

- PySide6 and Shiboken6 6.12.0: [Qt for Python 6.12.0 source archive](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz).
- Qt 6.12.0 framework modules: [Qt 6.12.0 source modules](https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/).
- Qt WebEngine 6.140.0 (Chromium 140), used by PySide6-WebEngine 6.12.0.140: [matching source archive](https://download.qt.io/online/qtsdkrepository/all_os/extensions/qtwebengine/6120/61400/src_doc_examples/extensions.qtwebengine.6120.61400.src/6.12.0-0-202609281005qtwebengine-everywhere-src-6.140.0.tar.xz).

These links are provided as a source location, not a substitute for the offer.
The maintainer will make a complete corresponding source archive available
electronically for the requested installer, including the matching Qt/PySide6
and WebEngine/Chromium versions, relevant patches/build scripts, and notices.

To request that archive, open a GitHub issue at
https://github.com/LookImEcho-Rick/ZomboidSorter/issues and name the installer
version or include its SHA-256 checksum. The maintainer will provide a download
link to the corresponding source archive. You do not need a GitHub account to
receive the source: if you cannot open an issue, have someone open one on your
behalf and specify a public delivery method. The offer is made by the project
maintainer, LookImEcho-Rick, to every recipient of the installer.

The application source itself is available at
https://github.com/LookImEcho-Rick/ZomboidSorter under GPL-3.0-or-later.
Recipients may replace compatible Qt library files in the installed application
directory and run the application with those replacements.

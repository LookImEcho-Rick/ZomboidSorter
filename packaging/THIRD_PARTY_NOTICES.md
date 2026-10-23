# Third-party components in the Windows build

The installer contains PySide6/Qt 6.12.0, Shiboken6 6.12.0, Qt WebEngine
6.12.0.140, the bundled CPython runtime, and PyInstaller 6.22.3 runtime components. The PySide6 modules
and Qt libraries are dynamically loaded from the install directory. Users may
replace compatible library files there and run the application with the
replacements. No technical restriction is applied to modified libraries.

PySide6, Shiboken6, and most bundled Qt modules are offered under LGPL-3.0
or GPL-3.0, with Qt WebEngine also containing Chromium components under
additional licenses, including LGPL-2.1. The installer includes the GPL-3.0,
LGPL-3.0, LGPL-2.1, CPython, and PyInstaller license texts in `LICENSE` and
`licenses/`. It includes a `SOURCE_OFFER.md` describing how to request the
complete corresponding source. See the component license and copyright notices
at these upstream locations:

- Qt for Python licensing: https://doc.qt.io/qtforpython-6/licenses.html
- Qt WebEngine and Chromium licenses: https://doc.qt.io/qt-6/qtwebengine-licensing.html
- Qt open-source obligations and source: https://www.qt.io/development/open-source-lgpl-obligations
- Python license: https://docs.python.org/3/license.html
- PyInstaller license: https://pyinstaller.org/en/stable/license.html
- Qt third-party licenses: https://doc.qt.io/qt-6/licenses-used-in-qt.html

The app's source and GPL-3.0-or-later terms are in the public repository and
the installed `LICENSE` file. The written offer is binding on the maintainer
for recipients of a distributed installer. See `packaging/README.md` for the
remaining release review.

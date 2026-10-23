# Third-party components in the Windows build

The installer contains PySide6 Essentials and Addons 6.12.0, Shiboken6 6.12.0,
PySide6 WebEngine and PDF 6.12.0.140 (Qt WebEngine 6.140.0 with Chromium 140),
the bundled CPython runtime, PyInstaller bootloader/runtime files, and the
Inno Setup installer engine.
The exact CPython version for each build is recorded in
`licenses/BUILD_COMPONENTS.txt`; the corresponding CPython license text is
`licenses/PYTHON.txt`. The exact PySide6, PyInstaller, CPython, OpenSSL, and Inno Setup
versions are recorded in `licenses/BUILD_COMPONENTS.txt`; Inno Setup's license
is `licenses/INNO-SETUP-LICENSE.txt`. The PySide6 modules and Qt libraries are
dynamically loaded from the install directory. Users may replace compatible
library files there and run the application with the replacements. No technical
restriction is applied to modified libraries.

PySide6, Shiboken6, and Qt libraries are available under open-source licenses
including LGPL-3.0 and GPL-3.0 (some Qt modules are GPL-only). This application
is GPL-3.0-or-later. The bundled CPython runtime includes OpenSSL 3 under
Apache-2.0; its full license text is `licenses/OPENSSL-LICENSE.txt`. Qt WebEngine includes Chromium and other third-party code
under additional terms, including LGPL-2.1. The installer includes the full
GPL-3.0, LGPL-3.0, LGPL-2.1, CPython, OpenSSL, PyInstaller, and Inno Setup license texts. It also
includes offline Qt 6.12.0 and Qt WebEngine 6.140.0 attribution pages with
component copyright notices and complete license texts in
`licenses/QT-6.12.0-THIRD-PARTY.html` and
`licenses/QT-WEBENGINE-6.140.0-THIRD-PARTY.html`. The Qt documentation extracts
are provided under GNU Free Documentation License 1.3; its text is included as
`licenses/FDL-1.3.txt`. `SOURCE_OFFER.md` states how recipients can request the
complete corresponding source. Primary upstream references:

- Qt for Python licensing: https://doc.qt.io/qtforpython-6/licenses.html
- Qt 6.12.0 third-party notices: https://doc.qt.io/qt-6/licenses-used-in-qt.html
- Qt WebEngine 6.140.0 and Chromium notices: https://doc.qt.io/qtwebengine/qtwebengine-licensing.html
- Qt open-source obligations and source: https://www.qt.io/development/open-source-lgpl-obligations
- Python license: https://docs.python.org/3/license.html
- OpenSSL license: https://github.com/openssl/openssl/blob/openssl-3.5.7/LICENSE.txt (Apache-2.0; exact runtime version is in the build manifest)
- PyInstaller license: https://pyinstaller.org/en/stable/license.html
- PySide6 source: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/
- Qt 6.12.0 module sources: https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/
- Qt WebEngine/Chromium 6.140.0 source: https://download.qt.io/online/qtsdkrepository/all_os/extensions/qtwebengine/6120/61400/src_doc_examples/extensions.qtwebengine.6120.61400.src/

The app's source and GPL-3.0-or-later terms are in the public repository and
the installed `LICENSE` file. The written offer is binding on the maintainer
for recipients of a distributed installer. Qt's source guidance states that
an upstream link alone may not satisfy all LGPL obligations; use the offer and
fulfill requests for the exact corresponding source archive.

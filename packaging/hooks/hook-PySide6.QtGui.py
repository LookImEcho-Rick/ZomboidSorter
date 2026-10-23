# This is a Windows desktop application. It does not use Qt's generic touch
# handler or bundled virtual keyboard; Windows handles normal text input and
# IME through the QWindows platform plugin.
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [
    item
    for item in binaries
    if not any(
        f"/plugins/{category}/" in item[0].replace("\\", "/").lower()
        for category in ("generic", "platforminputcontexts")
    )
]

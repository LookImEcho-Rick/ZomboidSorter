# The app uses QtWebEngineWidgets, which pulls QtQml in as a native dependency.
# It does not use QML views. PyInstaller's default QtQml hook therefore collects
# thousands of unrelated QML assets and plugin DLLs from the whole PySide6 wheel.
# Keep QtQml's actual module dependencies, but omit that unused QML import tree.
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

# These are development/debugging tools and are not used by the app or by the
# QtWebEngineWidgets browser surface.
binaries = [
    item
    for item in binaries
    if "/plugins/qmltooling/" not in item[0].replace("\\", "/").lower()
]

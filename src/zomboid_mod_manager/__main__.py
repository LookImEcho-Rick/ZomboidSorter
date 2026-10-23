"""Run the desktop application with `python -m zomboid_mod_manager`."""

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from zomboid_mod_manager.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    icon_path = (
        Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        / "assets"
        / "zomboidsorter-logo.png"
    )
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setOrganizationName("ZomboidSorter")
    app.setApplicationName("ZomboidSorter")
    app.setStyle(QStyleFactory.create("Fusion"))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202326"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#17191b"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#25292d"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#f3f3f3"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#17191b"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#30353a"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ff6868"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#7ab7ff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#b18b4b"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#111315"))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#858b91")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#858b91")
    )
    app.setPalette(palette)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the desktop application with `python -m zomboid_mod_manager`."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox, QStyleFactory

from zomboid_mod_manager.portable import application_directory
from zomboid_mod_manager.ui.main_window import MainWindow
from zomboid_mod_manager.updates import UpdateOutcome, consume_update_outcome


def _show_update_outcome(window: MainWindow, outcome: UpdateOutcome) -> None:
    box = QMessageBox(window)
    box.setTextFormat(Qt.TextFormat.PlainText)
    if outcome.status == "success":
        window.status.setText(
            f"Update to {outcome.version} installed and verified · "
            f"build {outcome.installed_build_id[:8]}"
        )
        box.setWindowTitle("Update Complete")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"ZomboidSorter {outcome.version} is installed.")
        box.setInformativeText(
            f"Verified build {outcome.installed_build_id[:8]} against the update package."
        )
    else:
        window.status.setText("The update could not be verified. See the update log.")
        box.setWindowTitle("Update Needs Attention")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("ZomboidSorter could not verify the update installation.")
        details = outcome.message or "The installer did not provide an error message."
        if outcome.log_path:
            details += f"\n\nUpdate log: {outcome.log_path}"
        box.setInformativeText(details)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


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
    outcome = consume_update_outcome(application_directory())
    if outcome is not None:
        QTimer.singleShot(0, lambda: _show_update_outcome(window, outcome))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

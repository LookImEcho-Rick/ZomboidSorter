"""Keep collection preparation and recovery off the GUI thread."""

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from .theme import apply_theme


class CollectionLoadWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.result_ready.emit(
                self.operation(self.isInterruptionRequested, self.progress.emit)
            )
        except Exception as exc:  # noqa: BLE001 - Return worker failures to the GUI.
            self.failed.emit(str(exc))


class CollectionLoadDialog(QDialog):
    def __init__(
        self,
        operation,
        parent=None,
        *,
        recovery=False,
        title=None,
        initial=None,
        stopping=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(
            title or ("Restore Previous Pack" if recovery else "Load Mod Pack")
        )
        self.stopping = stopping or "Stopping and restoring the previous pack…"
        self.resize(620, 180)
        apply_theme(self)
        self.result_data = None
        self.error = ""
        self.cancelled = False
        self.recovery = recovery
        layout = QVBoxLayout(self)
        self.status = QLabel(
            initial
            or (
                "Restoring previous collection folders…"
                if recovery
                else "Checking the saved collection and preparing its local copies…"
            )
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        progress = QProgressBar()
        progress.setRange(0, 0)
        layout.addWidget(progress)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(not recovery)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)
        self.worker = CollectionLoadWorker(operation)
        self.worker.result_ready.connect(self._ready)
        self.worker.failed.connect(self._failed)
        self.worker.progress.connect(self.status.setText)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _ready(self, data):
        self.result_data = data

    def _failed(self, message):
        self.error = message

    def _finished(self):
        self.worker.deleteLater()
        self.worker = None
        super().done(
            QDialog.DialogCode.Rejected
            if self.error or self.cancelled
            else QDialog.DialogCode.Accepted
        )

    def done(self, result):
        if self.worker is not None:
            if not self.recovery:
                self.cancelled = True
                self.worker.requestInterruption()
                self.cancel_button.setEnabled(False)
                self.status.setText(self.stopping)
            return
        super().done(result)

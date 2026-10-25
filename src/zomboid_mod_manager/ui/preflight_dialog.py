"""Visible review of advisory findings before a global-list action."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from zomboid_mod_manager.ui.theme import apply_theme


class PreflightReviewDialog(QDialog):
    def __init__(self, warnings: tuple[str, ...], action: str, parent=None) -> None:
        super().__init__(parent)
        action_label = "Apply" if action == "applying" else "Launch"
        self.setWindowTitle(f"Review Before {action_label}")
        self.resize(760, 500)
        self.setMinimumSize(580, 360)
        apply_theme(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        issue_word = "issue" if len(warnings) == 1 else "issues"
        heading = QLabel(f"{len(warnings)} possible {issue_word} in Active Order")
        heading.setObjectName("pageHeading")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        explanation = QLabel(
            "These checks compare your active list with the scanned library and "
            "the requirements each mod declares. Review the findings before continuing."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.findings = QPlainTextEdit()
        self.findings.setReadOnly(True)
        self.findings.setAccessibleName("Active-order findings to review")
        self.findings.setPlainText(
            "\n\n".join(
                f"{index}. {warning}" for index, warning in enumerate(warnings, 1)
            )
        )
        layout.addWidget(self.findings, 1)

        next_step = (
            "Continue to review the global-list changes before applying."
            if action == "applying"
            else "Continue to launch using the loaded global list."
        )
        note = QLabel(f"These findings are advisory. {next_step}")
        note.setObjectName("secondaryText")
        note.setWordWrap(True)
        layout.addWidget(note)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        actions.addWidget(self.cancel_button)
        self.continue_button = QPushButton(
            "Review Changes…" if action == "applying" else "Continue to Launch"
        )
        self.continue_button.setObjectName("primaryAction")
        self.continue_button.clicked.connect(self.accept)
        actions.addWidget(self.continue_button)
        layout.addLayout(actions)

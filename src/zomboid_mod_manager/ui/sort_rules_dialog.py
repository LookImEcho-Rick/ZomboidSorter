"""Editor for explicit relative ordering rules."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from zomboid_mod_manager.sorting.user_rules import (
    UserOrderRule,
    validate_user_order_rules,
)
from zomboid_mod_manager.ui.theme import apply_theme


class SortRulesDialog(QDialog):
    def __init__(self, rules: tuple[UserOrderRule, ...], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("User ordering rules")
        self.resize(560, 420)
        apply_theme(self)
        self._rules = list(rules)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        heading = QLabel("Ordering Rules")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        explanation = QLabel(
            "Add a rule when one Mod ID must load before another. Rules guide Suggest Order; "
            "they do not change the game list until you apply it."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("secondaryText")
        layout.addWidget(explanation)
        self.rule_list = QListWidget()
        self.rule_list.setAccessibleName("Ordering rules")
        self.rule_list.itemSelectionChanged.connect(self._update_remove_enabled)
        layout.addWidget(self.rule_list, 1)

        fields = QHBoxLayout()
        before_field = QVBoxLayout()
        before_field.addWidget(QLabel("Load first"))
        self.before_id = QLineEdit()
        self.before_id.setPlaceholderText("Mod ID that loads first")
        self.before_id.setAccessibleName("Mod ID that loads first")
        self.before_id.setClearButtonEnabled(True)
        before_field.addWidget(self.before_id)
        fields.addLayout(before_field, 1)
        after_field = QVBoxLayout()
        after_field.addWidget(QLabel("Load after"))
        self.after_id = QLineEdit()
        self.after_id.setPlaceholderText("Mod ID that loads after")
        self.after_id.setAccessibleName("Mod ID that loads after")
        self.after_id.setClearButtonEnabled(True)
        after_field.addWidget(self.after_id)
        fields.addLayout(after_field, 1)
        self.add_button = QPushButton("Add Rule")
        self.add_button.clicked.connect(self._add_rule)
        fields.addWidget(self.add_button)
        layout.addLayout(fields)

        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self._remove_selected)
        layout.addWidget(self.remove_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def rules(self) -> tuple[UserOrderRule, ...]:
        return tuple(self._rules)

    def _refresh(self) -> None:
        self.rule_list.clear()
        self.rule_list.addItems([rule.label for rule in self._rules])
        self._update_remove_enabled()

    def _update_remove_enabled(self) -> None:
        self.remove_button.setEnabled(self.rule_list.currentRow() >= 0)

    def _add_rule(self) -> None:
        rule = UserOrderRule(self.before_id.text(), self.after_id.text())
        try:
            validate_user_order_rules(tuple(self._rules) + (rule,))
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid ordering rule", str(exc))
            return
        self._rules.append(rule)
        self.before_id.clear()
        self.after_id.clear()
        self._refresh()

    def _remove_selected(self) -> None:
        row = self.rule_list.currentRow()
        if row < 0:
            return
        del self._rules[row]
        self._refresh()

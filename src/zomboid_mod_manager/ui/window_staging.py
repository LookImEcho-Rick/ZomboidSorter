"""Keyboard, selection, ordering, and sorting proposal actions."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QDesktopServices,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QWidget,
)

from zomboid_mod_manager.sorting.dependency_order import propose_dependency_order
from zomboid_mod_manager.sorting.user_rules import serialize_user_order_rules
from zomboid_mod_manager.ui.sort_rules_dialog import SortRulesDialog


class StagingMixin:
    def _install_workspace_shortcuts(self) -> None:
        def shortcut(keys: str, parent: QWidget, callback: Callable[[], None]) -> None:
            action = QShortcut(QKeySequence(keys), parent)
            action.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.activated.connect(callback)

        shortcut("Ctrl+F", self, self._focus_workspace_search)
        shortcut("Delete", self.active_list, self._stage_deactivate)
        for widget in (self.available_list, self.active_list):
            shortcut(
                "Return", widget, lambda widget=widget: self._focus_list_details(widget)
            )
            shortcut(
                "Enter", widget, lambda widget=widget: self._focus_list_details(widget)
            )
            shortcut("Escape", widget, widget.clearSelection)
            shortcut(
                "Ctrl+A",
                widget,
                lambda widget=widget: self._select_visible_items(widget),
            )
        for search in (self.manage_search, self.active_search):
            shortcut("Escape", search, search.clear)

    def _focus_workspace_search(self) -> None:
        focused = QApplication.focusWidget()
        search = (
            self.active_search
            if focused in (self.active_list, self.active_search)
            else self.manage_search
        )
        self.main_tabs.setCurrentIndex(0)
        search.setFocus()
        search.selectAll()

    def _focus_list_details(self, widget: QListWidget) -> None:
        item = widget.currentItem()
        if item is not None and not item.isHidden():
            self._show_management_item(item, None)
            self.detail_tabs.setCurrentIndex(1)
            self.details.setFocus()

    @staticmethod
    def _select_visible_items(widget: QListWidget) -> None:
        for row in range(widget.count()):
            item = widget.item(row)
            if not item.isHidden() and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setSelected(True)

    @staticmethod
    def _actionable_items(widget: QListWidget) -> list[QListWidgetItem]:
        return [
            item
            for item in widget.selectedItems()
            if not item.isHidden() and item.flags() & Qt.ItemFlag.ItemIsEnabled
        ]

    def _selected_active_rows(self) -> set[int]:
        return {
            self.active_list.row(item)
            for item in self._actionable_items(self.active_list)
        }

    def _show_list_context_menu(self, widget: QListWidget, point) -> None:
        clicked = widget.itemAt(point)
        if (
            clicked is not None
            and clicked.flags() & Qt.ItemFlag.ItemIsEnabled
            and not clicked.isSelected()
        ):
            widget.clearSelection()
            widget.setCurrentItem(clicked)
        menu = self._build_list_context_menu(widget)
        menu.exec(widget.viewport().mapToGlobal(point))

    def _build_list_context_menu(self, widget: QListWidget) -> QMenu:
        menu = QMenu(self)
        items = self._actionable_items(widget)
        if items:
            if widget is self.available_list:
                menu.addAction("Add selected to Active Order", self._stage_activate)
            else:
                menu.addAction(
                    "Remove selected from Active Order", self._stage_deactivate
                )
            if len(items) == 1:
                mod_id = items[0].data(Qt.ItemDataRole.UserRole)
                matches = [
                    entry
                    for entry in (
                        self._last_result.entries if self._last_result else ()
                    )
                    if entry.mod_id == mod_id
                ]
                menu.addSeparator()
                menu.addAction(
                    "Copy Mod ID",
                    lambda mod_id=mod_id: QApplication.clipboard().setText(mod_id),
                )
                if len(matches) == 1:
                    entry = matches[0]
                    menu.addAction(
                        "Open mod folder",
                        lambda entry=entry: QDesktopServices.openUrl(
                            QUrl.fromLocalFile(str(entry.entry_path))
                        ),
                    )
                    if entry.workshop_id:
                        menu.addAction(
                            "Copy Workshop ID",
                            lambda entry=entry: QApplication.clipboard().setText(
                                entry.workshop_id
                            ),
                        )
                        menu.addAction(
                            "Open Workshop page",
                            lambda entry=entry: QDesktopServices.openUrl(
                                QUrl(
                                    "https://steamcommunity.com/sharedfiles/"
                                    f"filedetails/?id={entry.workshop_id}"
                                )
                            ),
                        )
        if items:
            menu.addSeparator()
        menu.addAction("Select all visible", lambda: self._select_visible_items(widget))
        return menu

    def _select_filtered_available(self) -> None:
        self.available_list.clearSelection()
        self._select_visible_items(self.available_list)

    def _stage_activate(self) -> None:
        items = self._actionable_items(self.available_list)
        mod_ids = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in sorted(items, key=self.available_list.row)
            if item is not None
        ]
        self._add_mod_ids(mod_ids)

    def _stage_activate_item(self, item: QListWidgetItem) -> None:
        if item.isHidden() or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        self._add_mod_ids([item.data(Qt.ItemDataRole.UserRole)])

    def _add_mod_ids(self, mod_ids: list[str]) -> None:
        additions = [
            mod_id
            for mod_id in mod_ids
            if mod_id and mod_id not in self._staged_mod_ids
        ]
        if additions:
            self._staged_mod_ids.extend(additions)
            self._refresh_management_lists()
            self._update_apply_enabled()
            count = len(additions)
            self.configuration_status.setText(
                f"Added {count} {'mod' if count == 1 else 'mods'} to Active Order. "
                "Apply to save the change to Project Zomboid."
            )

    def _stage_deactivate(self) -> None:
        items = self._actionable_items(self.active_list)
        removed = {
            item.data(Qt.ItemDataRole.UserRole) for item in items if item is not None
        }
        self._remove_mod_ids(removed)

    def _stage_deactivate_item(self, item: QListWidgetItem) -> None:
        if item.isHidden() or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        self._remove_mod_ids({item.data(Qt.ItemDataRole.UserRole)})

    def _remove_mod_ids(self, removed: set[str]) -> None:
        remaining = [mod_id for mod_id in self._staged_mod_ids if mod_id not in removed]
        if remaining != self._staged_mod_ids:
            count = len(self._staged_mod_ids) - len(remaining)
            self._staged_mod_ids = remaining
            self._refresh_management_lists()
            self._update_apply_enabled()
            self.configuration_status.setText(
                f"Removed {count} {'mod' if count == 1 else 'mods'} from Active Order. "
                "Installed mod files are unchanged; apply to save the game list."
            )

    def _handle_mod_list_drop(
        self,
        source: QListWidget,
        target: QListWidget,
        mod_ids: list[str],
        target_row: int,
    ) -> None:
        if source is self.available_list and target is self.active_list:
            known_ids = set(self._staged_mod_ids)
            additions = []
            for mod_id in mod_ids:
                if mod_id not in known_ids:
                    additions.append(mod_id)
                    known_ids.add(mod_id)
            if not additions:
                return
            active_is_filtered = bool(self.active_search.text().strip()) or (
                self.active_filter.currentIndex() != 0
            )
            insertion_row = (
                len(self._staged_mod_ids)
                if active_is_filtered
                else max(0, min(target_row, len(self._staged_mod_ids)))
            )
            self._staged_mod_ids[insertion_row:insertion_row] = additions
        elif source is self.active_list and target is self.available_list:
            removed = set(mod_ids)
            remaining = [
                mod_id for mod_id in self._staged_mod_ids if mod_id not in removed
            ]
            if remaining == self._staged_mod_ids:
                return
            self._staged_mod_ids = remaining
        else:
            return
        self._refresh_management_lists()
        self._update_apply_enabled()

    def _active_list_reordered(self) -> None:
        reordered = [
            self.active_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.active_list.count())
        ]
        if len(reordered) == len(self._staged_mod_ids) and all(
            isinstance(item, str) for item in reordered
        ):
            self._staged_mod_ids = reordered
            self._update_apply_enabled()
            self._update_diagnostics()

    def _move_active(self, offset: int) -> None:
        if (
            offset not in (-1, 1)
            or self.active_search.text().strip()
            or self.active_filter.currentIndex() != 0
        ):
            return
        selected_rows = self._selected_active_rows()
        selected_ids = {self._staged_mod_ids[row] for row in selected_rows}
        moved = False
        for row in sorted(selected_rows, reverse=offset > 0):
            destination = row + offset
            if (
                0 <= destination < len(self._staged_mod_ids)
                and self._staged_mod_ids[destination] not in selected_ids
            ):
                self._staged_mod_ids[row], self._staged_mod_ids[destination] = (
                    self._staged_mod_ids[destination],
                    self._staged_mod_ids[row],
                )
                moved = True
        if not moved:
            return
        self._refresh_management_lists()
        current = self.active_list.currentItem()
        if current is not None:
            self.active_list.scrollToItem(current)
        self._update_apply_enabled()

    def _suggest_dependency_order(self) -> None:
        if self._last_result is None:
            self.configuration_status.setText(
                "Scan the mod library before requesting an order suggestion."
            )
            return
        try:
            proposal = propose_dependency_order(
                self._last_result.entries,
                self._staged_mod_ids,
                self._user_order_rules,
                target_build=self._metadata_target_build(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Could not suggest order", str(exc))
            return
        if proposal.cycles:
            explanation = "No order was staged because the active constraints contain a cycle:\n\n"
            explanation += "\n".join(
                " → ".join(cycle + (cycle[0],)) for cycle in proposal.cycles
            )
            if proposal.unresolved:
                explanation += "\n\nOther unresolved metadata:\n" + "\n".join(
                    proposal.unresolved[:8]
                )
            self.configuration_status.setText(
                "Order suggestion stopped: active dependency/order cycle."
            )
            QMessageBox.warning(self, "No safe order suggestion", explanation)
            return
        if not proposal.constraints:
            message = "No verified active ordering constraints were found. Your current order is unchanged."
            if proposal.unresolved:
                message += "\n\nUnresolved metadata:\n" + "\n".join(
                    proposal.unresolved[:8]
                )
            self.configuration_status.setText(
                "No verified constraints; current order retained."
            )
            QMessageBox.information(self, "Order suggestion", message)
            return
        if not proposal.changed:
            self.configuration_status.setText(
                f"Current order already satisfies {len(proposal.constraints)} verified constraints."
            )
            QMessageBox.information(
                self,
                "Order suggestion",
                "The current order already satisfies the verified constraints. No change was staged.",
            )
            return

        original_positions = {
            mod_id: index for index, mod_id in enumerate(proposal.original)
        }
        moved = [
            f"{index + 1}. {mod_id}"
            for index, mod_id in enumerate(proposal.suggested)
            if original_positions[mod_id] != index
        ]
        reasons = [
            f"{constraint.before} before {constraint.after}: {constraint.reason} "
            f"[from {constraint.source}]"
            for constraint in proposal.constraints[:12]
        ]
        message = "Stage this deterministic order? It keeps the current order as the tie-breaker.\n\n"
        message += "Changed positions:\n" + "\n".join(moved[:12])
        message += "\n\nConstraints:\n" + "\n".join(reasons)
        if len(proposal.constraints) > 12:
            message += f"\n…and {len(proposal.constraints) - 12} more constraints."
        if proposal.unresolved:
            message += "\n\nUnresolved metadata (not used to order):\n" + "\n".join(
                proposal.unresolved[:8]
            )
        message += "\n\nThis only stages the order. Applying to the global game list is a separate action."
        answer = QMessageBox.question(
            self,
            "Stage suggested order",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._staged_mod_ids = list(proposal.suggested)
        self._refresh_management_lists()
        self._update_apply_enabled()
        self.configuration_status.setText(
            f"Staged an order satisfying {len(proposal.constraints)} verified constraints. "
            "Apply separately to update Project Zomboid."
        )

    def _manage_sort_rules(self) -> None:
        dialog = SortRulesDialog(self._user_order_rules, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rules = dialog.rules()
        self._user_order_rules = rules
        self._user_rule_settings_error = None
        if self._persist_settings:
            self._settings.setValue(
                "sorting/user_rules", serialize_user_order_rules(rules)
            )
            self._settings.sync()
        self._update_diagnostics()

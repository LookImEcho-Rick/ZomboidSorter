"""Available and active mod list display and filtering."""

from __future__ import annotations

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtGui import (
    QColor,
)
from PySide6.QtWidgets import (
    QListWidgetItem,
)

from zomboid_mod_manager.discovery.version_selection import (
    declared_version_range_diagnostics,
    resolve_entry_metadata,
)
from zomboid_mod_manager.domain import ModEntry

from .window_widgets import (
    BUILD_41_ROLE,
    BUILD_42_ROLE,
    ISSUE_ROLE,
    NEW_WORKSHOP_ROLE,
    SEARCH_ROLE,
    SOURCE_ROLE,
)


class LibraryMixin:
    def _refresh_management_lists(self) -> None:
        current_ids = {
            widget: (
                widget.currentItem().data(Qt.ItemDataRole.UserRole)
                if widget.currentItem() is not None
                else None
            )
            for widget in (self.active_list, self.available_list)
        }
        inspected_id = self._last_management_mod_id
        inspected_widget = next(
            (
                widget
                for widget, mod_id in current_ids.items()
                if mod_id == inspected_id
            ),
            None,
        )
        selected_ids: set[str] = set()
        list_widgets = (self.active_list, self.available_list)
        scroll_positions = {
            widget: widget.verticalScrollBar().value() for widget in list_widgets
        }
        for widget in list_widgets:
            selected_ids.update(
                item.data(Qt.ItemDataRole.UserRole) for item in widget.selectedItems()
            )
        self.available_list.clear()
        self.active_list.clear()

        entries_by_id: dict[str, list[ModEntry]] = {}
        if self._last_result is not None:
            for entry in self._last_result.entries:
                if entry.mod_id:
                    entries_by_id.setdefault(entry.mod_id, []).append(entry)

        staged = set(self._staged_mod_ids)
        for mod_id in self._staged_mod_ids:
            matches = entries_by_id.get(mod_id, [])
            if len(matches) == 1:
                label = f"{self._entry_display_name(matches[0])}  ·  {mod_id}"
            elif len(matches) > 1:
                label = f"Duplicate installation  ·  {mod_id}"
            else:
                label = f"Not found in scan  ·  {mod_id}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, mod_id)
            item.setToolTip(label)
            self._set_list_item_metadata(
                item, mod_id, matches, include_discovery_issues=False
            )
            if len(matches) != 1:
                item.setText("⚠  " + label)
                if matches:
                    item.setToolTip(
                        f"{label}\n\nMultiple entries with this Mod ID were found "
                        "in the selected folders. Review Library Diagnostics to compare them."
                    )
                else:
                    item.setToolTip(
                        f"{label}\n\nThe configured Mod ID was not found in the selected local or Workshop folders. "
                        "Check Paths & Settings and refresh the scan."
                    )
            self._mark_recently_added_workshop_entry(item, matches)
            self.active_list.addItem(item)

        sort_mode = self.inactive_sort.currentIndex()
        inactive_entries = sorted(
            entries_by_id.items(),
            key=lambda pair: (
                pair[0].casefold()
                if sort_mode >= 2
                else self._entry_display_name(pair[1][0]).casefold(),
                pair[0].casefold(),
            ),
            reverse=sort_mode in (1, 3),
        )
        for mod_id, matches in inactive_entries:
            if mod_id in staged:
                continue
            if len(matches) == 1:
                label = f"{self._entry_display_name(matches[0])}  ·  {mod_id}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, mod_id)
                item.setToolTip(label)
                if self._entry_issue_messages(matches[0]):
                    item.setText("⚠  " + label)
                    item.setToolTip(
                        label
                        + "\n\n"
                        + "\n".join(self._entry_issue_messages(matches[0]))
                    )
            else:
                label = f"Duplicate installation  ·  {mod_id}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, mod_id)
                item.setToolTip(
                    f"{label}\n\nResolve duplicate Mod IDs before activating this entry."
                )
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._set_list_item_metadata(item, mod_id, matches)
            self._mark_recently_added_workshop_entry(item, matches)
            self.available_list.addItem(item)
        self._filter_available_mods(self.manage_search.text())
        self._filter_active_mods(self.active_search.text())
        inspected_item = None
        items_to_select = []
        for widget in list_widgets:
            for row in range(widget.count()):
                item = widget.item(row)
                mod_id = item.data(Qt.ItemDataRole.UserRole)
                if mod_id == current_ids[widget]:
                    widget.setCurrentItem(item)
                if mod_id in selected_ids:
                    items_to_select.append(item)
                if mod_id == inspected_id:
                    inspected_item = item
        if inspected_item is not None:
            owner = inspected_item.listWidget()
            if owner.currentItem() is not inspected_item:
                owner.setCurrentItem(inspected_item)
            self._show_management_item(inspected_item, None)
        elif inspected_id is not None and inspected_widget is not None:
            self._display_removed_mod_id(inspected_id)
        for item in items_to_select:
            item.setSelected(True)
        for widget in list_widgets:
            widget.verticalScrollBar().setValue(scroll_positions[widget])
        if (
            inspected_item is not None
            and inspected_item.listWidget() is not inspected_widget
        ):
            inspected_item.listWidget().scrollToItem(inspected_item)
        self._update_diagnostics()
        self._update_workspace_actions()

    def _mark_recently_added_workshop_entry(
        self, item: QListWidgetItem, matches: list[ModEntry]
    ) -> None:
        is_new = any(
            entry.key in self._recently_added_workshop_entry_keys for entry in matches
        )
        item.setData(NEW_WORKSHOP_ROLE, is_new)
        if not is_new:
            return
        item.setText(f"NEW  ·  {item.text()}")
        item.setForeground(QColor("#8fe0a7"))
        item.setToolTip(
            item.toolTip() + "\n\nNew Workshop content found on the latest scan."
        )

    def _set_list_item_metadata(
        self,
        item: QListWidgetItem,
        mod_id: str,
        matches: list[ModEntry],
        *,
        include_discovery_issues: bool = True,
    ) -> None:
        item.setData(
            SEARCH_ROLE,
            " ".join(
                [mod_id]
                + [self._entry_display_name(entry) for entry in matches]
                + [entry.workshop_id or "" for entry in matches]
            ).casefold(),
        )
        item.setData(SOURCE_ROLE, matches[0].source if len(matches) == 1 else "")
        item.setData(
            BUILD_41_ROLE,
            any(resolve_entry_metadata(entry, "41").candidates for entry in matches),
        )
        item.setData(
            BUILD_42_ROLE,
            any(resolve_entry_metadata(entry, "42").candidates for entry in matches),
        )
        has_issue = len(matches) != 1
        if include_discovery_issues:
            target_build = self._metadata_target_build()
            has_issue = has_issue or any(
                bool(self._entry_issue_messages(entry))
                or any(
                    candidate.diagnostics
                    for candidate in resolve_entry_metadata(
                        entry, target_build
                    ).candidates
                )
                for entry in matches
            )
        item.setData(ISSUE_ROLE, has_issue)

    def _metadata_target_build(self) -> str:
        target = self.metadata_preview_target.currentData()
        if target == "42":
            return self.metadata_build_version.text().strip() or "42"
        return target

    def _discover_target_build(self) -> str:
        target = self.inactive_build_filter.currentData()
        return str(target) if target in {"41", "42"} else self._metadata_target_build()

    def _entry_display_name(self, entry: ModEntry) -> str:
        target_build = self._discover_target_build()
        selected = resolve_entry_metadata(entry, target_build)
        candidate = selected.candidates[0] if selected.candidates else None
        if candidate is not None:
            name = candidate.fields.get("name", "").strip()
            if name:
                return name
        return entry.name

    def _entry_diagnostics_for_target(
        self, entry: ModEntry, target_build: str | None = None
    ) -> tuple[str, ...]:
        target_build = target_build or self._metadata_target_build()
        selection = resolve_entry_metadata(entry, target_build)
        messages = list(entry.diagnostics)
        if selection.status in {
            "build-41",
            "selected-version",
            "selected-common",
        }:
            selected_paths = {candidate.path for candidate in selection.candidates}
            messages = [
                message
                for message in messages
                if message
                != "Metadata candidates have different names; no active build was selected."
                and not any(
                    message.startswith(f"{candidate.path}:")
                    and candidate.path not in selected_paths
                    for candidate in entry.candidates
                )
            ]
        if (
            selection.status in {"invalid", "missing", "ambiguous"}
            or not selection.candidates
        ):
            messages.append(selection.message)
        if selection.candidates:
            exact_target = self._exact_compatibility_target(target_build)
            if exact_target is not None:
                for candidate in selection.candidates:
                    messages.extend(
                        declared_version_range_diagnostics(candidate, exact_target)
                    )
        return tuple(messages)

    def _entry_issue_messages(self, entry: ModEntry) -> tuple[str, ...]:
        return self._entry_diagnostics_for_target(entry, self._metadata_target_build())

    def _exact_compatibility_target(self, target_build: str) -> str | None:
        if target_build not in {"41", "42", "all"}:
            return target_build
        if target_build != "41":
            return None
        detection = self._game_build_detection
        if detection.major_build == target_build:
            return detection.exact_version
        return None

    @staticmethod
    def _matches_list_filter(item: QListWidgetItem, query: str, mode: str) -> bool:
        if query.casefold().strip() not in (item.data(SEARCH_ROLE) or ""):
            return False
        if mode in ("Workshop", "Local"):
            return item.data(SOURCE_ROLE) == mode.casefold()
        if mode == "Warnings":
            return bool(item.data(ISSUE_ROLE))
        if mode == "Missing / duplicate":
            return not item.data(SOURCE_ROLE)
        return True

    def _filter_available_mods(self, query: str) -> None:
        mode = self.inactive_filter.currentText()
        build = self.inactive_build_filter.currentData()
        build_role = {"41": BUILD_41_ROLE, "42": BUILD_42_ROLE}.get(build)
        visible = 0
        for index in range(self.available_list.count()):
            item = self.available_list.item(index)
            match = self._matches_list_filter(item, query, mode)
            if build_role is not None:
                match = match and bool(item.data(build_role))
            item.setHidden(not match)
            visible += match
        self.available_list.visible_count = visible
        total = self.available_list.count()
        count = f"{visible} of {total}" if visible != total else str(total)
        new_count = sum(
            not self.available_list.item(row).isHidden()
            and bool(self.available_list.item(row).data(NEW_WORKSHOP_ROLE))
            for row in range(total)
        )
        new_label = f"  ·  {new_count} new" if new_count else ""
        library_warning_count = getattr(self, "_library_warning_count", 0)
        library_error_count = getattr(self, "_library_error_count", 0)
        diagnostics_label = ""
        if self._last_result is not None:
            warning_word = "warning" if library_warning_count == 1 else "warnings"
            diagnostics_label = f"  ·  Library: {library_warning_count} {warning_word}"
            if library_error_count:
                error_word = "error" if library_error_count == 1 else "errors"
                diagnostics_label += f"  ·  {library_error_count} {error_word}"
        self.inactive_heading.setText(
            f"AVAILABLE MODS  ·  {count}{new_label}{diagnostics_label}"
        )
        if query or mode != "All sources" or build != "all":
            self.available_list.empty_text = "No mods match this search or filter"
        elif self._last_result is not None and not self._last_result.entries:
            self.available_list.empty_text = (
                "No mod entries were found in the selected local or Workshop folders. "
                "Check Paths & Settings, then refresh."
            )
        else:
            self.available_list.empty_text = (
                "No inactive mods found in the scanned folders"
            )
        self.available_list.viewport().update()
        self._update_workspace_actions()

    def _filter_active_mods(self, query: str) -> None:
        mode = self.active_filter.currentText()
        visible = 0
        for index in range(self.active_list.count()):
            item = self.active_list.item(index)
            match = self._matches_list_filter(item, query, mode)
            item.setHidden(not match)
            visible += match
        self.active_list.visible_count = visible
        total = self.active_list.count()
        count = f"{visible} of {total}" if visible != total else str(total)
        new_count = sum(
            not self.active_list.item(row).isHidden()
            and bool(self.active_list.item(row).data(NEW_WORKSHOP_ROLE))
            for row in range(total)
        )
        new_label = f"  ·  {new_count} new" if new_count else ""
        self.active_heading.setText(f"ACTIVE ORDER  ·  {count}{new_label}")
        self.active_list.empty_text = (
            "No active mods match this search or filter"
            if query or mode != "All active"
            else "Active Order is empty. Choose mods in Available Mods, then select Add."
        )
        self.active_list.viewport().update()
        unfiltered = not query.strip() and self.active_filter.currentIndex() == 0
        self.active_list.setDragEnabled(unfiltered)
        self._update_workspace_actions()

    def _update_workspace_actions(self) -> None:
        available = self._actionable_items(self.available_list)
        active = self._actionable_items(self.active_list)
        self.activate_button.setEnabled(bool(available))
        self.deactivate_button.setEnabled(bool(active))
        selectable_count = sum(
            not self.available_list.item(row).isHidden()
            and bool(self.available_list.item(row).flags() & Qt.ItemFlag.ItemIsEnabled)
            for row in range(self.available_list.count())
        )
        self.select_filtered_button.setEnabled(selectable_count > 0)
        self.select_filtered_button.setText(f"Select {selectable_count}")
        selected_rows = self._selected_active_rows()
        unfiltered = (
            not self.active_search.text().strip()
            and self.active_filter.currentIndex() == 0
        )
        self.move_up_button.setEnabled(
            unfiltered
            and any(row > 0 and row - 1 not in selected_rows for row in selected_rows)
        )
        self.move_down_button.setEnabled(
            unfiltered
            and any(
                row < self.active_list.count() - 1 and row + 1 not in selected_rows
                for row in selected_rows
            )
        )

    def _show_management_item(self, current, _previous) -> None:
        if current is None:
            return
        mod_id = current.data(Qt.ItemDataRole.UserRole)
        self._last_management_mod_id = mod_id
        matches = [
            entry
            for entry in (self._last_result.entries if self._last_result else ())
            if entry.mod_id == mod_id
        ]
        if len(matches) == 1:
            self._display_entry(matches[0])
        else:
            self._display_unresolved_mod_id(mod_id, duplicate=bool(matches))

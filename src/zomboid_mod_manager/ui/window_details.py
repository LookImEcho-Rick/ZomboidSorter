"""Selected-mod details, descriptions, and preview actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QDesktopServices,
    QImage,
)

from zomboid_mod_manager.discovery.version_selection import resolve_entry_metadata
from zomboid_mod_manager.domain import ModEntry
from zomboid_mod_manager.ui.mod_details import (
    find_preview_for_candidates,
    format_entry_description_html,
    format_entry_details,
    format_workshop_description_html,
)

from .window_workers import (
    PreviewWorker,
    WorkshopDescriptionWorker,
)


class DetailsMixin:
    def _show_selected_entry(self, current, _previous) -> None:
        if not current.isValid():
            self.inspect_library_button.setEnabled(False)
            self.open_workshop_button.setProperty("workshopId", None)
            self.open_workshop_button.setEnabled(False)
            self.open_folder_button.setProperty("entryPath", None)
            self.open_folder_button.setEnabled(False)
            return
        key = current.sibling(current.row(), 0).data(Qt.ItemDataRole.UserRole)
        entry = self._entries.get(key)
        if entry is None:
            self.inspect_library_button.setEnabled(False)
            self.open_workshop_button.setProperty("workshopId", None)
            self.open_workshop_button.setEnabled(False)
            self.open_folder_button.setProperty("entryPath", None)
            self.open_folder_button.setEnabled(False)
            return
        self.inspect_library_button.setEnabled(True)
        self._display_entry(entry)

    def _open_library_entry(self, _index=None) -> None:
        current = self.table.currentIndex()
        if not current.isValid():
            return
        key = current.sibling(current.row(), 0).data(Qt.ItemDataRole.UserRole)
        entry = self._entries.get(key)
        if entry is None:
            return
        self.main_tabs.setCurrentWidget(self.workspace_page)
        if entry.mod_id:
            widget = (
                self.active_list
                if entry.mod_id in self._staged_mod_ids
                else self.available_list
            )
            for row in range(widget.count()):
                item = widget.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == entry.mod_id:
                    if item.isHidden():
                        if widget is self.active_list:
                            self.active_search.clear()
                            self.active_filter.setCurrentIndex(0)
                        else:
                            self.manage_search.clear()
                            self.inactive_filter.setCurrentIndex(0)
                    widget.setCurrentItem(item)
                    break
        self._display_entry(entry)

    def _metadata_preview_target_changed(self, _value=None) -> None:
        self.metadata_build_version.setVisible(
            self.metadata_preview_target.currentData() == "42"
        )
        if self._selected_entry is not None:
            self._display_entry(self._selected_entry)
        if self._last_result is not None:
            self._refresh_management_lists()

    def _display_entry(self, entry: ModEntry) -> None:
        self._selected_entry = entry
        self.open_workshop_button.setProperty("workshopId", entry.workshop_id)
        self.open_workshop_button.setEnabled(bool(entry.workshop_id))
        self.open_folder_button.setProperty("entryPath", str(entry.entry_path))
        self.open_folder_button.setEnabled(True)
        entries = self._last_result.entries if self._last_result else (entry,)
        target_build = self._metadata_target_build()
        selection = resolve_entry_metadata(entry, target_build)
        candidates = selection.candidates
        self.details.setPlainText(
            format_entry_details(
                entry,
                entries,
                self._staged_mod_ids,
                target_build,
                include_description=False,
            )
        )
        if entry.workshop_id:
            self._request_workshop_description(entry, target_build)
        else:
            self._workshop_description_requested_id = None
            self._workshop_description_pending = None
            self._show_local_description(
                entry, target_build, "Local mod.info description"
            )
        choice = find_preview_for_candidates(entry, candidates)
        if choice is None:
            self._clear_preview(
                "NO PREVIEW AVAILABLE",
                f"{selection.message} No local poster or icon was found.",
            )
            return
        self._preview_requested = str(choice.path)
        if target_build == "all":
            caption = (
                f"Illustration from {choice.candidate.layout}; "
                "this does not select a game build."
            )
        elif (
            selection.status == "selected-version"
            or selection.status == "selected-common"
        ):
            caption = (
                f"{selection.message} This selects metadata only; it does not "
                "verify the mod's content is compatible."
            )
        else:
            caption = (
                f"Illustration from {choice.candidate.layout}; {selection.message}"
            )
        self.preview_caption.setText(f"{caption} Click the image to enlarge it.")
        cached = self._preview_cache.get(self._preview_requested)
        if cached is not None:
            self._preview_cache.move_to_end(self._preview_requested)
            self.preview.show_image(cached)
            self._preview_pending = None
            return
        self.preview.show_placeholder("LOADING PREVIEW…")
        if self._preview_worker is None:
            self._start_preview_worker(choice.path)
        else:
            self._preview_pending = choice.path

    def _show_local_description(
        self, entry: ModEntry, target_build: str, source: str
    ) -> None:
        self.description.setHtml(format_entry_description_html(entry, target_build))
        self.description_source.setText(source)
        self.description_source.setToolTip("")

    def _request_workshop_description(self, entry: ModEntry, target_build: str) -> None:
        workshop_id = entry.workshop_id
        if not workshop_id:
            self._show_local_description(
                entry, target_build, "Local mod.info description"
            )
            return
        self._workshop_description_requested_id = workshop_id
        cached = self._workshop_description_cache.get(workshop_id)
        if cached is not None:
            self._workshop_description_cache.move_to_end(workshop_id)
            self._workshop_description_pending = None
            self._show_loaded_workshop_description(
                entry, target_build, cached[0], cached[1]
            )
            return
        self._show_local_description(
            entry,
            target_build,
            "Loading Workshop description; showing local metadata for now…",
        )
        worker = self._workshop_description_worker
        if worker is not None and worker.workshop_id == workshop_id:
            self._workshop_description_pending = None
            return
        if worker is not None:
            self._workshop_description_pending = workshop_id
            return
        self._start_workshop_description_worker(workshop_id)

    def _start_workshop_description_worker(self, workshop_id: str) -> None:
        worker = WorkshopDescriptionWorker(workshop_id)
        self._workshop_description_worker = worker
        worker.result_ready.connect(self._workshop_description_loaded)
        worker.failed.connect(self._workshop_description_failed)
        worker.finished.connect(self._workshop_description_worker_finished)
        worker.start()

    def _workshop_description_loaded(
        self, workshop_id: str, title: str, description: str
    ) -> None:
        self._workshop_description_cache[workshop_id] = (title, description)
        self._workshop_description_cache.move_to_end(workshop_id)
        if len(self._workshop_description_cache) > 24:
            self._workshop_description_cache.popitem(last=False)
        if (
            self._workshop_description_requested_id != workshop_id
            or self._selected_entry is None
        ):
            return
        self._show_loaded_workshop_description(
            self._selected_entry,
            self._metadata_target_build(),
            title,
            description,
        )

    def _show_loaded_workshop_description(
        self, entry: ModEntry, target_build: str, title: str, description: str
    ) -> None:
        if not description.strip():
            self._show_local_description(
                entry,
                target_build,
                "Workshop has no description; showing local mod.info metadata.",
            )
            return
        self.description.setHtml(format_workshop_description_html(description))
        self.description_source.setText(f"Steam Workshop · {title}")
        self.description_source.setToolTip(
            "Full published description fetched read-only from Steam."
        )

    def _workshop_description_failed(self, workshop_id: str, message: str) -> None:
        if (
            self._workshop_description_requested_id == workshop_id
            and self._selected_entry is not None
        ):
            self._show_local_description(
                self._selected_entry,
                self._metadata_target_build(),
                "Workshop description unavailable; showing local metadata.",
            )
            self.description_source.setToolTip(message)

    def _workshop_description_worker_finished(self) -> None:
        self._workshop_description_worker = None
        if self._shutdown_requested:
            self._workshop_description_pending = None
            return
        pending = self._workshop_description_pending
        self._workshop_description_pending = None
        if pending and pending == self._workshop_description_requested_id:
            self._start_workshop_description_worker(pending)

    def _clear_preview(self, text: str, caption: str) -> None:
        self._preview_requested = None
        self._preview_pending = None
        self.preview.show_placeholder(text)
        self.preview_caption.setText(caption)

    def _show_enlarged_preview(self) -> None:
        image = self.preview.image
        if image.isNull():
            return
        self.preview_overlay.show_image(image)

    def _start_preview_worker(self, path: Path) -> None:
        self._preview_worker = PreviewWorker(path, self._preview_generation)
        self._preview_worker.loaded.connect(self._preview_loaded)
        self._preview_worker.finished.connect(self._preview_worker_finished)
        self._preview_worker.start()

    def _preview_loaded(self, path: str, generation: int, image: QImage) -> None:
        if generation != self._preview_generation:
            return
        if not image.isNull():
            self._preview_cache[path] = image
            self._preview_cache.move_to_end(path)
            if len(self._preview_cache) > 16:
                self._preview_cache.popitem(last=False)
        if self._preview_requested == path:
            if image.isNull():
                self.preview.show_placeholder("PREVIEW UNAVAILABLE")
            else:
                self.preview.show_image(image)

    def _preview_worker_finished(self) -> None:
        self._preview_worker = None
        if self._shutdown_requested:
            self._preview_pending = None
            return
        pending = self._preview_pending
        self._preview_pending = None
        if (
            pending is not None
            and str(pending) == self._preview_requested
            and str(pending) not in self._preview_cache
        ):
            self._start_preview_worker(pending)

    def _open_selected_folder(self) -> None:
        path = self.open_folder_button.property("entryPath")
        if isinstance(path, str) and Path(path).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_selected_workshop_page(self) -> None:
        workshop_id = self.open_workshop_button.property("workshopId")
        if isinstance(workshop_id, str) and workshop_id.isdecimal():
            QDesktopServices.openUrl(
                QUrl(
                    f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
                )
            )

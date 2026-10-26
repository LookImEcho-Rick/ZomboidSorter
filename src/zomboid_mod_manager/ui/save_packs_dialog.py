"""Browse and group existing game saves under one app-owned Mod Pack."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from zomboid_mod_manager.profiles import ProfileStore
from zomboid_mod_manager.save_packs import (
    GameSave,
    SaveAssignmentStore,
    SavePackError,
    discover_saves,
)
from zomboid_mod_manager.ui.theme import apply_theme


class SavePickerDialog(QDialog):
    def __init__(
        self,
        saves: tuple[GameSave, ...],
        assignments: SaveAssignmentStore,
        pack_name: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Existing Save")
        self.resize(560, 480)
        self.setMinimumSize(460, 340)
        apply_theme(self)

        layout = QVBoxLayout(self)
        heading = QLabel("Choose a save")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        instruction = QLabel(
            f"Choose an existing save to group under '{pack_name}'. This only changes "
            "ZomboidSorter’s organization; it does not change the save or its mod list."
        )
        instruction.setWordWrap(True)
        instruction.setObjectName("secondaryText")
        layout.addWidget(instruction)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter saves…")
        self.search.setAccessibleName("Filter existing saves")
        self.search.textChanged.connect(self._filter_items)
        layout.addWidget(self.search)
        self.saves_list = QListWidget()
        self.saves_list.setAccessibleName("Existing game saves")
        self.saves_list.itemSelectionChanged.connect(self._update_actions)
        self.saves_list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.saves_list, 1)
        self.status = QLabel()
        self.status.setObjectName("secondaryText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.add_button = QPushButton("Add to Pack")
        self.add_button.setObjectName("primaryAction")
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self.accept)
        buttons.addWidget(self.add_button)
        layout.addLayout(buttons)

        self._pack_name = pack_name
        for save in saves:
            try:
                owner = assignments.assigned_pack(save.key)
            except SavePackError as exc:
                self.status.setText(str(exc))
                break
            if owner and owner.casefold() == pack_name.casefold():
                continue
            label = save.label
            if owner:
                label += f" · currently in {owner}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, save.key)
            item.setToolTip(str(save.path))
            self.saves_list.addItem(item)
        self.search.setFocus()
        self._update_actions()

    @property
    def selected_key(self) -> str | None:
        item = self.saves_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _filter_items(self, text: str) -> None:
        query = text.casefold().strip()
        for index in range(self.saves_list.count()):
            item = self.saves_list.item(index)
            item.setHidden(query not in item.text().casefold())
        self._update_actions()

    def _update_actions(self) -> None:
        item = self.saves_list.currentItem()
        selected_visible = item is not None and not item.isHidden()
        self.add_button.setEnabled(selected_visible)
        if self.saves_list.count() == 0:
            self.status.setText("No other saves are available to add.")
        elif not any(
            not self.saves_list.item(index).isHidden()
            for index in range(self.saves_list.count())
        ):
            self.status.setText("No saves match this filter.")


class SavePacksDialog(QDialog):
    """Show the saves grouped under one Mod Pack and edit those app-only links."""

    def __init__(
        self,
        profile_store: ProfileStore,
        pack_name: str,
        saves_root: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._profile_store = profile_store
        self._pack_name = pack_name
        self._saves_root = saves_root
        self._assignment_store = SaveAssignmentStore(profile_store.root.parent)
        self.setWindowTitle(f"Saves · {pack_name}")
        self.resize(650, 520)
        self.setMinimumSize(520, 400)
        apply_theme(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        heading = QLabel(f"Saves for {pack_name}")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        instruction = QLabel(
            "Group existing saves under this Mod Pack. These links are stored by "
            "ZomboidSorter; game saves and their mod lists stay unchanged."
        )
        instruction.setObjectName("secondaryText")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        self.saves_list = QListWidget()
        self.saves_list.setAccessibleName(f"Saves for {pack_name}")
        self.saves_list.itemSelectionChanged.connect(self._update_actions)
        layout.addWidget(self.saves_list, 1)
        self.status = QLabel()
        self.status.setObjectName("secondaryText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        self.add_button = QPushButton("Add Existing Save…")
        self.add_button.clicked.connect(self._add_save)
        actions.addWidget(self.add_button)
        self.remove_button = QPushButton("Remove from Pack")
        self.remove_button.setToolTip(
            "Remove the app-only grouping. The save folder stays in place."
        )
        self.remove_button.clicked.connect(self._remove_selected)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

        try:
            self._saves = discover_saves(self._saves_root)
            self._load_assignments()
        except SavePackError as exc:
            self._saves = ()
            self._all_by_key: dict[str, GameSave] = {}
            self.status.setText(str(exc))
            self.add_button.setEnabled(False)
        else:
            self._refresh()

    def _load_assignments(self) -> None:
        self._assigned_keys = set(self._assignment_store.list_for_pack(self._pack_name))
        self._all_by_key = {save.key: save for save in self._saves}

    def _refresh(self, selected_key: str | None = None) -> None:
        self.saves_list.clear()
        for key in sorted(self._assigned_keys):
            save = self._all_by_key.get(key)
            if save is None:
                mode, name = key.split("/", 1)
                label = f"{name} · {mode} · folder not found"
            else:
                label = save.label
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            if save is not None:
                item.setToolTip(str(save.path))
            self.saves_list.addItem(item)
            if key == selected_key:
                self.saves_list.setCurrentItem(item)
        if not selected_key and self.saves_list.count():
            self.saves_list.setCurrentRow(0)
        if self.saves_list.count():
            self.status.setText(
                f"{self.saves_list.count()} save(s) grouped under '{self._pack_name}'."
            )
        elif self._saves:
            self.status.setText(
                "No saves are grouped under this pack yet. Choose Add Existing Save to start."
            )
        else:
            if self._saves_root.is_dir():
                self.status.setText(
                    "No game saves were found. Create a save in Project Zomboid, then reopen this window."
                )
            else:
                self.status.setText(
                    f"No Saves folder found at {self._saves_root}. Create a save in Project Zomboid, then reopen this window."
                )
        self._update_actions()

    def _add_save(self) -> None:
        try:
            dialog = SavePickerDialog(
                self._saves,
                self._assignment_store,
                self._pack_name,
                self,
            )
        except SavePackError as exc:
            QMessageBox.warning(self, "Could Not Read Save Groupings", str(exc))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_key:
            return
        key = dialog.selected_key
        try:
            owner = self._assignment_store.assigned_pack(key)
            if owner and owner.casefold() != self._pack_name.casefold():
                answer = QMessageBox.question(
                    self,
                    "Move Save to This Pack?",
                    f"Move this save from '{owner}' to '{self._pack_name}'? "
                    "Only its ZomboidSorter grouping will change.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            self._assignment_store.assign(key, self._pack_name)
            self._load_assignments()
            self._refresh(key)
        except SavePackError as exc:
            QMessageBox.warning(self, "Could Not Group Save", str(exc))

    def _remove_selected(self, _item=None) -> None:
        item = self.saves_list.currentItem()
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        try:
            self._assignment_store.unassign(key, self._pack_name)
            self._load_assignments()
            self._refresh()
        except SavePackError as exc:
            QMessageBox.warning(self, "Could Not Remove Save", str(exc))

    def _update_actions(self) -> None:
        self.remove_button.setEnabled(self.saves_list.currentItem() is not None)

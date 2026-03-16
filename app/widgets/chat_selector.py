from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QLabel,
)
from PyQt6.QtCore import Qt


class ChatSelector(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Chats")
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search chats...")
        self.search_box.textChanged.connect(self._filter_chats)
        layout.addWidget(self.search_box)

        self.chat_list = QListWidget()
        layout.addWidget(self.chat_list)

        btn_row = QHBoxLayout()
        self.btn_select_all = QPushButton("Select All")
        self.btn_deselect_all = QPushButton("Deselect All")
        self.btn_refresh = QPushButton("Refresh")
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_deselect_all.clicked.connect(self._deselect_all)

        btn_row.addWidget(self.btn_select_all)
        btn_row.addWidget(self.btn_deselect_all)
        btn_row.addWidget(self.btn_refresh)
        layout.addLayout(btn_row)

        self._all_chats: list[str] = []

    def set_chats(self, chat_names: list[str]) -> None:
        self._all_chats = list(chat_names)
        self._populate(chat_names)

    def get_selected(self) -> list[str]:
        selected = []
        for i in range(self.chat_list.count()):
            item = self.chat_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                selected.append(item.text())
        return selected

    def _populate(self, names: list[str]) -> None:
        self.chat_list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.chat_list.addItem(item)

    def _filter_chats(self, text: str) -> None:
        filtered = [c for c in self._all_chats if text.lower() in c.lower()] if text else self._all_chats
        self._populate(filtered)

    def _select_all(self) -> None:
        for i in range(self.chat_list.count()):
            item = self.chat_list.item(i)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _deselect_all(self) -> None:
        for i in range(self.chat_list.count()):
            item = self.chat_list.item(i)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

from datetime import datetime
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtGui import QTextCharFormat, QColor, QFont
from PyQt6.QtCore import Qt


class LogViewer(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header_row = QHBoxLayout()
        header = QLabel("Logs")
        header.setStyleSheet("font-weight: bold;")
        header_row.addWidget(header)
        header_row.addStretch()
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.clear)
        header_row.addWidget(self.btn_clear)
        layout.addLayout(header_row)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Consolas", 9))
        layout.addWidget(self.text_edit)

    def append(self, message: str, level: str = "INFO") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "INFO": "#d4d4d4",
            "WARN": "#f59e0b",
            "ERROR": "#ef4444",
            "SUCCESS": "#22c55e",
        }
        color = color_map.get(level, "#d4d4d4")
        self.text_edit.append(
            f'<span style="color:#888">{timestamp}</span> '
            f'<span style="color:{color}">{level:5}</span> '
            f'<span style="color:#d4d4d4">{message}</span>'
        )
        # Auto-scroll to bottom
        scrollbar = self.text_edit.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def clear(self) -> None:
        self.text_edit.clear()

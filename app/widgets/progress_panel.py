from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar


class ProgressPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Progress")
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)

        self.current_chat_label = QLabel("Idle")
        layout.addWidget(self.current_chat_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(0)  # indeterminate by default
        layout.addWidget(self.progress_bar)

        self.count_label = QLabel("Messages: 0")
        layout.addWidget(self.count_label)

        layout.addStretch()

    def set_collecting(self, chat_name: str, count: int) -> None:
        self.current_chat_label.setText(f"Collecting: {chat_name}")
        self.count_label.setText(f"Messages: {count}")
        self.progress_bar.setMaximum(0)  # indeterminate during scroll

    def set_chat_completed(self, chat_name: str, count: int) -> None:
        self.current_chat_label.setText(f"Completed: {chat_name}")
        self.count_label.setText(f"Messages: {count}")

    def set_idle(self) -> None:
        self.current_chat_label.setText("Idle")
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        self.count_label.setText("Messages: 0")

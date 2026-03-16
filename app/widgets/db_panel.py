from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout,
    QLabel, QPushButton, QHBoxLayout, QProgressBar,
)
from PyQt6.QtCore import pyqtSignal


class DatabasePanel(QWidget):
    decrypt_requested = pyqtSignal()
    wal_toggle_requested = pyqtSignal(bool)  # start/stop

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # --- DB Status Group ---
        db_group = QGroupBox("Database")
        db_layout = QFormLayout(db_group)

        self.db_path_label = QLabel("Not loaded")
        self.db_status_label = QLabel("Not decrypted")
        self.db_status_indicator = QLabel("\u25cf")
        self.db_status_indicator.setStyleSheet("color: #999; font-size: 14px;")

        status_row = QHBoxLayout()
        status_row.addWidget(self.db_status_indicator)
        status_row.addWidget(self.db_status_label)
        status_row.addStretch()

        db_layout.addRow("Path:", self.db_path_label)
        db_layout.addRow("Status:", status_row)

        self.btn_decrypt = QPushButton("Decrypt Now")
        self.btn_decrypt.clicked.connect(self.decrypt_requested)
        db_layout.addRow(self.btn_decrypt)

        layout.addWidget(db_group)

        # --- WAL Monitor Group ---
        wal_group = QGroupBox("WAL Monitor")
        wal_layout = QFormLayout(wal_group)

        self.wal_status_label = QLabel("Stopped")
        self.wal_stats_label = QLabel("")

        wal_layout.addRow("Status:", self.wal_status_label)
        wal_layout.addRow("Detected:", self.wal_stats_label)

        wal_btns = QHBoxLayout()
        self.btn_start_wal = QPushButton("Start")
        self.btn_stop_wal = QPushButton("Stop")
        self.btn_stop_wal.setEnabled(False)
        self.btn_start_wal.clicked.connect(lambda: self.wal_toggle_requested.emit(True))
        self.btn_stop_wal.clicked.connect(lambda: self.wal_toggle_requested.emit(False))
        wal_btns.addWidget(self.btn_start_wal)
        wal_btns.addWidget(self.btn_stop_wal)
        wal_layout.addRow(wal_btns)

        layout.addWidget(wal_group)

        # --- History Progress ---
        history_group = QGroupBox("History Scan")
        history_layout = QVBoxLayout(history_group)

        self.history_progress = QProgressBar()
        self.history_progress.setVisible(False)
        self.history_label = QLabel("")
        history_layout.addWidget(self.history_progress)
        history_layout.addWidget(self.history_label)

        layout.addWidget(history_group)
        layout.addStretch()

    def set_db_status(self, decrypted: bool, db_count: int = 0, msg_count: int = 0) -> None:
        if decrypted:
            self.db_status_indicator.setStyleSheet("color: #22c55e; font-size: 14px;")
            self.db_status_label.setText(f"Decrypted ({db_count} DBs, {msg_count:,} messages)")
        else:
            self.db_status_indicator.setStyleSheet("color: #999; font-size: 14px;")
            self.db_status_label.setText("Not decrypted")

    def set_db_path(self, path: str) -> None:
        self.db_path_label.setText(path)

    def set_wal_status(self, running: bool, changes: int = 0, messages: int = 0) -> None:
        if running:
            self.wal_status_label.setText("Running")
            self.btn_start_wal.setEnabled(False)
            self.btn_stop_wal.setEnabled(True)
        else:
            self.wal_status_label.setText("Stopped")
            self.btn_start_wal.setEnabled(True)
            self.btn_stop_wal.setEnabled(False)
        self.wal_stats_label.setText(f"{changes} changes, {messages:,} messages")

    def set_history_progress(self, current: int, total: int) -> None:
        self.history_progress.setVisible(True)
        self.history_progress.setMaximum(total)
        self.history_progress.setValue(current)
        self.history_label.setText(f"{current:,} / {total:,} messages")

    def set_history_complete(self, total: int) -> None:
        self.history_progress.setVisible(False)
        self.history_label.setText(f"Complete: {total:,} messages forwarded")

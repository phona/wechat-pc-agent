from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton


class ControlPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.btn_connect = QPushButton("Connect WeChat")
        self.btn_start = QPushButton("Start")
        self.btn_collect_history = QPushButton("Collect History")
        self.btn_stop = QPushButton("Stop")
        self.btn_settings = QPushButton("Settings")

        self.btn_start.setEnabled(False)
        self.btn_collect_history.setEnabled(False)
        self.btn_stop.setEnabled(False)

        for btn in (self.btn_connect, self.btn_start, self.btn_collect_history,
                     self.btn_stop, self.btn_settings):
            layout.addWidget(btn)

        layout.addStretch()

    def set_connected(self, connected: bool) -> None:
        self.btn_connect.setEnabled(not connected)
        self.btn_connect.setText("Connected" if connected else "Connect WeChat")
        self.btn_start.setEnabled(connected)
        self.btn_collect_history.setEnabled(connected)

    def set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_collect_history.setEnabled(not running)
        self.btn_stop.setEnabled(running)

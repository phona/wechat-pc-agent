import sys
import logging

from PyQt6.QtWidgets import QApplication

from config import AppConfig
from app.window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    config = AppConfig.load()

    app = QApplication(sys.argv)
    app.setApplicationName("WeChat Agent")
    app.setStyle("Fusion")

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

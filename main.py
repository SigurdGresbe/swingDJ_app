from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QFont, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from controller import AppController
from table_model import SongTableModel


APP_DIR = Path(__file__).resolve().parent


def main() -> int:
    QCoreApplication.setOrganizationName("SpareTime")
    QCoreApplication.setApplicationName("SpareTime Studio")
    QQuickStyle.setStyle("Basic")

    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI Variable Text", 10))
    app.setWindowIcon(QIcon(str(APP_DIR / "assets" / "app-icon.svg")))

    table_model = SongTableModel()
    controller = AppController(table_model)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("tableModel", table_model)
    engine.rootContext().setContextProperty("controller", controller)
    engine.load(QUrl.fromLocalFile(str(APP_DIR / "qml" / "Main.qml")))

    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

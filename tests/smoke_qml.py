from __future__ import annotations

import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from PySide6.QtCore import QMetaObject, QObject, QTimer, QUrl
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from controller import AppController
from config import GENERATED_DIR
from table_model import SongTableModel


def main() -> int:
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    app.setFont(QFont("Segoe UI Variable Text", 10))

    model = SongTableModel()
    controller = AppController(model)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("tableModel", model)
    engine.rootContext().setContextProperty("controller", controller)
    engine.load(QUrl.fromLocalFile(str(PROJECT_DIR / "qml" / "Main.qml")))
    if not engine.rootObjects():
        print("QML_LOAD_FAILED")
        return 1

    window = engine.rootObjects()[0]
    attempts = 0

    def capture_when_ready() -> None:
        nonlocal attempts
        attempts += 1
        if controller.busy and attempts < 25:
            QTimer.singleShot(200, capture_when_ready)
            return
        pages = [
            ("library", 0),
            ("merge", 1),
            ("spotify", 2),
            ("spotify_playlist", 2),
        ]
        saved_images: list[bool] = []

        def capture_page(index: int) -> None:
            if index >= len(pages):
                drawer = window.findChild(QObject, "settingsDrawer")
                if drawer is not None:
                    QMetaObject.invokeMethod(drawer, "open")

                def capture_settings() -> None:
                    path = GENERATED_DIR / "qml_smoke_settings.png"
                    saved_images.append(window.grabWindow().save(str(path)))
                    print(
                        f"QML_OK rows={model.rowCount()} columns={model.columnCount()} "
                        f"window={window.width()}x{window.height()} screenshots={all(saved_images)}"
                    )
                    controller.shutdown(window.width(), window.height())
                    app.quit()

                QTimer.singleShot(250, capture_settings)
                return

            name, page = pages[index]
            if name == "spotify_playlist":
                controller._spotify_view = {
                    "mode": "playlist",
                    "title": "Blues & Boogie",
                    "reference": "spotify:playlist:preview",
                }
                controller._spotify_results = [
                    {
                        "type": "track",
                        "name": "Before He Cheats",
                        "subtitle": "Carrie Underwood",
                        "extra": "Some Hearts",
                        "uri": "spotify:track:preview-1",
                    },
                    {
                        "type": "track",
                        "name": "Black Velvet",
                        "subtitle": "Alannah Myles",
                        "extra": "Alannah Myles",
                        "uri": "spotify:track:preview-2",
                    },
                ]
                controller.spotifyChanged.emit()
            window.setProperty("currentPage", page)

            def save_page() -> None:
                path = GENERATED_DIR / f"qml_smoke_{name}.png"
                saved_images.append(window.grabWindow().save(str(path)))
                capture_page(index + 1)

            QTimer.singleShot(250, save_page)

        capture_page(0)

    QTimer.singleShot(500, capture_when_ready)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

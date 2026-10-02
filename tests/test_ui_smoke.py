from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import app as metalbox_app
from metalbox_core import MetalboxStore


class UiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_main_window_constructs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "metalbox-smoke.sqlite3"
            store = MetalboxStore(db_path)
            store.seed_development_data()
            store.ensure_development_progress_seeded()

            config = metalbox_app.ClientConfig(
                server_ip="127.0.0.1",
                station_name="TEST — Development",
                inactivity_seconds=90,
                configured=True,
                test_mode=True,
            )

            window = metalbox_app.MainWindow(config, store)
            self.assertEqual(window.windowTitle(), f"Metalbox {metalbox_app.APP_VERSION}")
            window.close()

    def test_order_editor_dialog_constructs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "metalbox-editor.sqlite3"
            store = MetalboxStore(db_path)
            store.seed_development_data()
            store.ensure_development_progress_seeded()

            dialog = metalbox_app.OrderEditorDialog(store)
            self.assertEqual(len(dialog.item_rows), 1)
            dialog.close()

            edit_dialog = metalbox_app.OrderEditorDialog(
                store,
                order_code="ZL-740",
            )
            self.assertTrue(edit_dialog.structure_locked)
            self.assertGreaterEqual(len(edit_dialog.item_rows), 1)
            edit_dialog.close()

    def test_session_workers_dialog_constructs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "metalbox-session-ui.sqlite3"
            store = MetalboxStore(db_path)
            store.seed_development_data()
            store.ensure_development_progress_seeded()
            store.start_production_session(
                "ZL-740",
                "Zgrzewarki",
                ["Dawid", "Marek"],
            )

            dialog = metalbox_app.SessionWorkersDialog(
                store,
                "ZL-740",
                "Zgrzewarki",
            )
            self.assertEqual(dialog.table.rowCount(), 2)
            dialog.close()

    def test_update_checklist_dialog_constructs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            original = metalbox_app.DEV_UPDATE_STATE_FILE
            try:
                metalbox_app.DEV_UPDATE_STATE_FILE = Path(temp) / "update_state.json"
                metalbox_app.save_dev_update_state(
                    {
                        "schema": 2,
                        "status": "updated",
                        "old_version": "0.1.7",
                        "new_version": metalbox_app.APP_VERSION,
                        "title": "Test aktualizacji",
                        "description": "Sprawdzenie okna.",
                        "popup_shown": False,
                        "changes": [
                            {
                                "id": "orders-open",
                                "text": "Otwórz ekran Zlecenia",
                                "trigger": "page:orders",
                                "checked": False,
                                "checked_at": None,
                                "note": "",
                                "problem": False,
                            }
                        ],
                    }
                )

                dialog = metalbox_app.UpdateChecklistDialog()
                self.assertFalse(dialog.isModal())
                self.assertEqual(len(dialog.rows), 1)
                dialog.close()
            finally:
                metalbox_app.DEV_UPDATE_STATE_FILE = original


if __name__ == "__main__":
    unittest.main()

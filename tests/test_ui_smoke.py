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

    def test_quality_report_dialog_constructs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "metalbox-quality-ui.sqlite3"
            store = MetalboxStore(db_path)
            store.seed_development_data()
            store.ensure_development_progress_seeded()
            store.start_production_session(
                "ZL-740",
                "Zgrzewarki",
                ["Dawid"],
            )

            dialog = metalbox_app.QualityReportDialog(
                store,
                code="ZL-740",
                department="Zgrzewarki",
            )
            self.assertEqual(dialog.order_combo.currentText(), "ZL-740")
            self.assertGreater(dialog.item_combo.count(), 1)
            dialog.item_combo.setCurrentIndex(1)
            self.qt_app.processEvents()
            self.assertIsNotNone(dialog._selected_item_id())
            self.assertEqual(dialog.department_combo.currentText(), "Zgrzewarki")
            self.assertTrue(dialog.quantity_spin.isEnabled())
            dialog.close()

    def test_worker_and_manager_views_are_separated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            original_view_file = metalbox_app.DEV_VIEW_STATE_FILE
            try:
                metalbox_app.DEV_VIEW_STATE_FILE = Path(temp) / "dev_view.json"
                metalbox_app.DevViewState(
                    role="PRACOWNIK",
                    department="Zgrzewarki",
                ).save()

                db_path = Path(temp) / "role-view.sqlite3"
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
                window.resize(1400, 850)
                window.show()
                self.qt_app.processEvents()
                window._apply_role_view()
                self.qt_app.processEvents()

                self.assertFalse(window.management_frame.isVisible())
                self.assertTrue(
                    window.department_buttons["Zgrzewarki"].isVisible()
                )
                self.assertFalse(
                    window.department_buttons["Malarnia"].isVisible()
                )

                window.apply_dev_view_state("KIEROWNIK", "Zgrzewarki")
                self.qt_app.processEvents()

                self.assertTrue(window.management_frame.isVisible())
                self.assertTrue(
                    window.department_buttons["Malarnia"].isVisible()
                )
                window.close()
            finally:
                metalbox_app.DEV_VIEW_STATE_FILE = original_view_file

    def test_update_panel_overlay_does_not_change_main_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            original = metalbox_app.DEV_UPDATE_STATE_FILE
            try:
                metalbox_app.DEV_UPDATE_STATE_FILE = Path(temp) / "update_state.json"
                metalbox_app.save_dev_update_state(
                    {
                        "schema": 2,
                        "status": "updated",
                        "old_version": "0.1.13",
                        "new_version": metalbox_app.APP_VERSION,
                        "title": "Test overlay",
                        "description": "Panel nie może zmieniać layoutu.",
                        "ready_for_next": False,
                        "changes": [
                            {
                                "id": "overlay",
                                "text": "Panel nie zmienia layoutu",
                                "trigger": "page:orders",
                                "checked": False,
                                "checked_at": None,
                                "note": "",
                                "problem": False,
                            }
                        ],
                    }
                )

                db_path = Path(temp) / "overlay.sqlite3"
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
                window.resize(1400, 850)
                window.show()
                self.qt_app.processEvents()

                before = window.stack.geometry()
                window._setup_update_test_panel()
                self.qt_app.processEvents()
                after = window.stack.geometry()

                self.assertEqual(before, after)
                self.assertIs(window.update_test_panel.parent(), window)
                self.assertTrue(window.update_test_panel.isVisible())
                window.close()
            finally:
                metalbox_app.DEV_UPDATE_STATE_FILE = original

    def test_rework_quality_ui_constructs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "metalbox-rework-ui.sqlite3"
            store = MetalboxStore(db_path)
            store.seed_development_data()
            store.ensure_development_progress_seeded()
            session = store.start_production_session(
                "ZL-740",
                "Zgrzewarki",
                ["Dawid"],
            )

            dialog = metalbox_app.QualityReportDialog(
                store,
                code="ZL-740",
                department="Zgrzewarki",
            )
            self.assertGreater(dialog.item_combo.count(), 1)
            dialog.item_combo.setCurrentIndex(1)
            self.qt_app.processEvents()
            self.assertIsNotNone(dialog._selected_item_id())
            self.assertEqual(dialog.department_combo.currentText(), "Zgrzewarki")

            dialog.kind_combo.setCurrentText("POPRAWKA")
            dialog._refresh_context()
            self.assertFalse(dialog.rework_target_combo.isHidden())
            self.assertGreater(dialog.rework_target_combo.count(), 0)
            self.assertIn(
                "Giętarki",
                [
                    dialog.rework_target_combo.itemText(i)
                    for i in range(dialog.rework_target_combo.count())
                ],
            )

            target_index = dialog.rework_target_combo.findData("Giętarki")
            self.assertGreaterEqual(target_index, 0)
            dialog.rework_target_combo.setCurrentIndex(target_index)
            self.qt_app.processEvents()
            self.assertTrue(dialog.save_button.isEnabled())
            dialog.close()

            store.report_quality_quantity(
                "ZL-740",
                "Zgrzewarki",
                "POPRAWKA",
                1,
                reason="Test UI poprawki",
                session_id=int(session["id"]),
                rework_target_department="Giętarki",
            )

            page = metalbox_app.QualityPage(lambda: None, store)
            page.refresh_data()
            self.assertGreaterEqual(page.rework_table.rowCount(), 1)
            page.close()

    def test_update_check_auto_marks_matching_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            original = metalbox_app.DEV_UPDATE_STATE_FILE
            try:
                metalbox_app.DEV_UPDATE_STATE_FILE = Path(temp) / "update_state.json"
                metalbox_app.save_dev_update_state(
                    {
                        "schema": 2,
                        "status": "updated",
                        "old_version": "0.1.13.2",
                        "new_version": metalbox_app.APP_VERSION,
                        "title": "Automatyczny analizator",
                        "description": "Test triggera.",
                        "ready_for_next": False,
                        "changes": [
                            {
                                "id": "auto",
                                "text": "Automatyczny punkt",
                                "trigger": "test:auto",
                                "checked": False,
                                "checked_at": None,
                                "note": "",
                                "problem": False,
                            }
                        ],
                    }
                )

                changed = metalbox_app.mark_update_check("test:auto")
                self.assertTrue(changed)

                state = metalbox_app.load_dev_update_state()
                self.assertTrue(state["changes"][0]["checked"])
                self.assertIsNotNone(state["changes"][0]["checked_at"])
            finally:
                metalbox_app.DEV_UPDATE_STATE_FILE = original

    def test_update_age_formats_seconds_minutes_and_hours(self) -> None:
        now = metalbox_app.datetime.fromisoformat("2026-10-02T10:00:00+00:00")
        self.assertEqual(
            metalbox_app._format_elapsed_update_age(
                "2026-10-02T09:59:42+00:00", now=now
            ),
            "18 s temu",
        )
        self.assertEqual(
            metalbox_app._format_elapsed_update_age(
                "2026-10-02T09:58:30+00:00", now=now
            ),
            "1 min temu",
        )
        self.assertEqual(
            metalbox_app._format_elapsed_update_age(
                "2026-10-02T06:00:00+00:00", now=now
            ),
            "4 godz. temu",
        )

    def test_department_page_shows_separate_order_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "department-items.sqlite3"
            store = MetalboxStore(db_path)
            self.assertTrue(store.seed_development_data())

            created = store.get_order("ZL-740")
            self.assertIsNotNone(created)
            item_ids = {int(item["id"]) for item in created["items"]}

            page = metalbox_app.DepartmentPage(
                "Zgrzewarki",
                lambda: None,
                store,
            )

            rows = [
                row
                for row in page.queue_rows
                if row["code"] == "ZL-740"
            ]
            self.assertEqual(len(rows), 5)
            self.assertEqual(
                {int(row["order_item_id"]) for row in rows},
                item_ids,
            )

            labels = {
                label.text()
                for label in page.findChildren(metalbox_app.QLabel)
            }
            self.assertTrue(
                any("1.435.135" in text and "SC600 RP Sorta" in text for text in labels)
            )
            self.assertTrue(
                any("1.325.68" in text and "SC400 RP Sorta" in text for text in labels)
            )

            start_buttons = [
                button
                for button in page.findChildren(metalbox_app.QPushButton)
                if (
                    button.text() == "Rozpocznij"
                    and button.property("orderCode") == "ZL-740"
                )
            ]
            self.assertEqual(len(start_buttons), 5)
            self.assertTrue(any(button.isEnabled() for button in start_buttons))
            page.close()

    def test_update_checklist_panel_constructs_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            original = metalbox_app.DEV_UPDATE_STATE_FILE
            try:
                metalbox_app.DEV_UPDATE_STATE_FILE = Path(temp) / "update_state.json"
                metalbox_app.save_dev_update_state(
                    {
                        "schema": 2,
                        "status": "updated",
                        "old_version": "0.1.12",
                        "new_version": metalbox_app.APP_VERSION,
                        "title": "Test aktualizacji",
                        "description": "Sprawdzenie panelu.",
                        "ready_for_next": False,
                        "changes": [
                            {
                                "id": "orders-open",
                                "text": "Otwórz ekran Zlecenia",
                                "trigger": "page:orders",
                                "checked": False,
                                "checked_at": None,
                                "note": "",
                                "problem": False,
                            },
                            {
                                "id": "problem",
                                "text": "Wpisz uwagę",
                                "trigger": "update_panel:note",
                                "checked": False,
                                "checked_at": None,
                                "note": "testowa uwaga",
                                "problem": True,
                            },
                        ],
                    }
                )

                panel = metalbox_app.UpdateChecklistPanel()
                self.assertEqual(len(panel.rows), 2)
                self.assertIn("uwagi 1", panel._progress_text())

                state = metalbox_app.load_dev_update_state()
                self.assertEqual(
                    state["changes"][1]["note"],
                    "testowa uwaga",
                )
                panel.close()
            finally:
                metalbox_app.DEV_UPDATE_STATE_FILE = original


if __name__ == "__main__":
    unittest.main()

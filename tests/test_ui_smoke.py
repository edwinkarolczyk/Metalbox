from __future__ import annotations

import os
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import app as metalbox_app
from metalbox_core import MetalboxStore


class UiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_product_hints_resource_is_available(self) -> None:
        self.assertTrue(
            metalbox_app.PRODUCT_HINTS_FILE.exists(),
            str(metalbox_app.PRODUCT_HINTS_FILE),
        )
        entries = [
            line.strip()
            for line in metalbox_app.PRODUCT_HINTS_FILE.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        self.assertEqual(len(entries), 611)
        self.assertIn("1.437.68 TESAM", entries)

    def test_product_editor_updates_existing_card(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MetalboxStore(Path(temp) / "product-edit-ui.sqlite3")
            store.create_product(
                symbol="EDIT.UI",
                name="Nazwa stara",
                status="DO WERYFIKACJI",
            )
            product = store.get_product("EDIT.UI")
            self.assertIsNotNone(product)

            dialog = metalbox_app.ProductEditorDialog(
                store,
                product=product,
            )
            self.assertTrue(dialog.symbol_edit.isReadOnly())
            dialog.name_edit.setText("Nazwa poprawiona")
            dialog.material_edit.setText("DC01")
            dialog.status_combo.setCurrentText("AKTYWNY")
            dialog._save()
            self.qt_app.processEvents()

            updated = store.get_product("EDIT.UI")
            self.assertIsNotNone(updated)
            self.assertEqual(updated["symbol"], "EDIT.UI")
            self.assertEqual(updated["name"], "Nazwa poprawiona")
            self.assertEqual(updated["material"], "DC01")
            self.assertEqual(updated["status"], "AKTYWNY")
            dialog.close()

    def test_product_technology_page_constructs_and_refreshes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MetalboxStore(Path(temp) / "technology-ui.sqlite3")
            store.create_product(symbol="TECH.UI", name="Produkt UI")
            store.add_product_operation(
                "TECH.UI",
                department="Laser",
                operation_name="Cięcie",
                setup_minutes=20,
                minutes_per_unit=0.5,
            )
            store.add_product_operation(
                "TECH.UI",
                department="Giętarki",
                operation_name="Gięcie",
                minutes_per_unit=0.25,
            )

            page = metalbox_app.ProductDetailPage(lambda: None, store)
            page.set_product("TECH.UI")
            page._show_tab("Technologia")
            self.qt_app.processEvents()

            self.assertFalse(page.data_panel.isVisible())
            self.assertFalse(page.bom_panel.isVisible())
            self.assertTrue(page.technology_panel.isVisible() or not page.isVisible())
            self.assertEqual(page.operation_table.rowCount(), 2)
            self.assertEqual(page.operation_table.item(0, 1).text(), "Laser")
            self.assertEqual(page.operation_table.item(1, 1).text(), "Giętarki")
            self.assertEqual(page.operation_table.item(0, 2).text(), "Cięcie")
            self.assertEqual(page.operation_table.item(0, 3).text(), "20 min")
            self.assertEqual(page.operation_table.item(0, 4).text(), "0.5")
            page.close()

    def test_product_bom_page_constructs_and_refreshes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MetalboxStore(Path(temp) / "bom-ui.sqlite3")
            store.create_product(symbol="PARENT.UI", name="Produkt UI")
            store.create_product(
                symbol="SEMI.UI",
                name="Półprodukt UI",
                kind="PÓŁPRODUKT",
            )
            store.add_product_bom_item(
                "PARENT.UI",
                item_type="PÓŁPRODUKT",
                symbol="SEMI.UI",
                name="Półprodukt UI",
                quantity_per_set=2,
                unit="szt.",
            )

            page = metalbox_app.ProductDetailPage(lambda: None, store)
            page.set_product("PARENT.UI")
            page._show_tab("BOM")
            self.qt_app.processEvents()

            self.assertTrue(page.bom_panel.isVisible() or not page.isVisible())
            self.assertFalse(page.data_panel.isVisible())
            self.assertEqual(page.bom_table.rowCount(), 1)
            self.assertEqual(page.bom_table.item(0, 2).text(), "SEMI.UI")
            self.assertEqual(page.bom_table.item(0, 4).text(), "2")
            self.assertEqual(page.bom_table.item(0, 6).text(), "Karta produktu")
            open_button = page.bom_table.cellWidget(0, 7)
            self.assertIsNotNone(open_button)
            self.assertEqual(open_button.text(), "Otwórz półprodukt")
            self.assertTrue(page.add_bom_button.isEnabled())

            open_button.click()
            self.qt_app.processEvents()
            self.assertEqual(page.symbol, "SEMI.UI")
            self.assertEqual(page.current_product["kind"], "PÓŁPRODUKT")
            self.assertTrue(page.data_panel.isVisible() or not page.isVisible())
            page.close()

    def test_plan_approval_dialog_shows_matches_and_accepts_without_orders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MetalboxStore(Path(temp) / "plan-approval-ui.sqlite3")
            store.create_product(symbol="KNOWN.UI", name="Znany produkt")
            snapshot = store.create_plan_snapshot(
                source_name="Plan Produkcji 2026.xlsx",
                snapshot_path="snapshot-ui.xlsx",
                sha256="ui-snapshot",
                size_bytes=123,
                sheet_name="PLAN 2026",
                header_row=1,
                rows=[
                    {
                        "row_key": "zl-ui|known.ui|znany produkt#1",
                        "row_no": 2,
                        "order_code": "ZL-UI",
                        "symbol": "KNOWN.UI",
                        "name": "Znany produkt",
                        "quantity": 10.0,
                        "shipping": "20.10",
                        "ral": "9011",
                    },
                    {
                        "row_key": "zl-ui2|unknown.ui|obcy produkt#1",
                        "row_no": 3,
                        "order_code": "ZL-UI2",
                        "symbol": "UNKNOWN.UI",
                        "name": "Obcy produkt",
                        "quantity": 5.0,
                        "shipping": "21.10",
                        "ral": "7042",
                    },
                ],
            )

            dialog = metalbox_app.PlanApprovalDialog(
                store,
                int(snapshot["id"]),
            )
            self.qt_app.processEvents()

            self.assertEqual(dialog.table.rowCount(), 2)
            statuses = {
                dialog.table.item(row, 7).text()
                for row in range(dialog.table.rowCount())
            }
            self.assertEqual(statuses, {"DOPASOWANY", "DO WERYFIKACJI"})
            self.assertTrue(dialog.accept_button.isEnabled())

            with patch.object(
                metalbox_app.QMessageBox,
                "question",
                return_value=metalbox_app.QMessageBox.Yes,
            ), patch.object(
                metalbox_app.QMessageBox,
                "information",
                return_value=metalbox_app.QMessageBox.Ok,
            ):
                dialog._accept_changes()

            self.assertIsNotNone(dialog.accepted_summary)
            self.assertEqual(dialog.accepted_summary["row_count"], 2)
            self.assertFalse(dialog.accepted_summary["orders_changed"])
            self.assertEqual(len(store.list_accepted_plan_items()), 2)
            dialog.close()

    def test_plan_bom_requirements_dialog_shows_recursive_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MetalboxStore(Path(temp) / "plan-bom-ui.sqlite3")
            store.create_product(symbol="ROOT.UI", name="Produkt")
            store.create_product(
                symbol="SEMI.UI2",
                name="Półprodukt",
                kind="PÓŁPRODUKT",
            )
            store.add_product_bom_item(
                "ROOT.UI",
                item_type="PÓŁPRODUKT",
                symbol="SEMI.UI2",
                name="Półprodukt",
                quantity_per_set=2,
                unit="szt.",
            )
            store.add_product_bom_item(
                "SEMI.UI2",
                item_type="MATERIAŁ",
                symbol="MAT.UI",
                name="Materiał",
                quantity_per_set=0.5,
                unit="kg",
            )
            snapshot = store.create_plan_snapshot(
                source_name="Plan Produkcji 2026.xlsx",
                snapshot_path="snapshot-bom-ui.xlsx",
                sha256="bom-ui",
                size_bytes=123,
                sheet_name="PLAN 2026",
                header_row=1,
                rows=[
                    {
                        "row_key": "zl-ui|root.ui|produkt#1",
                        "row_no": 2,
                        "order_code": "ZL-UI",
                        "symbol": "ROOT.UI",
                        "name": "Produkt",
                        "quantity": 10.0,
                        "shipping": "20.10",
                        "ral": "9011",
                    }
                ],
            )
            store.accept_plan_snapshot(int(snapshot["id"]))
            summary = store.rebuild_accepted_plan_requirements()

            dialog = metalbox_app.PlanBomRequirementsDialog(
                store,
                summary,
            )
            self.qt_app.processEvents()

            self.assertEqual(dialog.table.rowCount(), 2)
            self.assertEqual(dialog.table.item(0, 5).text(), "SEMI.UI2 • Półprodukt")
            self.assertEqual(dialog.table.item(0, 6).text(), "20")
            self.assertEqual(dialog.table.item(0, 8).text(), "POWIĄZANY")
            self.assertEqual(dialog.table.item(1, 5).text(), "MAT.UI • Materiał")
            self.assertEqual(dialog.table.item(1, 6).text(), "10")
            self.assertEqual(dialog.table.item(1, 7).text(), "kg")
            self.assertEqual(dialog.table.item(1, 8).text(), "TYLKO BOM")
            dialog.close()

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
            self.assertIsNone(dialog.item_rows[0]["id"])
            self.assertTrue(dialog.item_rows[0]["duplicate"].isEnabled())
            dialog.close()

            created = store.create_order(
                code="ZL-UI-18",
                client="Test",
                deadline="2026-11-10",
                priority="NORMALNY",
                status="NOWE",
                items=[
                    {"symbol": "A", "name": "Pierwszy", "quantity": 10},
                    {"symbol": "B", "name": "Drugi", "quantity": 8},
                ],
            )
            first_id = int(created["items"][0]["id"])
            store.start_production_session(
                "ZL-UI-18",
                "Laser",
                ["Dawid"],
                order_item_id=first_id,
            )

            edit_dialog = metalbox_app.OrderEditorDialog(
                store,
                order_code="ZL-UI-18",
            )
            self.assertEqual(len(edit_dialog.item_rows), 2)

            started_row = edit_dialog.item_rows[0]
            free_row = edit_dialog.item_rows[1]

            self.assertTrue(started_row["started"])
            self.assertFalse(started_row["symbol"].isEnabled())
            self.assertFalse(started_row["name"].isEnabled())
            self.assertTrue(started_row["quantity"].isEnabled())
            self.assertFalse(started_row["remove"].isEnabled())
            self.assertTrue(started_row["duplicate"].isEnabled())

            self.assertFalse(free_row["started"])
            self.assertTrue(free_row["symbol"].isEnabled())
            self.assertTrue(free_row["name"].isEnabled())
            self.assertTrue(free_row["quantity"].isEnabled())
            self.assertTrue(free_row["remove"].isEnabled())
            self.assertTrue(edit_dialog.add_item_button.isEnabled())
            edit_dialog.close()

    def test_employees_page_uses_database_and_shows_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "employees-ui.sqlite3"
            store = MetalboxStore(db_path)
            store.seed_development_data()
            store.ensure_development_progress_seeded()
            store.ensure_development_employees_seeded()

            order = store.create_order(
                code="ZL-UI-WORKER",
                client="Test obsady",
                deadline="2026-11-30",
                priority="NORMALNY",
                status="NOWE",
                items=[
                    {
                        "symbol": "UI-W",
                        "name": "Test pracownika",
                        "quantity": 5,
                    }
                ],
            )
            item_id = int(order["items"][0]["id"])
            store.start_production_session(
                "ZL-UI-WORKER",
                "Laser",
                ["Dawid"],
                order_item_id=item_id,
            )

            page = metalbox_app.EmployeesPage(lambda: None, store)
            self.assertGreaterEqual(page.table.rowCount(), 3)

            rows = [
                [
                    page.table.item(r, c).text()
                    for c in range(page.table.columnCount())
                    if page.table.item(r, c) is not None
                ]
                for r in range(page.table.rowCount())
            ]
            dawid_row = next(row for row in rows if row and row[0] == "Dawid")
            self.assertTrue(any("ZL-UI-WORKER" in value for value in dawid_row))
            self.assertGreaterEqual(page.history_table.rowCount(), 1)
            page.close()

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
            store.ensure_development_employees_seeded()
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

    def test_quality_dialog_limits_reporter_to_current_session_crew(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "quality-reporter-ui.sqlite3"
            store = MetalboxStore(db_path)
            store.seed_development_data()
            store.ensure_development_progress_seeded()
            store.ensure_development_employees_seeded()

            order = store.get_order("ZL-740")
            self.assertIsNotNone(order)
            selected = next(
                item
                for item in order["items"]
                if store.get_item_department_capacity(
                    "ZL-740",
                    int(item["id"]),
                    "Zgrzewarki",
                )["available_now"] > 0
            )
            item_id = int(selected["id"])
            store.start_production_session(
                "ZL-740",
                "Zgrzewarki",
                ["Dawid", "Marek"],
                order_item_id=item_id,
            )

            dialog = metalbox_app.QualityReportDialog(
                store,
                code="ZL-740",
                department="Zgrzewarki",
                order_item_id=item_id,
            )
            self.qt_app.processEvents()

            reporters = [
                dialog.reporter_combo.itemText(index)
                for index in range(1, dialog.reporter_combo.count())
            ]
            self.assertEqual(set(reporters), {"Dawid", "Marek"})
            self.assertIn("obsada: Dawid, Marek", dialog.session_label.text())
            self.assertNotIn("Sebastian", reporters)
            self.assertGreater(dialog.reason_combo.count(), 1)
            self.assertFalse(dialog.save_button.isEnabled())
            dawid_index = dialog.reporter_combo.findText("Dawid")
            self.assertGreaterEqual(dawid_index, 1)
            dialog.reporter_combo.setCurrentIndex(dawid_index)
            self.qt_app.processEvents()
            self.assertTrue(dialog.save_button.isEnabled())
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

                # Pracownik widzi wszystkie działy w stałym układzie.
                for department in metalbox_app.DEPARTMENTS:
                    self.assertTrue(
                        window.department_buttons[department].isVisible()
                    )

                assigned = window.department_buttons["Zgrzewarki"]
                locked = window.department_buttons["Malarnia"]
                self.assertTrue(assigned.isEnabled())
                self.assertEqual(
                    assigned.objectName(),
                    "departmentButtonAssigned",
                )
                self.assertFalse(locked.isEnabled())
                self.assertEqual(
                    locked.objectName(),
                    "departmentButtonLocked",
                )

                window.apply_dev_view_state("KIEROWNIK", "Zgrzewarki")
                self.qt_app.processEvents()

                self.assertTrue(window.management_frame.isVisible())
                self.assertTrue(
                    window.department_buttons["Malarnia"].isVisible()
                )
                self.assertTrue(
                    all(
                        button.isEnabled()
                        for button in window.department_buttons.values()
                    )
                )
                self.assertTrue(
                    all(
                        button.objectName() == "departmentButton"
                        for button in window.department_buttons.values()
                    )
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
            store.ensure_development_employees_seeded()

            order = store.get_order("ZL-740")
            self.assertIsNotNone(order)
            selected = next(
                item
                for item in order["items"]
                if store.get_item_department_capacity(
                    "ZL-740",
                    int(item["id"]),
                    "Zgrzewarki",
                )["available_now"] > 0
            )
            item_id = int(selected["id"])
            session = store.start_production_session(
                "ZL-740",
                "Zgrzewarki",
                ["Dawid"],
                order_item_id=item_id,
            )

            dialog = metalbox_app.QualityReportDialog(
                store,
                code="ZL-740",
                department="Zgrzewarki",
                order_item_id=item_id,
            )
            self.assertGreater(dialog.item_combo.count(), 1)
            self.qt_app.processEvents()
            self.assertEqual(dialog._selected_item_id(), item_id)
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

    def test_pending_update_cannot_look_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            original = metalbox_app.DEV_UPDATE_STATE_FILE
            try:
                metalbox_app.DEV_UPDATE_STATE_FILE = Path(temp) / "update_state.json"
                metalbox_app.save_dev_update_state(
                    {
                        "schema": 2,
                        "status": "updated",
                        "old_version": "0.1.24.1",
                        "new_version": metalbox_app.APP_VERSION,
                        "title": "Test blokady",
                        "description": "Oczekujący punkt blokuje odbiór.",
                        "ready_for_next": True,
                        "changes": [
                            {
                                "id": "done",
                                "text": "Punkt wykonany",
                                "trigger": "test:done",
                                "checked": True,
                                "checked_at": "2026-10-05T08:00:00",
                                "note": "",
                                "problem": False,
                            },
                            {
                                "id": "pending",
                                "text": "Punkt oczekujący",
                                "trigger": "test:pending",
                                "checked": False,
                                "checked_at": None,
                                "note": "",
                                "problem": False,
                            },
                        ],
                    }
                )

                report = metalbox_app.format_update_test_report(
                    metalbox_app.load_dev_update_state()
                )
                self.assertIn("Gotowy na następne zmiany: NIE", report)

                state = metalbox_app.load_dev_update_state()
                state["ready_for_next"] = False
                metalbox_app.save_dev_update_state(state)

                panel = metalbox_app.UpdateChecklistPanel()
                self.assertFalse(panel.ready_btn.isEnabled())
                panel.close()
            finally:
                metalbox_app.DEV_UPDATE_STATE_FILE = original

    def test_finish_cycle_copies_final_report_and_ignores_control_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            original = metalbox_app.DEV_UPDATE_STATE_FILE
            try:
                metalbox_app.DEV_UPDATE_STATE_FILE = Path(temp) / "update_state.json"
                metalbox_app.save_dev_update_state(
                    {
                        "schema": 2,
                        "status": "updated",
                        "old_version": "0.1.18",
                        "new_version": metalbox_app.APP_VERSION,
                        "title": "Hotfix raportu",
                        "description": "Test końcowego raportu.",
                        "ready_for_next": False,
                        "changes": [
                            {
                                "id": "real",
                                "text": "Prawdziwy test funkcji",
                                "trigger": "test:real",
                                "checked": True,
                                "checked_at": "2026-10-02T11:00:00",
                                "note": "",
                                "problem": False,
                            },
                            {
                                "id": "copy",
                                "text": "Kopiuj raport",
                                "trigger": "update_panel:copy_report",
                                "checked": True,
                                "checked_at": "2026-10-02T11:01:00",
                                "note": "",
                                "problem": False,
                            },
                            {
                                "id": "ready",
                                "text": "Gotowy na następne zmiany",
                                "trigger": "update_panel:ready",
                                "checked": False,
                                "checked_at": None,
                                "note": "",
                                "problem": False,
                            },
                        ],
                    }
                )

                panel = metalbox_app.UpdateChecklistPanel()
                self.assertEqual(panel._progress_text(), "OK 1/1 • oczekuje 0 • uwagi 0")

                report_before = metalbox_app.format_update_test_report(
                    metalbox_app.load_dev_update_state()
                )
                self.assertIn("Podsumowanie: 1/1 OK", report_before)
                self.assertNotIn("Kopiuj raport", report_before)
                self.assertNotIn("[OCZEKUJE] Gotowy na następne zmiany", report_before)

                with patch.object(
                    metalbox_app.QMessageBox,
                    "question",
                    return_value=metalbox_app.QMessageBox.Yes,
                ), patch.object(
                    metalbox_app.QMessageBox,
                    "information",
                    return_value=metalbox_app.QMessageBox.Ok,
                ):
                    panel._finish_cycle()

                state = metalbox_app.load_dev_update_state()
                self.assertTrue(state["ready_for_next"])
                self.assertIsNotNone(state["completed_at"])
                self.assertEqual(state["completed_with_pending"], 0)

                final_report = metalbox_app.QApplication.clipboard().text()
                self.assertIn("Gotowy na następne zmiany: TAK", final_report)
                self.assertIn("Podsumowanie: 1/1 OK", final_report)
                self.assertNotIn("Kopiuj raport", final_report)
                panel.close()
            finally:
                metalbox_app.DEV_UPDATE_STATE_FILE = original

    def test_report_with_logs_includes_recent_app_and_runner_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            original_app_log = metalbox_app.APP_LOG_FILE
            original_log_dir = metalbox_app.LOG_DIR
            original_source_state = metalbox_app.DEV_SOURCE_STATE_FILE
            try:
                metalbox_app.LOG_DIR = temp_path
                metalbox_app.APP_LOG_FILE = temp_path / "metalbox.log"
                metalbox_app.DEV_SOURCE_STATE_FILE = temp_path / "source_state.json"

                metalbox_app.APP_LOG_FILE.write_text(
                    "[2026-10-02 12:00:00] [INFO] Test Metalbox\n",
                    encoding="utf-8",
                )
                (temp_path / "dev-runner.log").write_text(
                    "[2026-10-02 12:00:01] [INFO] Test Runner\n",
                    encoding="utf-8",
                )
                metalbox_app.DEV_SOURCE_STATE_FILE.write_text(
                    json.dumps({"commit": "abc123"}),
                    encoding="utf-8",
                )

                report = metalbox_app.format_update_report_with_logs(
                    {
                        "old_version": "0.1.19",
                        "new_version": metalbox_app.APP_VERSION,
                        "title": "Test",
                        "ready_for_next": True,
                        "completed_at": "2026-10-02T12:00:00",
                        "changes": [],
                    }
                )
                self.assertIn("DIAGNOSTYKA DO RAPORTU", report)
                self.assertIn("Test Metalbox", report)
                self.assertIn("Test Runner", report)
                self.assertIn("Commit: abc123", report)
                self.assertIn("Schemat bazy:", report)
            finally:
                metalbox_app.APP_LOG_FILE = original_app_log
                metalbox_app.LOG_DIR = original_log_dir
                metalbox_app.DEV_SOURCE_STATE_FILE = original_source_state

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

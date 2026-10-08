from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from metalbox_core import MetalboxStore, SCHEMA_VERSION


class MetalboxStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "metalbox-test.sqlite3"
        self.store = MetalboxStore(self.db_path)
        self.store.seed_development_data()
        self.store.ensure_development_progress_seeded()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_schema_version(self) -> None:
        db = sqlite3.connect(self.db_path)
        try:
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
        finally:
            db.close()
        self.assertEqual(version, SCHEMA_VERSION)

    def test_repairs_incomplete_schema_with_current_user_version(self) -> None:
        repair_path = Path(self.temp_dir.name) / "repair.sqlite3"
        db = sqlite3.connect(repair_path)
        try:
            db.execute(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    client TEXT NOT NULL DEFAULT '',
                    deadline TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL DEFAULT 'NORMALNY',
                    status TEXT NOT NULL DEFAULT 'NOWE'
                )
                """
            )
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            db.commit()
        finally:
            db.close()

        repaired = MetalboxStore(repair_path)
        with repaired._connect() as db2:
            tables = {
                str(row["name"])
                for row in db2.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("operation_progress", tables)
        self.assertIn("order_items", tables)
        self.assertIn("audit_events", tables)
        self.assertIn("products", tables)
        self.assertIn("product_hints", tables)
        self.assertIn("accepted_plan_items", tables)
        self.assertIn("accepted_plan_requirements", tables)
        self.assertIn("accepted_plan_operation_loads", tables)
        self.assertIn("plan_publications", tables)
        self.assertIn("plan_published_subjects", tables)
        self.assertIn("order_item_dependencies", tables)

    def test_migrates_v7_session_workers_employee_id(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy-v7.sqlite3"
        db = sqlite3.connect(legacy_path)
        try:
            db.executescript(
                """
                CREATE TABLE production_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL DEFAULT 1,
                    department TEXT NOT NULL DEFAULT 'Laser',
                    status TEXT NOT NULL DEFAULT 'AKTYWNA',
                    started_at TEXT NOT NULL DEFAULT '',
                    paused_at TEXT,
                    ended_at TEXT,
                    created_by TEXT NOT NULL DEFAULT 'system',
                    note TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE session_workers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    worker_name TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    left_at TEXT
                );

                PRAGMA user_version = 7;
                """
            )
            db.commit()
        finally:
            db.close()

        migrated = MetalboxStore(legacy_path)
        with migrated._connect() as db2:
            columns = {
                str(row["name"])
                for row in db2.execute(
                    "PRAGMA table_info(session_workers)"
                ).fetchall()
            }
            version = int(db2.execute("PRAGMA user_version").fetchone()[0])

        self.assertIn("employee_id", columns)
        self.assertEqual(version, SCHEMA_VERSION)

    def test_migrates_v8_quality_reporter_employee_id(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy-v8-quality.sqlite3"
        db = sqlite3.connect(legacy_path)
        try:
            db.executescript(
                """
                CREATE TABLE quality_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    order_item_id INTEGER,
                    department TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    session_id INTEGER,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system'
                );
                PRAGMA user_version = 8;
                """
            )
            db.commit()
        finally:
            db.close()

        migrated = MetalboxStore(legacy_path)
        with migrated._connect() as db2:
            columns = {
                str(row["name"])
                for row in db2.execute(
                    "PRAGMA table_info(quality_events)"
                ).fetchall()
            }
            version = int(db2.execute("PRAGMA user_version").fetchone()[0])

        self.assertIn("reporter_employee_id", columns)
        self.assertEqual(version, SCHEMA_VERSION)

    def test_plan_acceptance_matches_products_and_does_not_create_orders(self) -> None:
        known = self.store.create_product(
            symbol="PLAN.KNOWN",
            name="Produkt znany",
        )
        before_orders = len(self.store.list_orders())

        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="snapshot-1.xlsx",
            sha256="snap1",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "zl-900|plan.known|produkt znany#1",
                    "row_no": 2,
                    "order_code": "ZL-900",
                    "symbol": "PLAN.KNOWN",
                    "name": "Produkt znany",
                    "quantity": 10.0,
                    "shipping": "2026-10-20",
                    "ral": "9011",
                },
                {
                    "row_key": "zl-901|plan.unknown|produkt obcy#1",
                    "row_no": 3,
                    "order_code": "ZL-901",
                    "symbol": "PLAN.UNKNOWN",
                    "name": "Produkt obcy",
                    "quantity": 5.0,
                    "shipping": "2026-10-21",
                    "ral": "7042",
                },
            ],
        )

        preview = self.store.get_plan_acceptance_preview(int(snapshot["id"]))
        self.assertEqual(preview["total_changes"], 2)
        self.assertEqual(preview["matched_count"], 1)
        self.assertEqual(preview["review_count"], 1)
        by_symbol = {row["symbol"]: row for row in preview["added"]}
        self.assertEqual(by_symbol["PLAN.KNOWN"]["product_match_status"], "DOPASOWANY")
        self.assertEqual(
            int(by_symbol["PLAN.KNOWN"]["product_id"]),
            int(known["id"]),
        )
        self.assertEqual(
            by_symbol["PLAN.UNKNOWN"]["product_match_status"],
            "DO WERYFIKACJI",
        )

        summary = self.store.accept_plan_snapshot(int(snapshot["id"]))
        self.assertFalse(summary["orders_changed"])
        self.assertEqual(len(self.store.list_orders()), before_orders)

        accepted = self.store.list_accepted_plan_items()
        self.assertEqual(len(accepted), 2)
        accepted_by_symbol = {row["symbol"]: row for row in accepted}
        self.assertEqual(
            accepted_by_symbol["PLAN.KNOWN"]["product_match_status"],
            "DOPASOWANY",
        )
        self.assertEqual(
            accepted_by_symbol["PLAN.UNKNOWN"]["product_match_status"],
            "DO WERYFIKACJI",
        )
        self.assertEqual(accepted_by_symbol["PLAN.KNOWN"]["ral"], "9011")
        self.assertEqual(accepted_by_symbol["PLAN.UNKNOWN"]["ral"], "7042")

        saved_snapshot = self.store.get_plan_snapshot(int(snapshot["id"]))
        self.assertEqual(saved_snapshot["status"], "ZAAKCEPTOWANY")

    def test_plan_acceptance_preview_detects_new_changed_and_removed(self) -> None:
        first = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="snapshot-a.xlsx",
            sha256="snap-a",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "zl-910|a|produkt a#1",
                    "row_no": 2,
                    "order_code": "ZL-910",
                    "symbol": "A",
                    "name": "Produkt A",
                    "quantity": 10.0,
                    "shipping": "18.10",
                    "ral": "9011",
                },
                {
                    "row_key": "zl-911|b|produkt b#1",
                    "row_no": 3,
                    "order_code": "ZL-911",
                    "symbol": "B",
                    "name": "Produkt B",
                    "quantity": 5.0,
                    "shipping": "18.10",
                    "ral": "9011",
                },
            ],
        )
        self.store.accept_plan_snapshot(int(first["id"]))

        second = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="snapshot-b.xlsx",
            sha256="snap-b",
            size_bytes=120,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "zl-910|a|produkt a#1",
                    "row_no": 2,
                    "order_code": "ZL-910",
                    "symbol": "A",
                    "name": "Produkt A",
                    "quantity": 12.0,
                    "shipping": "18.10",
                    "ral": "9011",
                },
                {
                    "row_key": "zl-912|c|produkt c#1",
                    "row_no": 4,
                    "order_code": "ZL-912",
                    "symbol": "C",
                    "name": "Produkt C",
                    "quantity": 3.0,
                    "shipping": "19.10",
                    "ral": "7042",
                },
            ],
        )

        preview = self.store.get_plan_acceptance_preview(int(second["id"]))
        self.assertEqual(len(preview["added"]), 1)
        self.assertEqual(len(preview["changed"]), 1)
        self.assertEqual(len(preview["removed"]), 1)
        self.assertEqual(
            preview["changed"][0]["changes"]["quantity"]["before"],
            10.0,
        )
        self.assertEqual(
            preview["changed"][0]["changes"]["quantity"]["after"],
            12.0,
        )

        self.store.accept_plan_snapshot(int(second["id"]))
        accepted_symbols = {
            row["symbol"]
            for row in self.store.list_accepted_plan_items()
        }
        self.assertEqual(accepted_symbols, {"A", "C"})

    def test_accepted_plan_bom_expands_recursively_and_keeps_orders_unchanged(self) -> None:
        root = self.store.create_product(symbol="PLAN.ROOT", name="Produkt główny")
        semi = self.store.create_product(
            symbol="PLAN.SEMI",
            name="Półprodukt",
            kind="PÓŁPRODUKT",
        )
        detail = self.store.create_product(
            symbol="PLAN.DETAIL",
            name="Detal",
            kind="PÓŁPRODUKT",
        )

        self.store.add_product_bom_item(
            "PLAN.ROOT",
            item_type="PÓŁPRODUKT",
            symbol="PLAN.SEMI",
            name="Półprodukt",
            quantity_per_set=2,
            unit="szt.",
        )
        self.store.add_product_bom_item(
            "PLAN.ROOT",
            item_type="MATERIAŁ",
            symbol="MAT.X",
            name="Materiał X",
            quantity_per_set=1.5,
            unit="kg",
        )
        self.store.add_product_bom_item(
            "PLAN.SEMI",
            item_type="DETAL",
            symbol="PLAN.DETAIL",
            name="Detal",
            quantity_per_set=3,
            unit="szt.",
        )

        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="snapshot-bom.xlsx",
            sha256="bom-plan",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "zl-100|plan.root|produkt glowny#1",
                    "row_no": 2,
                    "order_code": "ZL-100",
                    "symbol": "PLAN.ROOT",
                    "name": "Produkt główny",
                    "quantity": 100.0,
                    "shipping": "20.10",
                    "ral": "9011",
                }
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))
        before_orders = len(self.store.list_orders())

        summary = self.store.rebuild_accepted_plan_requirements()

        self.assertFalse(summary["orders_changed"])
        self.assertEqual(len(self.store.list_orders()), before_orders)
        self.assertEqual(summary["requirements"], 3)
        self.assertEqual(summary["linked_requirements"], 2)
        self.assertEqual(summary["unlinked_requirements"], 1)
        self.assertEqual(summary["matched_without_bom"], 0)

        rows = self.store.list_accepted_plan_requirements()
        by_symbol = {row["symbol"]: row for row in rows}

        self.assertEqual(by_symbol["PLAN.SEMI"]["level_no"], 1)
        self.assertEqual(by_symbol["PLAN.SEMI"]["required_quantity"], 200.0)
        self.assertEqual(by_symbol["PLAN.SEMI"]["link_status"], "POWIĄZANY")

        self.assertEqual(by_symbol["MAT.X"]["level_no"], 1)
        self.assertEqual(by_symbol["MAT.X"]["required_quantity"], 150.0)
        self.assertEqual(by_symbol["MAT.X"]["unit"], "kg")
        self.assertEqual(by_symbol["MAT.X"]["link_status"], "TYLKO BOM")

        self.assertEqual(by_symbol["PLAN.DETAIL"]["level_no"], 2)
        self.assertEqual(by_symbol["PLAN.DETAIL"]["required_quantity"], 600.0)
        self.assertIn("PLAN.ROOT", by_symbol["PLAN.DETAIL"]["path"])
        self.assertIn("PLAN.SEMI", by_symbol["PLAN.DETAIL"]["path"])

    def test_accepted_plan_bom_reports_unmatched_and_products_without_bom(self) -> None:
        self.store.create_product(symbol="PLAN.EMPTY", name="Produkt bez BOM")
        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="snapshot-empty.xlsx",
            sha256="empty-plan",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "zl-110|plan.empty|produkt bez bom#1",
                    "row_no": 2,
                    "order_code": "ZL-110",
                    "symbol": "PLAN.EMPTY",
                    "name": "Produkt bez BOM",
                    "quantity": 10.0,
                    "shipping": "20.10",
                    "ral": "9011",
                },
                {
                    "row_key": "zl-111|unknown|nieznany#1",
                    "row_no": 3,
                    "order_code": "ZL-111",
                    "symbol": "UNKNOWN",
                    "name": "Nieznany",
                    "quantity": 5.0,
                    "shipping": "21.10",
                    "ral": "7042",
                },
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))

        summary = self.store.rebuild_accepted_plan_requirements()

        self.assertEqual(summary["matched_plan_items"], 1)
        self.assertEqual(summary["review_plan_items"], 1)
        self.assertEqual(summary["matched_without_bom"], 1)
        self.assertEqual(summary["requirements"], 0)

    def test_accepted_plan_bom_blocks_multilevel_cycle(self) -> None:
        self.store.create_product(symbol="CYCLE.A", name="A")
        self.store.create_product(
            symbol="CYCLE.B",
            name="B",
            kind="PÓŁPRODUKT",
        )
        self.store.add_product_bom_item(
            "CYCLE.A",
            item_type="PÓŁPRODUKT",
            symbol="CYCLE.B",
            name="B",
            quantity_per_set=1,
        )
        self.store.add_product_bom_item(
            "CYCLE.B",
            item_type="PÓŁPRODUKT",
            symbol="CYCLE.A",
            name="A",
            quantity_per_set=1,
        )

        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="snapshot-cycle.xlsx",
            sha256="cycle-plan",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "zl-cycle|cycle.a|a#1",
                    "row_no": 2,
                    "order_code": "ZL-CYCLE",
                    "symbol": "CYCLE.A",
                    "name": "A",
                    "quantity": 1.0,
                    "shipping": "20.10",
                    "ral": "9011",
                }
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))

        with self.assertRaisesRegex(ValueError, "cykl BOM"):
            self.store.rebuild_accepted_plan_requirements()

        self.assertEqual(self.store.list_accepted_plan_requirements(), [])

    def test_plan_operation_loads_use_root_and_bom_technologies(self) -> None:
        self.store.create_product(symbol="LOAD.ROOT", name="Produkt główny")
        self.store.create_product(
            symbol="LOAD.SEMI",
            name="Półprodukt",
            kind="PÓŁPRODUKT",
        )
        self.store.create_product(
            symbol="LOAD.MAT",
            name="Materiał z kartą",
            kind="PÓŁPRODUKT",
        )

        self.store.add_product_bom_item(
            "LOAD.ROOT",
            item_type="PÓŁPRODUKT",
            symbol="LOAD.SEMI",
            name="Półprodukt",
            quantity_per_set=2,
            unit="szt.",
        )
        self.store.add_product_bom_item(
            "LOAD.ROOT",
            item_type="MATERIAŁ",
            symbol="LOAD.MAT",
            name="Materiał z kartą",
            quantity_per_set=1.5,
            unit="kg",
        )

        self.store.add_product_operation(
            "LOAD.ROOT",
            department="Laser",
            operation_name="Cięcie",
            setup_minutes=30,
            minutes_per_unit=0.5,
        )
        self.store.add_product_operation(
            "LOAD.SEMI",
            department="Giętarki",
            operation_name="Gięcie",
            setup_minutes=15,
            minutes_per_unit=0.25,
        )
        self.store.add_product_operation(
            "LOAD.MAT",
            department="Magazyn",
            operation_name="Nie licz materiału",
            setup_minutes=10,
            minutes_per_unit=1,
        )

        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="snapshot-load.xlsx",
            sha256="load-plan",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "zl-load|load.root|produkt#1",
                    "row_no": 2,
                    "order_code": "ZL-LOAD",
                    "symbol": "LOAD.ROOT",
                    "name": "Produkt główny",
                    "quantity": 100.0,
                    "shipping": "20.10",
                    "ral": "9011",
                }
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))
        before_orders = len(self.store.list_orders())

        summary = self.store.rebuild_accepted_plan_operation_loads()

        self.assertFalse(summary["orders_changed"])
        self.assertEqual(len(self.store.list_orders()), before_orders)
        self.assertEqual(summary["department_count"], 2)
        self.assertEqual(summary["operation_count"], 2)
        self.assertEqual(summary["timed_operation_count"], 2)
        self.assertEqual(summary["untimed_operation_count"], 0)
        self.assertAlmostEqual(summary["total_load_minutes"], 145.0)
        self.assertAlmostEqual(summary["total_load_hours"], 145.0 / 60.0)

        loads = self.store.list_accepted_plan_operation_loads()
        by_department = {row["department"]: row for row in loads}

        self.assertEqual(by_department["Laser"]["source_kind"], "PRODUKT")
        self.assertEqual(by_department["Laser"]["planned_quantity"], 100.0)
        self.assertEqual(by_department["Laser"]["load_minutes"], 80.0)

        self.assertEqual(by_department["Giętarki"]["source_kind"], "PÓŁPRODUKT")
        self.assertEqual(by_department["Giętarki"]["planned_quantity"], 200.0)
        self.assertEqual(by_department["Giętarki"]["load_minutes"], 65.0)

        self.assertNotIn("Magazyn", by_department)

    def test_plan_operation_loads_aggregate_same_component_and_setup_once(self) -> None:
        self.store.create_product(symbol="LOAD2.ROOT", name="Produkt")
        self.store.create_product(
            symbol="LOAD2.SEMI",
            name="Półprodukt",
            kind="PÓŁPRODUKT",
        )
        self.store.create_product(
            symbol="LOAD2.A",
            name="Gałąź A",
            kind="PÓŁPRODUKT",
        )
        self.store.create_product(
            symbol="LOAD2.B",
            name="Gałąź B",
            kind="PÓŁPRODUKT",
        )

        self.store.add_product_bom_item(
            "LOAD2.ROOT",
            item_type="PÓŁPRODUKT",
            symbol="LOAD2.A",
            name="A",
            quantity_per_set=1,
        )
        self.store.add_product_bom_item(
            "LOAD2.ROOT",
            item_type="PÓŁPRODUKT",
            symbol="LOAD2.B",
            name="B",
            quantity_per_set=1,
        )
        self.store.add_product_bom_item(
            "LOAD2.A",
            item_type="PÓŁPRODUKT",
            symbol="LOAD2.SEMI",
            name="Półprodukt",
            quantity_per_set=2,
        )
        self.store.add_product_bom_item(
            "LOAD2.B",
            item_type="PÓŁPRODUKT",
            symbol="LOAD2.SEMI",
            name="Półprodukt",
            quantity_per_set=3,
        )
        self.store.add_product_operation(
            "LOAD2.SEMI",
            department="Zgrzewarki",
            operation_name="Zgrzewanie",
            setup_minutes=10,
            minutes_per_unit=1,
        )

        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="snapshot-load2.xlsx",
            sha256="load-plan2",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "zl-load2|load2.root|produkt#1",
                    "row_no": 2,
                    "order_code": "ZL-LOAD2",
                    "symbol": "LOAD2.ROOT",
                    "name": "Produkt",
                    "quantity": 10.0,
                    "shipping": "20.10",
                    "ral": "9011",
                }
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))

        summary = self.store.rebuild_accepted_plan_operation_loads()
        loads = [
            row
            for row in self.store.list_accepted_plan_operation_loads()
            if row["subject_symbol"] == "LOAD2.SEMI"
        ]

        self.assertEqual(len(loads), 1)
        self.assertEqual(loads[0]["planned_quantity"], 50.0)
        self.assertEqual(loads[0]["load_minutes"], 60.0)
        self.assertEqual(summary["subjects_without_technology_count"], 3)

    def test_plan_operation_load_marks_missing_time_norm(self) -> None:
        self.store.create_product(symbol="LOAD3.ROOT", name="Produkt")
        self.store.add_product_operation(
            "LOAD3.ROOT",
            department="Pakownia",
            operation_name="Pakowanie",
            setup_minutes=0,
            minutes_per_unit=0,
        )
        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="snapshot-load3.xlsx",
            sha256="load-plan3",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "zl-load3|load3.root|produkt#1",
                    "row_no": 2,
                    "order_code": "ZL-LOAD3",
                    "symbol": "LOAD3.ROOT",
                    "name": "Produkt",
                    "quantity": 20.0,
                    "shipping": "20.10",
                    "ral": "7042",
                }
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))

        summary = self.store.rebuild_accepted_plan_operation_loads()

        self.assertEqual(summary["operation_count"], 1)
        self.assertEqual(summary["timed_operation_count"], 0)
        self.assertEqual(summary["untimed_operation_count"], 1)
        self.assertEqual(summary["total_load_minutes"], 0.0)
        load = self.store.list_accepted_plan_operation_loads()[0]
        self.assertEqual(int(load["has_time_norm"]), 0)
        self.assertEqual(load["load_minutes"], 0.0)

    def test_accepted_department_plan_preserves_operation_order_and_does_not_create_orders(self) -> None:
        self.store.create_product(symbol="PLANQ.ROOT", name="Produkt")
        self.store.create_product(
            symbol="PLANQ.SEMI",
            name="Półprodukt",
            kind="PÓŁPRODUKT",
        )
        self.store.add_product_bom_item(
            "PLANQ.ROOT",
            item_type="PÓŁPRODUKT",
            symbol="PLANQ.SEMI",
            name="Półprodukt",
            quantity_per_set=2,
        )
        self.store.add_product_operation(
            "PLANQ.ROOT",
            department="Laser",
            operation_name="Cięcie",
            setup_minutes=10,
            minutes_per_unit=0.2,
        )
        self.store.add_product_operation(
            "PLANQ.ROOT",
            department="Giętarki",
            operation_name="Gięcie",
            setup_minutes=5,
            minutes_per_unit=0.1,
        )
        self.store.add_product_operation(
            "PLANQ.SEMI",
            department="Zgrzewarki",
            operation_name="Zgrzewanie",
            setup_minutes=8,
            minutes_per_unit=0.3,
        )

        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="planq.xlsx",
            sha256="planq",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "zl-planq|planq.root|produkt#1",
                    "row_no": 2,
                    "order_code": "ZL-PLANQ",
                    "symbol": "PLANQ.ROOT",
                    "name": "Produkt",
                    "quantity": 10.0,
                    "shipping": "2026-10-20",
                    "ral": "9011",
                }
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))
        before_orders = len(self.store.list_orders())

        self.store.rebuild_accepted_plan_operation_loads()
        summary = self.store.accepted_department_plan_summary()
        rows = self.store.list_accepted_department_plan()

        self.assertEqual(len(self.store.list_orders()), before_orders)
        self.assertFalse(summary["orders_changed"])
        self.assertEqual(summary["department_count"], 3)
        self.assertEqual(summary["row_count"], 3)
        self.assertEqual({row["plan_status"] for row in rows}, {"PLANOWANE"})

        root_rows = [
            row for row in rows
            if row["subject_symbol"] == "PLANQ.ROOT"
        ]
        root_rows.sort(key=lambda row: int(row["sequence_no"]))
        self.assertEqual(len(root_rows), 2)
        self.assertEqual(root_rows[0]["department"], "Laser")
        self.assertEqual(root_rows[0]["plan_stage"], "PIERWSZY ETAP")
        self.assertTrue(root_rows[0]["is_first_operation"])
        self.assertEqual(root_rows[1]["department"], "Giętarki")
        self.assertEqual(root_rows[1]["plan_stage"], "OSTATNI ETAP")
        self.assertTrue(root_rows[1]["is_last_operation"])

        semi_rows = [
            row for row in rows
            if row["subject_symbol"] == "PLANQ.SEMI"
        ]
        self.assertEqual(len(semi_rows), 1)
        self.assertEqual(semi_rows[0]["planned_quantity"], 20.0)
        self.assertEqual(semi_rows[0]["plan_stage"], "JEDYNY ETAP")

        laser_rows = self.store.list_accepted_department_plan("Laser")
        self.assertEqual(len(laser_rows), 1)
        self.assertEqual(laser_rows[0]["operation_name"], "Cięcie")

    def test_plan_publication_creates_real_queues_and_is_idempotent(self) -> None:
        self.store.create_product(symbol="PUB.ROOT", name="Produkt publikowany")
        self.store.create_product(
            symbol="PUB.SEMI",
            name="Półprodukt publikowany",
            kind="PÓŁPRODUKT",
        )
        self.store.add_product_bom_item(
            "PUB.ROOT",
            item_type="PÓŁPRODUKT",
            symbol="PUB.SEMI",
            name="Półprodukt publikowany",
            quantity_per_set=2,
        )
        self.store.add_product_operation(
            "PUB.ROOT",
            department="Laser",
            operation_name="Cięcie",
            setup_minutes=10,
            minutes_per_unit=0.2,
        )
        self.store.add_product_operation(
            "PUB.ROOT",
            department="Giętarki",
            operation_name="Gięcie",
            setup_minutes=5,
            minutes_per_unit=0.1,
        )
        self.store.add_product_operation(
            "PUB.SEMI",
            department="Zgrzewarki",
            operation_name="Zgrzewanie",
            setup_minutes=8,
            minutes_per_unit=0.3,
        )

        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="publish.xlsx",
            sha256="publish-plan",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "10001|pub.root|produkt publikowany#1",
                    "row_no": 2,
                    "order_code": "10001",
                    "symbol": "PUB.ROOT",
                    "name": "Produkt publikowany",
                    "quantity": 10.0,
                    "shipping": "20.10",
                    "ral": "9011",
                },
                {
                    "row_key": "10002|pub.unknown|produkt nieznany#1",
                    "row_no": 3,
                    "order_code": "10002",
                    "symbol": "PUB.UNKNOWN",
                    "name": "Produkt nieznany",
                    "quantity": 5.0,
                    "shipping": "21.10",
                    "ral": "7042",
                },
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))

        before_orders = len(self.store.list_orders())
        preview = self.store.get_plan_publication_preview()

        self.assertEqual(preview["eligible_count"], 1)
        self.assertEqual(preview["blocked_count"], 1)
        self.assertEqual(preview["eligible_subject_count"], 2)
        self.assertEqual(
            preview["eligible_rows"][0]["normalized_order_code"],
            "ZL-10001",
        )
        self.assertIn(
            "DO WERYFIKACJI",
            " ".join(preview["blocked_rows"][0]["reasons"]),
        )

        first = self.store.publish_accepted_department_plan()

        self.assertTrue(first["orders_changed"])
        self.assertEqual(first["created_orders"], 1)
        self.assertEqual(first["created_items"], 2)
        self.assertEqual(first["operation_count"], 3)
        self.assertEqual(len(self.store.list_orders()), before_orders + 1)

        order = self.store.get_order("ZL-10001")
        self.assertIsNotNone(order)
        self.assertEqual(len(order["items"]), 2)

        laser = [
            row
            for row in self.store.list_department_queue("Laser")
            if row["code"] == "ZL-10001"
        ]
        bending = [
            row
            for row in self.store.list_department_queue("Giętarki")
            if row["code"] == "ZL-10001"
        ]
        welding = [
            row
            for row in self.store.list_department_queue("Zgrzewarki")
            if row["code"] == "ZL-10001"
        ]
        self.assertEqual(len(laser), 1)
        self.assertEqual(len(bending), 1)
        self.assertEqual(len(welding), 1)
        self.assertEqual(int(laser[0]["planned_qty"]), 10)
        self.assertEqual(int(welding[0]["planned_qty"]), 20)

        with self.store._connect() as db:
            published_items = db.execute(
                """
                SELECT symbol, quantity, ral, source_kind, plan_row_key
                FROM order_items
                WHERE order_id = (
                    SELECT id FROM orders WHERE code = 'ZL-10001'
                )
                ORDER BY position_no
                """
            ).fetchall()
            operations = db.execute(
                """
                SELECT oi.symbol, op.department, op.operation_name, op.sequence_no
                FROM operation_progress op
                JOIN order_items oi ON oi.id = op.order_item_id
                JOIN orders o ON o.id = oi.order_id
                WHERE o.code = 'ZL-10001'
                ORDER BY oi.position_no, op.sequence_no
                """
            ).fetchall()

        self.assertEqual(
            {str(row["source_kind"]) for row in published_items},
            {"PRODUKT", "PÓŁPRODUKT"},
        )
        self.assertEqual(
            {str(row["ral"]) for row in published_items},
            {"9011"},
        )
        self.assertEqual(
            [str(row["operation_name"]) for row in operations],
            ["Cięcie", "Gięcie", "Zgrzewanie"],
        )

        second = self.store.publish_accepted_department_plan()
        self.assertEqual(second["created_orders"], 0)
        self.assertEqual(second["created_items"], 0)
        self.assertEqual(second["updated_items"], 2)
        self.assertEqual(len(self.store.list_orders()), before_orders + 1)

        with self.store._connect() as db:
            item_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    WHERE o.code = 'ZL-10001'
                    """
                ).fetchone()[0]
            )
        self.assertEqual(item_count, 2)

    def test_published_parent_waits_for_bom_child(self) -> None:
        self.store.create_product(symbol="PUBDEP.ROOT", name="Produkt")
        self.store.create_product(
            symbol="PUBDEP.SEMI",
            name="Półprodukt",
            kind="PÓŁPRODUKT",
        )
        self.store.add_product_bom_item(
            "PUBDEP.ROOT",
            item_type="PÓŁPRODUKT",
            symbol="PUBDEP.SEMI",
            name="Półprodukt",
            quantity_per_set=2,
        )
        self.store.add_product_operation(
            "PUBDEP.ROOT",
            department="Zgrzewarki",
            operation_name="Montaż",
            setup_minutes=5,
            minutes_per_unit=0.2,
        )
        self.store.add_product_operation(
            "PUBDEP.SEMI",
            department="Laser",
            operation_name="Cięcie półproduktu",
            setup_minutes=5,
            minutes_per_unit=0.1,
        )
        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="publish-dependency.xlsx",
            sha256="publish-dependency",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "10004|pubdep.root|produkt#1",
                    "row_no": 2,
                    "order_code": "10004",
                    "symbol": "PUBDEP.ROOT",
                    "name": "Produkt",
                    "quantity": 10.0,
                    "shipping": "23.10",
                    "ral": "9011",
                }
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))
        self.store.publish_accepted_department_plan()
        order = self.store.get_order("ZL-10004")
        self.assertIsNotNone(order)
        by_kind = {str(item["source_kind"]): item for item in order["items"]}
        root_item_id = int(by_kind["PRODUKT"]["id"])
        semi_item_id = int(by_kind["PÓŁPRODUKT"]["id"])

        root_before = self.store.get_item_department_capacity(
            "ZL-10004", root_item_id, "Zgrzewarki"
        )
        semi_before = self.store.get_item_department_capacity(
            "ZL-10004", semi_item_id, "Laser"
        )
        self.assertEqual(root_before["available_now"], 0)
        self.assertEqual(semi_before["available_now"], 20)

        with self.store._connect() as db:
            dependency_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM order_item_dependencies
                    WHERE parent_order_item_id = ?
                      AND child_order_item_id = ?
                    """,
                    (root_item_id, semi_item_id),
                ).fetchone()[0]
            )
            self.assertEqual(dependency_count, 1)
            db.execute(
                """
                UPDATE operation_progress
                SET good_qty = planned_qty,
                    status = 'GOTOWE'
                WHERE order_item_id = ?
                """,
                (semi_item_id,),
            )

        root_after = self.store.get_item_department_capacity(
            "ZL-10004", root_item_id, "Zgrzewarki"
        )
        self.assertEqual(root_after["available_now"], 10)

    def test_plan_publication_blocks_unlinked_production_bom(self) -> None:
        self.store.create_product(symbol="PUBMISS.ROOT", name="Produkt")
        self.store.add_product_bom_item(
            "PUBMISS.ROOT",
            item_type="PÓŁPRODUKT",
            symbol="PUBMISS.SEMI",
            name="Brakujący półprodukt",
            quantity_per_set=2,
        )
        self.store.add_product_operation(
            "PUBMISS.ROOT",
            department="Laser",
            operation_name="Cięcie",
            setup_minutes=1,
            minutes_per_unit=0.1,
        )
        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="publish-missing-bom.xlsx",
            sha256="publish-missing-bom",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "10005|pubmiss.root|produkt#1",
                    "row_no": 2,
                    "order_code": "10005",
                    "symbol": "PUBMISS.ROOT",
                    "name": "Produkt",
                    "quantity": 10.0,
                    "shipping": "24.10",
                    "ral": "9011",
                }
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))
        preview = self.store.get_plan_publication_preview()
        self.assertEqual(preview["eligible_count"], 0)
        self.assertEqual(preview["blocked_count"], 1)
        self.assertIn(
            "brak powiązanej karty",
            " ".join(preview["blocked_rows"][0]["reasons"]),
        )
        before_orders = len(self.store.list_orders())
        result = self.store.publish_accepted_department_plan()
        self.assertEqual(result["created_orders"], 0)
        self.assertEqual(len(self.store.list_orders()), before_orders)

    def test_plan_publication_protects_started_work(self) -> None:
        self.store.create_product(symbol="PUB.ACTIVE", name="Produkt aktywny")
        self.store.add_product_operation(
            "PUB.ACTIVE",
            department="Laser",
            operation_name="Cięcie",
            setup_minutes=1,
            minutes_per_unit=0.1,
        )
        snapshot = self.store.create_plan_snapshot(
            source_name="Plan Produkcji 2026.xlsx",
            snapshot_path="publish-active.xlsx",
            sha256="publish-active",
            size_bytes=100,
            sheet_name="PLAN 2026",
            header_row=1,
            rows=[
                {
                    "row_key": "10003|pub.active|produkt aktywny#1",
                    "row_no": 2,
                    "order_code": "10003",
                    "symbol": "PUB.ACTIVE",
                    "name": "Produkt aktywny",
                    "quantity": 10.0,
                    "shipping": "22.10",
                    "ral": "9011",
                }
            ],
        )
        self.store.accept_plan_snapshot(int(snapshot["id"]))
        self.store.publish_accepted_department_plan()

        order = self.store.get_order("ZL-10003")
        self.assertIsNotNone(order)
        order_item_id = int(order["items"][0]["id"])
        self.store.start_production_session(
            "ZL-10003",
            "Laser",
            ["Tester"],
            order_item_id=order_item_id,
        )

        preview = self.store.get_plan_publication_preview()
        self.assertEqual(preview["eligible_count"], 0)
        self.assertEqual(preview["blocked_count"], 1)
        self.assertIn(
            "rozpoczętą produkcję",
            " ".join(preview["blocked_rows"][0]["reasons"]),
        )

    def test_product_hints_are_raw_idempotent_and_do_not_create_products(self) -> None:
        entries = [
            "1.437.68 TESAM",
            "ARCHIWUM",
            "1.437.68 TESAM",
            "5.REG.PÓŁKA 1M",
        ]

        first = self.store.import_product_hints(
            entries,
            source="test-foldery.txt",
        )
        second = self.store.import_product_hints(
            entries,
            source="test-foldery.txt",
        )

        self.assertEqual(first["input_count"], 4)
        self.assertEqual(first["inserted"], 4)
        self.assertEqual(first["total"], 4)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["total"], 4)
        self.assertEqual(self.store.list_products(), [])

        hints = self.store.list_product_hints()
        self.assertEqual(
            {row["raw_name"] for row in hints},
            {"1.437.68 TESAM", "ARCHIWUM", "5.REG.PÓŁKA 1M"},
        )

    def test_product_can_be_created_from_hint_and_marks_source_as_used(self) -> None:
        self.store.import_product_hints(
            ["1.437.68 TESAM", "ARCHIWUM"],
            source="test-foldery.txt",
        )
        hint = next(
            row
            for row in self.store.list_product_hints()
            if row["raw_name"] == "1.437.68 TESAM"
        )

        product = self.store.create_product(
            symbol="1.437.68",
            name="TESAM",
            kind="PRODUKT",
            material="DC01",
            dimensions="437x68",
            quantity_per_set=2,
            department="Giętarki",
            technology="Laser → Gięcie",
            hint_id=int(hint["id"]),
        )

        self.assertEqual(product["symbol"], "1.437.68")
        self.assertEqual(product["name"], "TESAM")
        self.assertEqual(product["quantity_per_set"], 2)
        self.assertEqual(self.store.product_hint_stats()["used_rows"], 1)
        self.assertEqual(
            [row["symbol"] for row in self.store.list_products(search="TESAM")],
            ["1.437.68"],
        )

    def test_product_symbol_must_be_unique(self) -> None:
        self.store.create_product(symbol="TEST.1", name="Test")
        with self.assertRaisesRegex(ValueError, "już istnieje"):
            self.store.create_product(symbol="test.1", name="Duplikat")

    def test_product_can_be_edited_and_filtered_for_verification(self) -> None:
        self.store.create_product(
            symbol="VERIFY.1",
            name="Nazwa robocza",
            status="DO WERYFIKACJI",
        )
        self.store.create_product(
            symbol="ACTIVE.1",
            name="Produkt aktywny",
            status="AKTYWNY",
        )

        pending = self.store.list_products(status="DO WERYFIKACJI")
        self.assertEqual([row["symbol"] for row in pending], ["VERIFY.1"])

        updated = self.store.update_product(
            "VERIFY.1",
            name="Nazwa poprawiona",
            kind="PÓŁPRODUKT",
            client_variant="Wariant A",
            material="DC01",
            dimensions="100x200",
            quantity_per_set=3,
            department="Giętarki",
            technology="Laser → Gięcie",
            notes="Po weryfikacji",
            status="AKTYWNY",
        )

        self.assertEqual(updated["symbol"], "VERIFY.1")
        self.assertEqual(updated["name"], "Nazwa poprawiona")
        self.assertEqual(updated["kind"], "PÓŁPRODUKT")
        self.assertEqual(updated["quantity_per_set"], 3)
        self.assertEqual(updated["status"], "AKTYWNY")
        self.assertEqual(self.store.list_products(status="DO WERYFIKACJI"), [])

    def test_product_bom_add_link_calculate_and_delete(self) -> None:
        self.store.create_product(symbol="PARENT.1", name="Produkt główny")
        child = self.store.create_product(
            symbol="SEMI.1",
            name="Półprodukt",
            kind="PÓŁPRODUKT",
        )

        linked = self.store.add_product_bom_item(
            "PARENT.1",
            item_type="PÓŁPRODUKT",
            symbol="SEMI.1",
            name="Półprodukt",
            quantity_per_set=2,
            unit="szt.",
        )
        loose = self.store.add_product_bom_item(
            "PARENT.1",
            item_type="MATERIAŁ",
            symbol="BLACHA.1",
            name="Blacha",
            quantity_per_set=1.5,
            unit="kg",
        )

        rows = self.store.list_product_bom("PARENT.1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(int(linked["child_product_id"]), int(child["id"]))
        self.assertIsNone(loose["child_product_id"])

        requirements = self.store.calculate_product_requirements(
            "PARENT.1",
            100,
        )
        by_symbol = {row["symbol"]: row for row in requirements}
        self.assertEqual(by_symbol["SEMI.1"]["required_quantity"], 200.0)
        self.assertEqual(by_symbol["BLACHA.1"]["required_quantity"], 150.0)

        self.store.delete_product_bom_item(
            "PARENT.1",
            int(linked["id"]),
        )
        self.assertEqual(
            [row["symbol"] for row in self.store.list_product_bom("PARENT.1")],
            ["BLACHA.1"],
        )

    def test_product_operations_route_order_and_load(self) -> None:
        self.store.create_product(symbol="TECH.1", name="Produkt technologiczny")

        laser = self.store.add_product_operation(
            "TECH.1",
            department="Laser",
            operation_name="Cięcie",
            setup_minutes=30,
            minutes_per_unit=0.5,
        )
        bending = self.store.add_product_operation(
            "TECH.1",
            department="Giętarki",
            operation_name="Gięcie",
            setup_minutes=15,
            minutes_per_unit=0.25,
        )
        welding = self.store.add_product_operation(
            "TECH.1",
            department="Zgrzewarki",
            operation_name="Zgrzewanie",
            minutes_per_unit=0.75,
        )

        route = self.store.list_product_operations("TECH.1")
        self.assertEqual(
            [row["department"] for row in route],
            ["Laser", "Giętarki", "Zgrzewarki"],
        )

        self.store.move_product_operation(
            "TECH.1",
            int(welding["id"]),
            -1,
        )
        moved = self.store.list_product_operations("TECH.1")
        self.assertEqual(
            [row["department"] for row in moved],
            ["Laser", "Zgrzewarki", "Giętarki"],
        )
        self.assertEqual(
            [row["sequence_no"] for row in moved],
            [1, 2, 3],
        )

        load = self.store.calculate_operation_load("TECH.1", 100)
        by_department = {row["department"]: row for row in load}
        self.assertEqual(by_department["Laser"]["load_minutes"], 80.0)
        self.assertEqual(by_department["Giętarki"]["load_minutes"], 40.0)
        self.assertEqual(by_department["Zgrzewarki"]["load_minutes"], 75.0)

        self.store.delete_product_operation(
            "TECH.1",
            int(laser["id"]),
        )
        final_route = self.store.list_product_operations("TECH.1")
        self.assertEqual(
            [row["sequence_no"] for row in final_route],
            [1, 2],
        )

    def test_product_operation_requires_department_and_name(self) -> None:
        self.store.create_product(symbol="TECH.2", name="Produkt")
        with self.assertRaisesRegex(ValueError, "Dział"):
            self.store.add_product_operation(
                "TECH.2",
                department="",
                operation_name="Cięcie",
            )
        with self.assertRaisesRegex(ValueError, "Nazwa operacji"):
            self.store.add_product_operation(
                "TECH.2",
                department="Laser",
                operation_name="",
            )

    def test_product_bom_blocks_duplicate_and_self_reference(self) -> None:
        self.store.create_product(symbol="PARENT.2", name="Produkt")

        self.store.add_product_bom_item(
            "PARENT.2",
            item_type="DETAL",
            symbol="D.1",
            name="Detal",
            quantity_per_set=1,
        )
        with self.assertRaisesRegex(ValueError, "już znajduje się"):
            self.store.add_product_bom_item(
                "PARENT.2",
                item_type="DETAL",
                symbol="d.1",
                name="Duplikat",
                quantity_per_set=2,
            )

        with self.assertRaisesRegex(ValueError, "samego siebie"):
            self.store.add_product_bom_item(
                "PARENT.2",
                item_type="PÓŁPRODUKT",
                symbol="PARENT.2",
                name="Błędne zapętlenie",
                quantity_per_set=1,
            )

    def test_transport_location_optional_and_searchable(self) -> None:
        item_id = int(self.store.get_order("ZL-740")["items"][4]["id"])
        self.assertEqual(self.store.list_transport_units(order_item_id=item_id), [])
        pallet = self.store.register_transport_unit(
            order_item_id=item_id,
            unit_code="PAL-024",
            quantity=600,
            hall="Hala 2",
            zone="Zgrzewarki",
            place="Odkładcze A",
            stage="Po gięciu",
            actor="Edwin",
        )
        self.assertEqual(pallet["unit_code"], "PAL-024")
        self.assertEqual(pallet["quantity"], 600)
        self.assertEqual(pallet["hall"], "Hala 2")
        self.assertEqual(
            [x["unit_code"] for x in self.store.list_transport_units(search="ZL-740")],
            ["PAL-024"],
        )
        self.assertEqual(len(self.store.list_transport_movements(unit_code="PAL-024")), 1)
        self.assertEqual(self.store.list_transport_movements(unit_code="PAL-024")[0]["actor"], "Edwin")

    def test_transport_split_and_full_move_have_durable_history(self) -> None:
        item_id = int(self.store.get_order("ZL-740")["items"][4]["id"])
        self.store.register_transport_unit(
            order_item_id=item_id, unit_code="PAL-A", quantity=700,
            hall="Hala 1", actor="I zmiana",
        )
        self.store.move_transport_unit(
            "PAL-A", quantity=200, target_unit_code="PAL-B",
            hall="Hala 2", zone="Malarnia", place="Półka 3", actor="II zmiana",
        )
        self.assertEqual(self.store.get_transport_unit("PAL-A")["quantity"], 500)
        self.assertEqual(self.store.get_transport_unit("PAL-B")["quantity"], 200)
        self.store.move_transport_unit(
            "PAL-B", quantity=200, hall="Hala 3",
            zone="Pakownia", actor="III zmiana",
        )
        self.assertEqual(self.store.get_transport_unit("PAL-B")["hall"], "Hala 3")
        self.assertEqual(
            [x["action"] for x in self.store.list_transport_movements(unit_code="PAL-B")],
            ["PRZENIESIONO", "PODZIELONO"],
        )
        self.assertEqual(
            sum(x["quantity"] for x in self.store.list_transport_units(order_item_id=item_id)),
            700,
        )

    def test_transport_rejects_wrong_item_excess_and_invalid_split(self) -> None:
        item = self.store.get_order("ZL-740")["items"][4]
        item_id = int(item["id"])
        self.store.register_transport_unit(
            order_item_id=item_id, unit_code="PAL-A", quantity=100,
            hall="Hala 1",
        )
        with self.assertRaisesRegex(ValueError, "już przypisany"):
            self.store.register_transport_unit(
                order_item_id=item_id, unit_code="pal-a", quantity=1, hall="Hala 1",
            )
        with self.assertRaisesRegex(ValueError, "przekroczyłaby"):
            self.store.register_transport_unit(
                order_item_id=item_id, unit_code="PAL-TOO-MANY",
                quantity=int(item["quantity"]), hall="Hala 1",
            )
        with self.assertRaisesRegex(ValueError, "inny identyfikator"):
            self.store.move_transport_unit(
                "PAL-A", quantity=20, hall="Hala 2",
            )
        self.assertEqual(self.store.get_transport_unit("PAL-A")["quantity"], 100)
        with self.assertRaisesRegex(ValueError, "więcej sztuk"):
            self.store.move_transport_unit(
                "PAL-A", quantity=101, hall="Hala 2",
            )

    def test_transport_handover_and_schema_repair(self) -> None:
        item_id = int(self.store.get_order("ZL-740")["items"][4]["id"])
        self.store.register_transport_unit(
            order_item_id=item_id, unit_code="PAL-S", quantity=25, hall="Hala 1",
        )
        with self.assertRaisesRegex(ValueError, "Najpierw"):
            self.store.set_transport_handover("PAL-S", status="ODEBRANE")
        self.store.set_transport_handover(
            "PAL-S", status="OCZEKUJE NA ODBIÓR", actor="Zmiana I",
        )
        self.assertEqual(
            self.store.get_transport_unit("PAL-S")["handover_status"],
            "OCZEKUJE NA ODBIÓR",
        )
        self.store.set_transport_handover(
            "PAL-S", status="ODEBRANE", actor="Zmiana II",
        )
        self.assertEqual(
            [x["action"] for x in self.store.list_transport_movements(unit_code="PAL-S")],
            ["ODBIÓR", "PRZEKAZANIE", "UTWORZONO"],
        )
        self.assertEqual(
            self.store.get_transport_unit("PAL-S")["handover_status"], "ODEBRANE",
        )
        reopened = MetalboxStore(self.db_path)
        self.assertEqual(reopened.get_transport_unit("PAL-S")["quantity"], 25)

    def test_seed_and_search(self) -> None:
        orders = self.store.list_orders()
        self.assertEqual(len(orders), 4)

        by_product = self.store.list_orders(search="SC600")
        self.assertEqual([row["code"] for row in by_product], ["ZL-740"])

        by_symbol = self.store.list_orders(search="1.330.50")
        self.assertEqual([row["code"] for row in by_symbol], ["ZL-763"])

    def test_order_has_items_and_stage_progress(self) -> None:
        order = self.store.get_order("ZL-740")
        self.assertIsNotNone(order)
        self.assertEqual(len(order["items"]), 5)

        stages = self.store.get_order_stage_progress("ZL-740")
        self.assertEqual(
            [row["department"] for row in stages],
            ["Laser", "Giętarki", "Zgrzewarki", "Malarnia", "Pakownia"],
        )
        self.assertGreater(stages[0]["good_qty"], 0)

    def test_downstream_capacity_is_limited_by_previous_stage(self) -> None:
        capacity = self.store.get_department_order_capacity(
            "ZL-740",
            "Malarnia",
        )
        self.assertGreater(capacity["available_now"], 0)
        self.assertLessEqual(
            capacity["available_now"],
            capacity["remaining"],
        )

        with self.assertRaises(ValueError):
            self.store.add_department_good_qty(
                "ZL-740",
                "Malarnia",
                capacity["available_now"] + 1,
            )

    def test_add_good_quantity_updates_progress_and_audit(self) -> None:
        capacity = self.store.get_department_order_capacity(
            "ZL-740",
            "Zgrzewarki",
        )
        self.assertGreater(capacity["available_now"], 0)

        result = self.store.add_department_good_qty(
            "ZL-740",
            "Zgrzewarki",
            1,
            actor="test-user",
        )
        self.assertEqual(result["added"], 1)

        events = self.store.list_audit_events(
            entity_type="order",
            entity_id="ZL-740",
            limit=50,
        )
        self.assertTrue(
            any(
                event["action"] == "good_quantity_added"
                and event["actor"] == "test-user"
                for event in events
            )
        )

    def test_create_order_with_default_route(self) -> None:
        created = self.store.create_order(
            code="ZL-900",
            client="Test Klient",
            deadline="2026-11-05",
            priority="WYSOKI",
            status="NOWE",
            items=[
                {"symbol": "ABC-1", "name": "Produkt A", "quantity": 12},
                {"symbol": "ABC-2", "name": "Produkt B", "quantity": 7},
            ],
            actor="test-user",
        )
        self.assertEqual(created["code"], "ZL-900")
        self.assertEqual(len(created["items"]), 2)

        stages = self.store.get_order_stage_progress("ZL-900")
        self.assertEqual(
            [row["department"] for row in stages],
            ["Laser", "Giętarki", "Zgrzewarki", "Malarnia", "Pakownia"],
        )
        self.assertTrue(all(int(row["good_qty"]) == 0 for row in stages))

        events = self.store.list_audit_events(
            entity_type="order",
            entity_id="ZL-900",
        )
        self.assertTrue(any(event["action"] == "order_created" for event in events))

    def test_update_order_preserves_item_id_and_audits_diff(self) -> None:
        created = self.store.create_order(
            code="ZL-901",
            client="Klient",
            deadline="2026-11-05",
            priority="NORMALNY",
            status="NOWE",
            items=[{"symbol": "A", "name": "Produkt", "quantity": 10}],
        )
        first_id = int(created["items"][0]["id"])

        updated = self.store.update_order(
            "ZL-901",
            code="ZL-901",
            client="Nowy klient",
            deadline="2026-11-10",
            priority="WYSOKI",
            status="NOWE",
            items=[
                {
                    "id": first_id,
                    "symbol": "A",
                    "name": "Produkt",
                    "quantity": 15,
                },
                {"symbol": "B", "name": "Drugi", "quantity": 5},
            ],
            actor="test-user",
        )

        self.assertEqual(updated["client"], "Nowy klient")
        self.assertEqual(len(updated["items"]), 2)
        self.assertEqual(int(updated["items"][0]["id"]), first_id)
        self.assertEqual(int(updated["items"][0]["quantity"]), 15)
        self.assertNotEqual(int(updated["items"][1]["id"]), first_id)

        events = self.store.list_audit_events(
            entity_type="order",
            entity_id="ZL-901",
            limit=20,
        )
        event = next(
            event
            for event in events
            if event["action"] == "order_updated"
        )
        payload = event["payload"]
        self.assertEqual(
            payload["header_changes"]["client"],
            {"old": "Klient", "new": "Nowy klient"},
        )
        updated_change = next(
            change
            for change in payload["item_changes"]
            if change["action"] == "updated"
        )
        self.assertEqual(int(updated_change["order_item_id"]), first_id)
        self.assertEqual(int(updated_change["old"]["quantity"]), 10)
        self.assertEqual(int(updated_change["new"]["quantity"]), 15)
        self.assertTrue(
            any(
                change["action"] == "added"
                for change in payload["item_changes"]
            )
        )

    def test_started_item_does_not_lock_unstarted_sibling(self) -> None:
        created = self.store.create_order(
            code="ZL-902",
            client="Klient",
            deadline="2026-11-05",
            priority="NORMALNY",
            status="NOWE",
            items=[
                {"symbol": "A", "name": "Pierwszy", "quantity": 10},
                {"symbol": "B", "name": "Drugi", "quantity": 8},
            ],
        )
        first_id = int(created["items"][0]["id"])
        second_id = int(created["items"][1]["id"])

        self.store.start_production_session(
            "ZL-902",
            "Laser",
            ["Dawid"],
            order_item_id=first_id,
        )

        updated = self.store.update_order(
            "ZL-902",
            code="ZL-902",
            client="Klient",
            deadline="2026-11-05",
            priority="NORMALNY",
            status="NOWE",
            items=[
                {
                    "id": first_id,
                    "symbol": "A",
                    "name": "Pierwszy",
                    "quantity": 10,
                },
                {
                    "id": second_id,
                    "symbol": "B2",
                    "name": "Drugi po zmianie",
                    "quantity": 12,
                },
            ],
        )
        self.assertEqual(int(updated["items"][0]["id"]), first_id)
        self.assertEqual(int(updated["items"][1]["id"]), second_id)
        self.assertEqual(updated["items"][1]["symbol"], "B2")
        self.assertEqual(int(updated["items"][1]["quantity"]), 12)

        reduced = self.store.update_order(
            "ZL-902",
            code="ZL-902",
            client="Klient",
            deadline="2026-11-05",
            priority="NORMALNY",
            status="NOWE",
            items=[
                {
                    "id": first_id,
                    "symbol": "A",
                    "name": "Pierwszy",
                    "quantity": 10,
                }
            ],
        )
        self.assertEqual(
            [int(item["id"]) for item in reduced["items"]],
            [first_id],
        )

    def test_started_item_blocks_symbol_name_and_delete(self) -> None:
        created = self.store.create_order(
            code="ZL-903",
            client="Klient",
            deadline="2026-11-05",
            priority="NORMALNY",
            status="NOWE",
            items=[
                {"symbol": "A", "name": "Pierwszy", "quantity": 10},
                {"symbol": "B", "name": "Drugi", "quantity": 8},
            ],
        )
        first_id = int(created["items"][0]["id"])
        second_id = int(created["items"][1]["id"])

        self.store.start_production_session(
            "ZL-903",
            "Laser",
            ["Dawid"],
            order_item_id=first_id,
        )

        with self.assertRaises(ValueError):
            self.store.update_order(
                "ZL-903",
                code="ZL-903",
                client="Klient",
                deadline="2026-11-05",
                priority="NORMALNY",
                status="NOWE",
                items=[
                    {
                        "id": first_id,
                        "symbol": "A-ZMIANA",
                        "name": "Pierwszy",
                        "quantity": 10,
                    },
                    {
                        "id": second_id,
                        "symbol": "B",
                        "name": "Drugi",
                        "quantity": 8,
                    },
                ],
            )

        with self.assertRaises(ValueError):
            self.store.update_order(
                "ZL-903",
                code="ZL-903",
                client="Klient",
                deadline="2026-11-05",
                priority="NORMALNY",
                status="NOWE",
                items=[
                    {
                        "id": second_id,
                        "symbol": "B",
                        "name": "Drugi",
                        "quantity": 8,
                    }
                ],
            )

    def test_started_item_quantity_can_increase_but_not_below_processed(self) -> None:
        created = self.store.create_order(
            code="ZL-904",
            client="Klient",
            deadline="2026-11-05",
            priority="NORMALNY",
            status="NOWE",
            items=[{"symbol": "A", "name": "Produkt", "quantity": 10}],
        )
        item_id = int(created["items"][0]["id"])
        session = self.store.start_production_session(
            "ZL-904",
            "Laser",
            ["Dawid"],
            order_item_id=item_id,
        )
        self.store.add_department_good_qty(
            "ZL-904",
            "Laser",
            3,
            order_item_id=item_id,
            session_id=int(session["id"]),
        )

        increased = self.store.update_order(
            "ZL-904",
            code="ZL-904",
            client="Klient",
            deadline="2026-11-05",
            priority="NORMALNY",
            status="NOWE",
            items=[
                {
                    "id": item_id,
                    "symbol": "A",
                    "name": "Produkt",
                    "quantity": 12,
                }
            ],
        )
        self.assertEqual(int(increased["items"][0]["id"]), item_id)
        self.assertEqual(int(increased["items"][0]["quantity"]), 12)
        capacity = self.store.get_item_department_capacity(
            "ZL-904",
            item_id,
            "Laser",
        )
        self.assertEqual(int(capacity["remaining"]), 9)

        with self.assertRaises(ValueError):
            self.store.update_order(
                "ZL-904",
                code="ZL-904",
                client="Klient",
                deadline="2026-11-05",
                priority="NORMALNY",
                status="NOWE",
                items=[
                    {
                        "id": item_id,
                        "symbol": "A",
                        "name": "Produkt",
                        "quantity": 2,
                    }
                ],
            )

    def test_production_session_lifecycle(self) -> None:
        session = self.store.start_production_session(
            "ZL-740",
            "Zgrzewarki",
            ["Dawid", "Marek"],
            actor="test-user",
        )
        self.assertEqual(session["status"], "AKTYWNA")
        self.assertEqual(
            [worker["worker_name"] for worker in session["workers"]],
            ["Dawid", "Marek"],
        )

        paused = self.store.pause_production_session(
            "ZL-740",
            "Zgrzewarki",
            actor="test-user",
        )
        self.assertEqual(paused["status"], "WSTRZYMANA")

        resumed = self.store.resume_production_session(
            "ZL-740",
            "Zgrzewarki",
            actor="test-user",
        )
        self.assertEqual(resumed["status"], "AKTYWNA")

        result = self.store.add_department_good_qty(
            "ZL-740",
            "Zgrzewarki",
            1,
            actor="test-user",
            session_id=int(resumed["id"]),
        )
        self.assertEqual(result["added"], 1)

        session_id = self.store.finish_production_session(
            "ZL-740",
            "Zgrzewarki",
            actor="test-user",
        )
        self.assertGreater(session_id, 0)
        self.assertIsNone(
            self.store.get_department_session("ZL-740", "Zgrzewarki")
        )

        events = self.store.list_audit_events(
            entity_type="order",
            entity_id="ZL-740",
            limit=100,
        )
        actions = {event["action"] for event in events}
        self.assertIn("session_started", actions)
        self.assertIn("session_paused", actions)
        self.assertIn("session_resumed", actions)
        self.assertIn("session_finished", actions)

    def test_session_workers_can_join_and_leave(self) -> None:
        session = self.store.start_production_session(
            "ZL-740",
            "Zgrzewarki",
            ["Dawid"],
            actor="test-user",
        )
        self.assertEqual(len(session["workers"]), 1)

        session = self.store.add_session_worker(
            "ZL-740",
            "Zgrzewarki",
            "Marek",
            actor="test-user",
        )
        active = [
            worker
            for worker in session["workers"]
            if worker["left_at"] is None
        ]
        self.assertEqual(
            [worker["worker_name"] for worker in active],
            ["Dawid", "Marek"],
        )

        session = self.store.remove_session_worker(
            "ZL-740",
            "Zgrzewarki",
            "Dawid",
            actor="test-user",
        )
        active = [
            worker
            for worker in session["workers"]
            if worker["left_at"] is None
        ]
        self.assertEqual(
            [worker["worker_name"] for worker in active],
            ["Marek"],
        )

        with self.assertRaises(ValueError):
            self.store.remove_session_worker(
                "ZL-740",
                "Zgrzewarki",
                "Marek",
                actor="test-user",
            )

        events = self.store.list_audit_events(
            entity_type="order",
            entity_id="ZL-740",
            limit=100,
        )
        actions = {event["action"] for event in events}
        self.assertIn("session_worker_joined", actions)
        self.assertIn("session_worker_left", actions)

    def test_duplicate_active_worker_is_blocked(self) -> None:
        self.store.start_production_session(
            "ZL-740",
            "Zgrzewarki",
            ["Dawid"],
        )
        with self.assertRaises(ValueError):
            self.store.add_session_worker(
                "ZL-740",
                "Zgrzewarki",
                "Dawid",
            )

    def test_cannot_start_second_open_session(self) -> None:
        self.store.start_production_session(
            "ZL-740",
            "Zgrzewarki",
            ["Dawid"],
        )
        with self.assertRaises(ValueError):
            self.store.start_production_session(
                "ZL-740",
                "Zgrzewarki",
                ["Marek"],
            )

    def test_quality_event_is_bound_to_specific_order_item(self) -> None:
        order = self.store.get_order("ZL-740")
        self.assertIsNotNone(order)

        selected = None
        for item in order["items"]:
            try:
                capacity = self.store.get_item_department_capacity(
                    "ZL-740",
                    int(item["id"]),
                    "Zgrzewarki",
                )
            except ValueError:
                continue
            if int(capacity["available_now"]) > 0:
                selected = item
                break

        self.assertIsNotNone(selected)
        item_id = int(selected["id"])
        before = self.store.get_item_department_capacity(
            "ZL-740",
            item_id,
            "Zgrzewarki",
        )

        session = self.store.start_production_session(
            "ZL-740",
            "Zgrzewarki",
            ["Dawid"],
            actor="test-user",
        )

        result = self.store.report_quality_quantity(
            "ZL-740",
            "Zgrzewarki",
            "BRAK",
            1,
            reason="Test pozycji",
            actor="test-user",
            session_id=int(session["id"]),
            order_item_id=item_id,
        )
        self.assertEqual(result["order_item_id"], item_id)

        after = self.store.get_item_department_capacity(
            "ZL-740",
            item_id,
            "Zgrzewarki",
        )
        self.assertEqual(
            after["available_now"],
            before["available_now"] - 1,
        )

        events = self.store.list_quality_events(
            code="ZL-740",
            department="Zgrzewarki",
        )
        bound = next(
            event
            for event in events
            if int(event["order_item_id"] or 0) == item_id
        )
        self.assertEqual(bound["symbol"], selected["symbol"])
        self.assertEqual(bound["name"], selected["name"])

    def test_quality_reporter_is_bound_to_active_session_crew(self) -> None:
        reporter = self.store.create_employee(
            name="Reporter Jakości",
            department="Zgrzewarki",
            competency="Produkcja",
        )
        outsider = self.store.create_employee(
            name="Poza Obsada",
            department="Zgrzewarki",
            competency="Produkcja",
        )

        order = self.store.get_order("ZL-740")
        self.assertIsNotNone(order)
        item = next(
            item
            for item in order["items"]
            if self.store.get_item_department_capacity(
                "ZL-740",
                int(item["id"]),
                "Zgrzewarki",
            )["available_now"] > 0
        )
        item_id = int(item["id"])

        session = self.store.start_production_session(
            "ZL-740",
            "Zgrzewarki",
            ["Reporter Jakości"],
            order_item_id=item_id,
        )

        result = self.store.report_quality_quantity(
            "ZL-740",
            "Zgrzewarki",
            "BRAK",
            1,
            reason="Błąd zgrzewu",
            session_id=int(session["id"]),
            order_item_id=item_id,
            reporter_employee_id=int(reporter["id"]),
        )
        self.assertEqual(result["reporter"], "Reporter Jakości")
        self.assertEqual(
            result["reporter_employee_id"],
            int(reporter["id"]),
        )

        event = self.store.list_quality_events(
            code="ZL-740",
            department="Zgrzewarki",
        )[0]
        self.assertEqual(event["reporter_name"], "Reporter Jakości")
        self.assertEqual(
            int(event["reporter_employee_id"]),
            int(reporter["id"]),
        )

        with self.assertRaisesRegex(
            ValueError,
            "nie należy do aktualnej obsady",
        ):
            self.store.report_quality_quantity(
                "ZL-740",
                "Zgrzewarki",
                "BRAK",
                1,
                reason="Błąd zgrzewu",
                session_id=int(session["id"]),
                order_item_id=item_id,
                reporter_employee_id=int(outsider["id"]),
            )

    def test_quality_cannot_exceed_selected_item_capacity(self) -> None:
        order = self.store.get_order("ZL-740")
        self.assertIsNotNone(order)
        item = next(
            item
            for item in order["items"]
            if self.store.get_item_department_capacity(
                "ZL-740",
                int(item["id"]),
                "Zgrzewarki",
            )["available_now"] > 0
        )
        item_id = int(item["id"])
        capacity = self.store.get_item_department_capacity(
            "ZL-740",
            item_id,
            "Zgrzewarki",
        )

        with self.assertRaisesRegex(ValueError, "maksymalnie"):
            self.store.report_quality_quantity(
                "ZL-740",
                "Zgrzewarki",
                "ZŁOM",
                int(capacity["available_now"]) + 1,
                reason="Uszkodzenie mechaniczne",
                order_item_id=item_id,
            )

    def test_quality_event_reduces_available_capacity(self) -> None:
        session = self.store.start_production_session(
            "ZL-740",
            "Zgrzewarki",
            ["Dawid"],
            actor="test-user",
        )
        before = self.store.get_department_order_capacity(
            "ZL-740",
            "Zgrzewarki",
        )

        result = self.store.report_quality_quantity(
            "ZL-740",
            "Zgrzewarki",
            "BRAK",
            2,
            reason="Nieprawidłowy zgrzew",
            note="Test jakości",
            actor="test-user",
            session_id=int(session["id"]),
        )
        self.assertEqual(result["kind"], "BRAK")
        self.assertEqual(result["quantity"], 2)

        after = self.store.get_department_order_capacity(
            "ZL-740",
            "Zgrzewarki",
        )
        self.assertEqual(
            after["available_now"],
            before["available_now"] - 2,
        )

        events = self.store.list_quality_events(
            code="ZL-740",
            department="Zgrzewarki",
        )
        self.assertTrue(
            any(
                event["kind"] == "BRAK"
                and int(event["quantity"]) == 2
                and event["reason"] == "Nieprawidłowy zgrzew"
                for event in events
            )
        )

    def test_quality_summary_counts_types(self) -> None:
        session = self.store.start_production_session(
            "ZL-740",
            "Zgrzewarki",
            ["Dawid"],
        )
        for kind, quantity in (
            ("BRAK", 1),
            ("POPRAWKA", 1),
            ("ZŁOM", 1),
        ):
            self.store.report_quality_quantity(
                "ZL-740",
                "Zgrzewarki",
                kind,
                quantity,
                reason="Test",
                session_id=int(session["id"]),
                rework_target_department=(
                    "Giętarki" if kind == "POPRAWKA" else None
                ),
            )

        summary = self.store.quality_summary()
        self.assertEqual(summary["reject"], 1)
        self.assertEqual(summary["rework"], 1)
        self.assertEqual(summary["scrap"], 1)

    def test_rework_targets_are_earlier_stages(self) -> None:
        targets = self.store.get_rework_target_departments(
            "ZL-740",
            "Zgrzewarki",
        )
        self.assertIn("Giętarki", targets)
        self.assertIn("Laser", targets)
        self.assertNotIn("Malarnia", targets)

    def test_rework_full_cycle_returns_capacity_to_source(self) -> None:
        session = self.store.start_production_session(
            "ZL-740",
            "Zgrzewarki",
            ["Dawid"],
            actor="test-user",
        )
        before = self.store.get_department_order_capacity(
            "ZL-740",
            "Zgrzewarki",
        )

        result = self.store.report_quality_quantity(
            "ZL-740",
            "Zgrzewarki",
            "POPRAWKA",
            2,
            reason="Korekta elementu",
            note="Test obiegu",
            actor="test-user",
            session_id=int(session["id"]),
            rework_target_department="Giętarki",
        )
        self.assertEqual(result["kind"], "POPRAWKA")
        self.assertEqual(result["rework_target_department"], "Giętarki")

        after_report = self.store.get_department_order_capacity(
            "ZL-740",
            "Zgrzewarki",
        )
        self.assertEqual(
            after_report["available_now"],
            before["available_now"] - 2,
        )

        jobs = self.store.list_rework_jobs(code="ZL-740")
        self.assertGreaterEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["status"], "DO_NAPRAWY")
        self.assertEqual(job["target_department"], "Giętarki")

        job = self.store.transition_rework_job(
            int(job["id"]),
            "START",
            actor="test-user",
        )
        self.assertEqual(job["status"], "W_NAPRAWIE")

        job = self.store.transition_rework_job(
            int(job["id"]),
            "NAPRAWIONE",
            actor="test-user",
        )
        self.assertEqual(job["status"], "DO_KONTROLI")

        job = self.store.transition_rework_job(
            int(job["id"]),
            "AKCEPTUJ",
            actor="test-user",
        )
        self.assertEqual(job["status"], "ZAMKNIĘTA")

        after_accept = self.store.get_department_order_capacity(
            "ZL-740",
            "Zgrzewarki",
        )
        self.assertEqual(
            after_accept["available_now"],
            before["available_now"],
        )

    def test_rework_scrap_does_not_return_capacity(self) -> None:
        session = self.store.start_production_session(
            "ZL-740",
            "Zgrzewarki",
            ["Dawid"],
        )
        before = self.store.get_department_order_capacity(
            "ZL-740",
            "Zgrzewarki",
        )

        self.store.report_quality_quantity(
            "ZL-740",
            "Zgrzewarki",
            "POPRAWKA",
            1,
            reason="Do decyzji",
            session_id=int(session["id"]),
            rework_target_department="Giętarki",
        )
        job = self.store.list_rework_jobs(code="ZL-740")[0]

        job = self.store.transition_rework_job(
            int(job["id"]),
            "ZŁOM",
        )
        self.assertEqual(job["status"], "ZŁOM")

        after_scrap = self.store.get_department_order_capacity(
            "ZL-740",
            "Zgrzewarki",
        )
        self.assertEqual(
            after_scrap["available_now"],
            before["available_now"] - 1,
        )

    def test_production_isolated_per_order_item(self) -> None:
        created = self.store.create_order(
            code="ZL-917",
            client="Test pozycji",
            deadline="2026-11-20",
            priority="NORMALNY",
            status="NOWE",
            items=[
                {"symbol": "P-1", "name": "Produkt pierwszy", "quantity": 10},
                {"symbol": "P-2", "name": "Produkt drugi", "quantity": 8},
            ],
            actor="test-user",
        )
        item_1 = int(created["items"][0]["id"])
        item_2 = int(created["items"][1]["id"])

        queue = [
            row
            for row in self.store.list_department_queue("Laser")
            if row["code"] == "ZL-917"
        ]
        self.assertEqual(len(queue), 2)
        self.assertEqual(
            {int(row["order_item_id"]) for row in queue},
            {item_1, item_2},
        )

        session_1 = self.store.start_production_session(
            "ZL-917",
            "Laser",
            ["Dawid"],
            order_item_id=item_1,
            actor="test-user",
        )
        session_2 = self.store.start_production_session(
            "ZL-917",
            "Laser",
            ["Marek"],
            order_item_id=item_2,
            actor="test-user",
        )
        self.assertNotEqual(session_1["id"], session_2["id"])
        self.assertEqual(int(session_1["order_item_id"]), item_1)
        self.assertEqual(int(session_2["order_item_id"]), item_2)

        self.store.add_department_good_qty(
            "ZL-917",
            "Laser",
            3,
            order_item_id=item_1,
            session_id=int(session_1["id"]),
            actor="test-user",
        )

        queue = [
            row
            for row in self.store.list_department_queue("Laser")
            if row["code"] == "ZL-917"
        ]
        first = next(row for row in queue if int(row["order_item_id"]) == item_1)
        second = next(row for row in queue if int(row["order_item_id"]) == item_2)
        self.assertEqual(int(first["good_qty"]), 3)
        self.assertEqual(int(second["good_qty"]), 0)

        self.store.pause_production_session(
            "ZL-917",
            "Laser",
            order_item_id=item_1,
            actor="test-user",
        )
        paused = self.store.get_department_session(
            "ZL-917",
            "Laser",
            item_1,
        )
        still_active = self.store.get_department_session(
            "ZL-917",
            "Laser",
            item_2,
        )
        self.assertEqual(paused["status"], "WSTRZYMANA")
        self.assertEqual(still_active["status"], "AKTYWNA")

    def test_item_session_audit_contains_order_item_id(self) -> None:
        created = self.store.create_order(
            code="ZL-918",
            client="Audit pozycji",
            deadline="2026-11-21",
            priority="NORMALNY",
            status="NOWE",
            items=[
                {"symbol": "AUD-1", "name": "Pozycja audytowa", "quantity": 4},
            ],
            actor="test-user",
        )
        item_id = int(created["items"][0]["id"])
        session = self.store.start_production_session(
            "ZL-918",
            "Laser",
            ["Dawid"],
            order_item_id=item_id,
            actor="test-user",
        )
        self.store.add_department_good_qty(
            "ZL-918",
            "Laser",
            1,
            order_item_id=item_id,
            session_id=int(session["id"]),
            actor="test-user",
        )

        events = self.store.list_audit_events(
            entity_type="order",
            entity_id="ZL-918",
            limit=100,
        )
        matching = [
            event
            for event in events
            if event["action"] in {"session_started", "good_quantity_added"}
        ]
        self.assertTrue(matching)
        for event in matching:
            payload = event["payload"]
            self.assertEqual(int(payload["order_item_id"]), item_id)

    def test_worker_cannot_be_assigned_to_two_open_sessions(self) -> None:
        self.store.ensure_development_employees_seeded()
        first = self.store.create_order(
            code="ZL-W01",
            client="Obsada",
            deadline="2026-11-25",
            priority="NORMALNY",
            status="NOWE",
            items=[{"symbol": "W-1", "name": "Pierwszy", "quantity": 5}],
        )
        second = self.store.create_order(
            code="ZL-W02",
            client="Obsada",
            deadline="2026-11-25",
            priority="NORMALNY",
            status="NOWE",
            items=[{"symbol": "W-2", "name": "Drugi", "quantity": 5}],
        )
        item_1 = int(first["items"][0]["id"])
        item_2 = int(second["items"][0]["id"])

        session = self.store.start_production_session(
            "ZL-W01",
            "Laser",
            ["Dawid"],
            order_item_id=item_1,
        )
        self.assertIsNotNone(session["workers"][0]["employee_id"])

        with self.assertRaisesRegex(ValueError, "jest już przypisany"):
            self.store.start_production_session(
                "ZL-W02",
                "Laser",
                ["Dawid"],
                order_item_id=item_2,
            )

    def test_worker_can_move_after_leaving_previous_session(self) -> None:
        self.store.ensure_development_employees_seeded()
        first = self.store.create_order(
            code="ZL-W03",
            client="Obsada",
            deadline="2026-11-25",
            priority="NORMALNY",
            status="NOWE",
            items=[{"symbol": "W-3", "name": "Pierwszy", "quantity": 5}],
        )
        second = self.store.create_order(
            code="ZL-W04",
            client="Obsada",
            deadline="2026-11-25",
            priority="NORMALNY",
            status="NOWE",
            items=[{"symbol": "W-4", "name": "Drugi", "quantity": 5}],
        )
        item_1 = int(first["items"][0]["id"])
        item_2 = int(second["items"][0]["id"])

        self.store.start_production_session(
            "ZL-W03",
            "Laser",
            ["Dawid", "Marek"],
            order_item_id=item_1,
        )
        self.store.remove_session_worker(
            "ZL-W03",
            "Laser",
            "Dawid",
            order_item_id=item_1,
        )

        moved = self.store.start_production_session(
            "ZL-W04",
            "Laser",
            ["Dawid"],
            order_item_id=item_2,
        )
        self.assertEqual(moved["workers"][0]["worker_name"], "Dawid")

    def test_finished_session_closes_worker_time_and_history(self) -> None:
        self.store.ensure_development_employees_seeded()
        created = self.store.create_order(
            code="ZL-W05",
            client="Obsada",
            deadline="2026-11-25",
            priority="NORMALNY",
            status="NOWE",
            items=[{"symbol": "W-5", "name": "Historia", "quantity": 5}],
        )
        item_id = int(created["items"][0]["id"])
        employees = self.store.list_employees(active_only=True)
        dawid = next(row for row in employees if row["name"] == "Dawid")
        employee_id = int(dawid["id"])

        session = self.store.start_production_session(
            "ZL-W05",
            "Laser",
            ["Dawid"],
            order_item_id=item_id,
        )
        self.store.finish_production_session(
            "ZL-W05",
            "Laser",
            order_item_id=item_id,
        )

        history = self.store.list_worker_work_log(employee_id=employee_id)
        row = next(
            entry
            for entry in history
            if int(entry["session_id"]) == int(session["id"])
        )
        self.assertEqual(int(row["employee_id"]), employee_id)
        self.assertIsNotNone(row["left_at"])
        self.assertGreaterEqual(int(row["duration_seconds"]), 0)
        self.assertEqual(row["code"], "ZL-W05")
        self.assertEqual(int(row["order_item_id"]), item_id)

    def test_status_change_is_audited(self) -> None:
        self.store.set_department_order_status(
            "ZL-740",
            "Zgrzewarki",
            "AKTYWNE",
            actor="test-user",
        )
        self.store.set_department_order_status(
            "ZL-740",
            "Zgrzewarki",
            "WSTRZYMANE",
            actor="test-user",
        )

        events = self.store.list_audit_events(
            entity_type="order",
            entity_id="ZL-740",
            limit=50,
        )
        status_events = [
            event
            for event in events
            if event["action"] == "operation_status_changed"
        ]
        self.assertGreaterEqual(len(status_events), 2)


if __name__ == "__main__":
    unittest.main()

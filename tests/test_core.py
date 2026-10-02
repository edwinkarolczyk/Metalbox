from __future__ import annotations

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

    def test_update_order_before_production_can_change_items(self) -> None:
        self.store.create_order(
            code="ZL-901",
            client="Klient",
            deadline="2026-11-05",
            priority="NORMALNY",
            status="NOWE",
            items=[{"symbol": "A", "name": "Produkt", "quantity": 10}],
        )

        updated = self.store.update_order(
            "ZL-901",
            code="ZL-901",
            client="Nowy klient",
            deadline="2026-11-10",
            priority="WYSOKI",
            status="NOWE",
            items=[
                {"symbol": "A", "name": "Produkt", "quantity": 15},
                {"symbol": "B", "name": "Drugi", "quantity": 5},
            ],
        )
        self.assertEqual(updated["client"], "Nowy klient")
        self.assertEqual(len(updated["items"]), 2)
        self.assertEqual(updated["items"][0]["quantity"], 15)

    def test_update_order_after_production_blocks_structural_change(self) -> None:
        capacity = self.store.get_department_order_capacity("ZL-740", "Zgrzewarki")
        self.assertGreater(capacity["available_now"], 0)
        self.store.add_department_good_qty("ZL-740", "Zgrzewarki", 1)

        order = self.store.get_order("ZL-740")
        self.assertIsNotNone(order)
        changed_items = [
            {
                "symbol": item["symbol"],
                "name": item["name"],
                "quantity": int(item["quantity"]) + (1 if index == 0 else 0),
            }
            for index, item in enumerate(order["items"])
        ]

        with self.assertRaises(ValueError):
            self.store.update_order(
                "ZL-740",
                code="ZL-740",
                client=order["client"],
                deadline=order["deadline"],
                priority=order["priority"],
                status=order["status"],
                items=changed_items,
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

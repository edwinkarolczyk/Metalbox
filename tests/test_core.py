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
        with sqlite3.connect(self.db_path) as db:
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
        self.assertEqual(version, SCHEMA_VERSION)

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

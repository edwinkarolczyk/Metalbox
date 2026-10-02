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

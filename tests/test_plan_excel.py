from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from metalbox_core import MetalboxStore
from plan_excel import compare_plan_rows, read_plan_snapshot, safe_snapshot


class PlanExcelTests(unittest.TestCase):
    def _write_plan(self, path: Path, rows: list[list[object]]) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "PLAN"
        sheet.append(["PLAN PRODUKCJI"])
        sheet.append(["Nr ZL", "Produkt", "Ilość", "Wysyłka", "RAL"])
        for row in rows:
            sheet.append(row)
        workbook.save(path)
        workbook.close()

    def test_source_is_closed_before_snapshot_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "plan.xlsx"
            snapshots = root / "snapshots"
            self._write_plan(
                source,
                [
                    ["740", "1.435.135 SC600 RP Sorta", 65, "18.10", "9011"],
                    ["", "1.325.68 SC400 RP Sorta", 120, "", "9011"],
                ],
            )

            info = safe_snapshot(source, snapshots)
            self.assertTrue(info.path.exists())
            self.assertGreater(info.size_bytes, 0)

            # Na Windows usunięcie nie powiedzie się, jeśli źródło nadal ma otwarty uchwyt.
            source.unlink()
            self.assertFalse(source.exists())

            parsed = read_plan_snapshot(info.path)
            self.assertEqual(parsed.sheet_name, "PLAN")
            self.assertEqual(parsed.header_row, 2)
            self.assertEqual(len(parsed.rows), 2)
            self.assertEqual(parsed.rows[0]["order_code"], "740")
            self.assertEqual(parsed.rows[1]["order_code"], "740")
            self.assertEqual(parsed.rows[0]["symbol"], "1.435.135")
            self.assertEqual(parsed.rows[0]["name"], "SC600 RP Sorta")
            self.assertEqual(parsed.rows[1]["quantity"], 120.0)
            self.assertEqual(parsed.rows[0]["ral"], "9011")

    def test_compare_detects_added_changed_and_removed_rows(self) -> None:
        previous = [
            {
                "row_key": "740|a|produkt a#1",
                "row_no": 3,
                "order_code": "740",
                "symbol": "A",
                "name": "Produkt A",
                "quantity": 10.0,
                "shipping": "18.10",
                "ral": "9011",
            },
            {
                "row_key": "740|b|produkt b#1",
                "row_no": 4,
                "order_code": "740",
                "symbol": "B",
                "name": "Produkt B",
                "quantity": 5.0,
                "shipping": "18.10",
                "ral": "9011",
            },
        ]
        current = [
            {
                "row_key": "740|a|produkt a#1",
                "row_no": 3,
                "order_code": "740",
                "symbol": "A",
                "name": "Produkt A",
                "quantity": 12.0,
                "shipping": "18.10",
                "ral": "9011",
            },
            {
                "row_key": "740|c|produkt c#1",
                "row_no": 4,
                "order_code": "740",
                "symbol": "C",
                "name": "Produkt C",
                "quantity": 3.0,
                "shipping": "19.10",
                "ral": "7042",
            },
        ]

        diff = compare_plan_rows(previous, current)
        self.assertEqual([row["symbol"] for row in diff["added"]], ["C"])
        self.assertEqual([row["symbol"] for row in diff["removed"]], ["B"])
        self.assertEqual(len(diff["changed"]), 1)
        self.assertEqual(
            diff["changed"][0]["changes"]["quantity"],
            {"before": 10.0, "after": 12.0},
        )

    def test_snapshot_rows_are_persisted_for_next_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MetalboxStore(Path(temp) / "metalbox.sqlite3")
            rows = [
                {
                    "row_key": "740|a|produkt a#1",
                    "row_no": 3,
                    "order_code": "740",
                    "symbol": "A",
                    "name": "Produkt A",
                    "quantity": 10.0,
                    "shipping": "18.10",
                    "ral": "9011",
                }
            ]

            snapshot = store.create_plan_snapshot(
                source_name="plan.xlsx",
                snapshot_path="snapshot.xlsx",
                sha256="abc123",
                size_bytes=1234,
                sheet_name="PLAN",
                header_row=2,
                rows=rows,
            )

            latest = store.get_latest_plan_snapshot()
            self.assertIsNotNone(latest)
            self.assertEqual(int(latest["id"]), int(snapshot["id"]))
            self.assertEqual(latest["status"], "PODGLĄD")

            stored_rows = store.list_plan_snapshot_rows(int(snapshot["id"]))
            self.assertEqual(len(stored_rows), 1)
            self.assertEqual(stored_rows[0]["symbol"], "A")
            self.assertEqual(stored_rows[0]["quantity"], 10.0)


if __name__ == "__main__":
    unittest.main()

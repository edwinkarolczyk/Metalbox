from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from plan_sources import PlanSources


def make_excel(path: Path, *, qty: int, symbol: str = "1.435.135") -> None:
    workbook = """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
    <sheets><sheet name="PLAN" sheetId="1" r:id="rId1"/></sheets></workbook>"""
    rels = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet1.xml"/></Relationships>"""
    sheet = f"""<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
    <sheetData>
      <row r="1"><c r="A1" t="inlineStr"><is><t>Nr ZL</t></is></c>
        <c r="B1" t="inlineStr"><is><t>Produkt</t></is></c>
        <c r="C1" t="inlineStr"><is><t>Ilość</t></is></c></row>
      <row r="2"><c r="A2" t="inlineStr"><is><t>740</t></is></c>
        <c r="B2" t="inlineStr"><is><t>{symbol} SC600</t></is></c>
        <c r="C2"><v>{qty}</v></c></row>
    </sheetData></worksheet>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


class MultiSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan_a = self.root / "a.xlsx"
        self.plan_b = self.root / "b.xlsx"
        make_excel(self.plan_a, qty=65)
        make_excel(self.plan_b, qty=70)
        self.registry = PlanSources(self.root / "config")
        self.source_a = self.registry.add_source(name="Excel 1", path=str(self.plan_a))
        self.source_b = self.registry.add_source(name="Excel 2", path=str(self.plan_b))

    def test_two_sources_preserve_separate_snapshot_and_conflict(self) -> None:
        first = self.registry.scan(self.source_a["id"])
        second = self.registry.scan(self.source_b["id"])
        self.assertNotEqual(first["snapshot_path"], second["snapshot_path"])
        self.assertEqual(first["rows"][0]["quantity"], 65)
        self.assertEqual(second["rows"][0]["quantity"], 70)
        self.assertEqual(first["source_name"], "Excel 1")
        self.assertEqual(second["source_name"], "Excel 2")
        conflicts = self.registry.check_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["status"], "DO ROZSTRZYGNIĘCIA")
        self.assertEqual(conflicts[0]["sources"], ["Excel 1", "Excel 2"])

    def test_damaged_excel_preserves_last_good_snapshot(self) -> None:
        first = self.registry.scan(self.source_a["id"])
        self.plan_a.write_bytes(b"not-an-excel-archive")
        broken = self.registry.scan(self.source_a["id"])
        self.assertEqual(broken["status"], "BŁĄD ODCZYTU")
        self.assertEqual(broken["rows"], first["rows"])
        self.assertEqual(broken["sha256"], first["sha256"])
        self.assertEqual(self.registry.scan(self.source_b["id"])["row_count"], 1)

    def test_missing_file_keeps_last_successful_state_and_other_source(self) -> None:
        first = self.registry.scan(self.source_a["id"])
        self.plan_a.unlink()
        broken = self.registry.scan(self.source_a["id"])
        second = self.registry.scan(self.source_b["id"])
        self.assertEqual(broken["status"], "BŁĄD ODCZYTU")
        self.assertEqual(broken["sha256"], first["sha256"])
        self.assertEqual(broken["rows"], first["rows"])
        self.assertEqual(second["rows"][0]["quantity"], 70)
        self.assertEqual(
            self.registry.get_state(self.source_a["id"])["row_count"], 1
        )

    def test_same_source_change_compares_against_itself_not_second_excel(self) -> None:
        self.registry.scan(self.source_a["id"])
        self.registry.scan(self.source_b["id"])
        make_excel(self.plan_a, qty=90)
        third = self.registry.scan(self.source_a["id"])
        self.assertEqual(third["change_counts"], {"added": 0, "removed": 0, "changed": 1})
        self.assertEqual(third["diff"]["changed"][0]["changes"]["quantity"],
                         {"before": 65.0, "after": 90.0})
        self.assertEqual(self.registry.get_state(self.source_b["id"])["rows"][0]["quantity"], 70)

    def test_unreviewed_changes_remain_visible_after_unchanged_poll(self) -> None:
        first = self.registry.scan(self.source_a["id"])
        self.assertEqual(first["status"], "NOWE ZMIANY")
        unchanged = self.registry.scan(self.source_a["id"])
        self.assertEqual(unchanged["status"], "NOWE ZMIANY")
        self.assertEqual(unchanged["change_counts"]["added"], 1)

    def test_unchanged_file_is_not_copied_again(self) -> None:
        first = self.registry.scan(self.source_a["id"])
        again = self.registry.scan(self.source_a["id"])
        self.assertEqual(first["snapshot_path"], again["snapshot_path"])
        self.assertEqual(
            len(list((self.registry.root / "snapshots" / self.source_a["id"]).glob("*.xlsx"))),
            1,
        )

    def test_duplicate_path_is_rejected_and_state_can_be_reopened(self) -> None:
        with self.assertRaisesRegex(ValueError, "już monitorowany"):
            self.registry.add_source(name="kopiuj 1", path=str(self.plan_a))
        with self.assertRaisesRegex(ValueError, "Interwał"):
            self.registry.add_source(name="inny", path=str(self.plan_a), interval_seconds=2)
        self.registry.scan(self.source_a["id"])
        restarted = PlanSources(self.root / "config")
        self.assertEqual(len(restarted.list_sources()), 2)
        self.assertEqual(restarted.get_state(self.source_a["id"])["row_count"], 1)

    def test_combined_preview_blocks_conflict_and_does_not_touch_originals(self) -> None:
        original_a = self.plan_a.read_bytes()
        original_b = self.plan_b.read_bytes()
        self.registry.scan(self.source_a["id"])
        self.registry.scan(self.source_b["id"])
        with self.assertRaisesRegex(ValueError, "wspólnych pozycji"):
            self.registry.build_combined_preview()
        self.assertEqual(self.plan_a.read_bytes(), original_a)
        self.assertEqual(self.plan_b.read_bytes(), original_b)

    def test_combined_preview_keeps_provenance_and_unique_keys(self) -> None:
        make_excel(self.plan_b, qty=30, symbol="1.325.68")
        self.registry.scan(self.source_a["id"])
        self.registry.scan(self.source_b["id"])
        preview = self.registry.build_combined_preview()
        self.assertEqual(preview["row_count"], 2)
        self.assertEqual({x["source_name"] for x in preview["rows"]},
                         {"Excel 1", "Excel 2"})
        self.assertEqual(len({x["row_key"] for x in preview["rows"]}), 2)
        self.assertEqual([x["row_no"] for x in preview["rows"]], [1, 2])
        self.assertEqual(len(preview["sources"]), 2)

    def test_manual_conflict_resolution_selects_one_source_and_expires(self) -> None:
        self.registry.scan(self.source_a["id"])
        self.registry.scan(self.source_b["id"])
        choice = self.registry.resolve_conflict(
            order_code="740", symbol="1.435.135",
            chosen_source_id=self.source_a["id"], actor="Kierownik",
        )
        self.assertEqual(choice["chosen_source_id"], self.source_a["id"])
        preview = self.registry.build_combined_preview()
        self.assertEqual(preview["row_count"], 1)
        self.assertEqual(preview["rows"][0]["quantity"], 65)
        self.assertEqual(preview["rows"][0]["source_id"], self.source_a["id"])
        make_excel(self.plan_b, qty=72)
        self.registry.scan(self.source_b["id"])
        self.assertIsNone(self.registry.check_conflicts()[0]["chosen_source_id"])
        with self.assertRaisesRegex(ValueError, "nierozstrzygniętych"):
            self.registry.build_combined_preview()

    def test_duplicate_identical_excel_row_still_requires_choice(self) -> None:
        make_excel(self.plan_b, qty=65)
        self.registry.scan(self.source_a["id"])
        self.registry.scan(self.source_b["id"])
        self.assertEqual(self.registry.check_conflicts()[0]["status"], "DUPLIKAT")
        with self.assertRaisesRegex(ValueError, "nierozstrzygniętych"):
            self.registry.build_combined_preview()
        self.registry.resolve_conflict(
            order_code="740", symbol="1.435.135",
            chosen_source_id=self.source_b["id"],
        )
        self.assertEqual(self.registry.build_combined_preview()["row_count"], 1)

    def test_combined_preview_blocks_unavailable_or_stale_source(self) -> None:
        make_excel(self.plan_b, qty=30, symbol="1.325.68")
        self.registry.scan(self.source_a["id"])
        self.registry.scan(self.source_b["id"])
        self.plan_a.unlink()
        with self.assertRaisesRegex(ValueError, "niedostępny"):
            self.registry.build_combined_preview()
        make_excel(self.plan_a, qty=71)
        with self.assertRaisesRegex(ValueError, "zmieniło się"):
            self.registry.build_combined_preview()
        self.registry.scan(self.source_a["id"])
        self.assertEqual(self.registry.build_combined_preview()["row_count"], 2)

    def test_disable_source_does_not_remove_history(self) -> None:
        state = self.registry.scan(self.source_a["id"])
        self.registry.update_source(self.source_a["id"], enabled=False)
        self.assertEqual(
            self.registry.scan(self.source_a["id"])["status"], "WYŁĄCZONE"
        )
        self.assertEqual(
            self.registry.get_state(self.source_a["id"])["sha256"], state["sha256"]
        )

    def test_source_path_change_does_not_keep_old_rows(self) -> None:
        self.registry.scan(self.source_a["id"])
        alternate = self.root / "alternate.xlsx"
        make_excel(alternate, qty=21, symbol="1.000.00")
        self.registry.update_source(self.source_a["id"], path=str(alternate))
        self.assertEqual(self.registry.get_state(self.source_a["id"]), {})
        self.assertEqual(self.registry.scan(self.source_a["id"])["rows"][0]["quantity"], 21)

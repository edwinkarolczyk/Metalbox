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

    def test_folder_with_one_excel_and_exclusions_reads_only_selected_copy(self) -> None:
        folder = self.root / "hala"
        folder.mkdir()
        main = folder / "plan.xlsx"
        archive = folder / "plan_archiwum.xlsm"
        lock = folder / "~$plan.xlsx"
        make_excel(main, qty=122)
        original_bytes = main.read_bytes()
        make_excel(archive, qty=999)
        lock.write_bytes(b"temporary lock")
        (folder / "instrukcja.txt").write_text("to nie jest plan")
        source = self.registry.add_source(
            name="Folder hali", path=str(folder), mode="folder",
            exclude_patterns="*archiwum*",
        )
        self.assertEqual(
            self.registry.folder_candidates(str(folder), exclude_patterns="*archiwum*"),
            ["plan.xlsx"],
        )
        state = self.registry.scan(source["id"])
        self.assertEqual(state["rows"][0]["quantity"], 122)
        self.assertEqual(state["source_file"], "plan.xlsx")
        self.assertEqual(main.read_bytes(), original_bytes)
        self.assertTrue(Path(state["snapshot_path"]).is_file())

    def test_folder_multiple_candidates_requires_explicit_choice(self) -> None:
        folder = self.root / "kopie"
        folder.mkdir()
        make_excel(folder / "plan1.xlsx", qty=51)
        make_excel(folder / "plan2.xlsx", qty=81)
        src = self.registry.add_source(
            name="Kopie planu", path=str(folder), mode="folder",
        )
        state = self.registry.scan(src["id"])
        self.assertEqual(state["status"], "BŁĄD ODCZYTU")
        self.assertIn("Wybierz konkretny aktywny plik", state["error"])
        with self.assertRaisesRegex(ValueError, "aktualnego poprawnego odczytu"):
            self.registry.build_combined_preview()
        self.registry.update_source(src["id"], selected_file="plan2.xlsx")
        good = self.registry.scan(src["id"])
        self.assertEqual(good["source_file"], "plan2.xlsx")
        self.assertEqual(good["rows"][0]["quantity"], 81)

    def test_two_independent_excels_can_share_same_folder(self) -> None:
        # Pozostałe źródła z setUp wyłączamy — nie należą do tego podglądu.
        self.registry.update_source(self.source_a["id"], enabled=False)
        self.registry.update_source(self.source_b["id"], enabled=False)
        folder = self.root / "wspolny-folder"
        folder.mkdir()
        make_excel(folder / "laser.xlsx", qty=17, symbol="1.400.10")
        make_excel(folder / "malarnia.xlsx", qty=51, symbol="1.400.11")
        first = self.registry.add_source(
            name="Laser kopia", path=str(folder), mode="folder",
            selected_file="laser.xlsx",
        )
        second = self.registry.add_source(
            name="Malarnia kopia", path=str(folder), mode="folder",
            selected_file="malarnia.xlsx",
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.registry.scan(first["id"])["rows"][0]["quantity"], 17)
        self.assertEqual(self.registry.scan(second["id"])["rows"][0]["quantity"], 51)
        with self.assertRaisesRegex(ValueError, "już monitorowany"):
            self.registry.add_source(
                name="Duplikat lasera", path=str(folder), mode="folder",
                selected_file="laser.xlsx",
            )
        self.assertEqual(self.registry.build_combined_preview()["row_count"], 2)

    def test_selected_folder_file_disappearing_does_not_switch_to_other_copy(self) -> None:
        folder = self.root / "folder"
        folder.mkdir()
        selected = folder / "nowy.xlsx"
        older = folder / "stary.xlsx"
        make_excel(selected, qty=62)
        make_excel(older, qty=19)
        src = self.registry.add_source(
            name="Plan z folderu", path=str(folder), mode="folder",
            selected_file="nowy.xlsx",
        )
        before = self.registry.scan(src["id"])
        selected.unlink()
        after = self.registry.scan(src["id"])
        self.assertEqual(after["status"], "BŁĄD ODCZYTU")
        self.assertEqual(after["sha256"], before["sha256"])
        self.assertEqual(after["rows"], before["rows"])
        with self.assertRaisesRegex(ValueError, "aktualnego poprawnego odczytu"):
            self.registry.build_combined_preview()

    def test_folder_source_rejects_empty_path_and_unsafe_filename(self) -> None:
        with self.assertRaisesRegex(ValueError, "Podaj ścieżkę"):
            self.registry.add_source(name="Bez folderu", path="", mode="folder")
        with self.assertRaisesRegex(ValueError, "samą nazwę"):
            self.registry.add_source(
                name="Niebezpieczny", path=str(self.root), mode="folder",
                selected_file="../secret.xlsx",
            )

    def test_per_source_mapping_is_used_only_on_its_own_snapshot(self) -> None:
        # Ten sam plik może mieć inny arkusz/nagłówki niż drugi plan.
        folder = self.root / "mapowanie"
        folder.mkdir()
        source_excel = folder / "map.xlsx"
        make_excel(source_excel, qty=130)
        source = self.registry.add_source(
            name="Osobne mapowanie", path=str(source_excel),
        )
        self.registry.update_source(
            source["id"],
            column_mapping={
                "sheet_name": "PLAN", "header_row": 1,
                "mapping": {"order_code": 1, "product": 2, "quantity": 3},
            },
        )
        state = self.registry.scan(source["id"])
        self.assertEqual(state["rows"][0]["quantity"], 130)
        self.assertEqual(state["mapping_used"]["sheet_name"], "PLAN")
        self.assertEqual(self.registry.list_sources()[0].get("column_mapping"), {})
        self.assertEqual(self.registry.get_state(source["id"])["status"], "NOWE ZMIANY")
        snapshot_path, source_name = self.registry.mapping_snapshot(source["id"])
        self.assertTrue(snapshot_path.exists())
        self.assertEqual(source_name, "map.xlsx")

    def test_changing_mapping_invalidates_cached_snapshot_state(self) -> None:
        src = self.registry.scan(self.source_a["id"])
        self.registry.update_source(
            self.source_a["id"],
            column_mapping={
                "sheet_name": "PLAN", "header_row": 1,
                "mapping": {"order_code": 1, "product": 2, "quantity": 3},
            },
        )
        self.assertEqual(self.registry.get_state(self.source_a["id"]), {})
        latest = self.registry.scan(self.source_a["id"])
        self.assertEqual(latest["rows"][0]["quantity"], 65)
        self.assertEqual(latest["mapping_used"]["sheet_name"], "PLAN")
        self.assertNotEqual(latest["signature"], src["signature"])

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
        with self.assertRaisesRegex(ValueError, "nierozstrzygniętych pozycji"):
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

    def test_only_accepted_versions_clear_pending_changes(self) -> None:
        make_excel(self.plan_b, qty=30, symbol="1.325.68")
        self.registry.scan(self.source_a["id"])
        self.registry.scan(self.source_b["id"])
        preview = self.registry.build_combined_preview()
        # Podgląd sam niczego nie potwierdza.
        self.assertEqual(self.registry.get_state(self.source_a["id"])["status"], "NOWE ZMIANY")
        accepted = self.registry.acknowledge_accepted_sources(preview["sources"])
        self.assertEqual(accepted, 2)
        self.assertEqual(self.registry.get_state(self.source_a["id"])["status"], "BEZ ZMIAN")
        make_excel(self.plan_b, qty=35, symbol="1.325.68")
        self.registry.scan(self.source_b["id"])
        self.assertEqual(self.registry.acknowledge_accepted_sources(preview["sources"]), 1)
        self.assertEqual(self.registry.get_state(self.source_b["id"])["status"], "NOWE ZMIANY")
        self.assertEqual(self.registry.get_state(self.source_b["id"])["change_counts"]["changed"], 1)

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

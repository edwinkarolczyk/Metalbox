from __future__ import annotations

import hashlib
import os
import posixpath
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


ALLOWED_EXTENSIONS = {".xlsx", ".xlsm"}

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

HEADER_ALIASES = {
    "order_code": {
        "nr zl", "nr zlec", "nr zlecenia", "zlecenie", "zl", "numer zl", "numer zlecenia",
        "nr zlecenia produkcyjnego",
    },
    "symbol": {
        "symbol", "kod", "indeks", "nr produktu", "numer produktu",
        "symbol produktu",
    },
    "product": {
        "produkt", "produkt / nazwa", "produkt/nazwa", "wyrób", "wyrob",
    },
    "name": {
        "nazwa", "nazwa produktu", "opis", "nazwa wyrobu",
    },
    "quantity": {
        "ilosc", "ilość", "qty", "szt", "szt.", "ilosc szt", "ilość szt",
    },
    "shipping": {
        "wysylka", "wysyłka", "termin", "termin realizacji", "data realizacji", "data wysylki", "data wysyłki",
        "termin wysylki", "termin wysyłki",
    },
    "ral": {
        "ral", "kolor", "kolor ral",
    },
}


@dataclass(frozen=True)
class SnapshotInfo:
    path: Path
    source_name: str
    sha256: str
    size_bytes: int
    created_at: str


@dataclass(frozen=True)
class ParsedPlan:
    sheet_name: str
    header_row: int
    rows: list[dict]


def _normalize_header(value: object) -> str:
    text = str(value or "").replace("\xa0", " ").strip().casefold()
    text = re.sub(r"[.:;,]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_snapshot(source: Path, snapshot_dir: Path) -> SnapshotInfo:
    """Kopiuje źródło bajt po bajcie i zamyka je przed jakimkolwiek parsowaniem."""
    source = Path(source)
    snapshot_dir = Path(snapshot_dir)

    if not source.is_file():
        raise FileNotFoundError(f"Nie znaleziono pliku planu: {source}")

    extension = source.suffix.casefold()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Obsługiwane są pliki Excel .xlsx i .xlsm.")

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    temp_path = snapshot_dir / f".snapshot-{stamp}.tmp"

    digest = hashlib.sha256()
    size_bytes = 0

    # Krytyczna zasada: uchwyt do źródła istnieje wyłącznie w tym bloku.
    with source.open("rb") as source_handle, temp_path.open("wb") as target_handle:
        while True:
            chunk = source_handle.read(1024 * 1024)
            if not chunk:
                break
            target_handle.write(chunk)
            digest.update(chunk)
            size_bytes += len(chunk)
        target_handle.flush()
        os.fsync(target_handle.fileno())

    sha256 = digest.hexdigest()
    final_path = snapshot_dir / f"plan-{stamp}-{sha256[:10]}{extension}"
    os.replace(temp_path, final_path)

    return SnapshotInfo(
        path=final_path,
        source_name=source.name,
        sha256=sha256,
        size_bytes=size_bytes,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _xml_root(archive: zipfile.ZipFile, member: str) -> ET.Element:
    try:
        with archive.open(member, "r") as handle:
            return ET.parse(handle).getroot()
    except KeyError as exc:
        raise ValueError(f"Plik Excel jest niekompletny — brak {member}.") from exc
    except ET.ParseError as exc:
        raise ValueError(f"Uszkodzony XML w pliku Excel: {member}.") from exc


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = _xml_root(archive, "xl/sharedStrings.xml")
    result: list[str] = []
    for item in root.findall(f"{{{MAIN_NS}}}si"):
        parts = [
            node.text or ""
            for node in item.iter(f"{{{MAIN_NS}}}t")
        ]
        result.append("".join(parts))
    return result


def _workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str, bool]]:
    workbook = _xml_root(archive, "xl/workbook.xml")
    sheets_node = workbook.find(f"{{{MAIN_NS}}}sheets")
    if sheets_node is None:
        raise ValueError("Plik Excel nie zawiera arkuszy.")

    sheets = list(sheets_node.findall(f"{{{MAIN_NS}}}sheet"))
    if not sheets:
        raise ValueError("Plik Excel nie zawiera arkuszy.")

    active_index = 0
    book_views = workbook.find(f"{{{MAIN_NS}}}bookViews")
    if book_views is not None:
        view = book_views.find(f"{{{MAIN_NS}}}workbookView")
        if view is not None:
            try:
                active_index = int(view.attrib.get("activeTab", "0"))
            except ValueError:
                active_index = 0
    active_index = max(0, min(active_index, len(sheets) - 1))

    rels = _xml_root(archive, "xl/_rels/workbook.xml.rels")
    targets = {
        rel.attrib.get("Id", ""): rel.attrib.get("Target", "")
        for rel in rels.findall(f"{{{PKG_REL_NS}}}Relationship")
    }

    result: list[tuple[str, str, bool]] = []
    for index, sheet in enumerate(sheets):
        rel_id = sheet.attrib.get(f"{{{DOC_REL_NS}}}id", "")
        target = targets.get(rel_id, "")
        if not target:
            continue
        if target.startswith("/"):
            sheet_path = target.lstrip("/")
        else:
            sheet_path = posixpath.normpath(posixpath.join("xl", target))
        result.append(
            (
                str(sheet.attrib.get("name", f"Arkusz {index + 1}")),
                sheet_path,
                index == active_index,
            )
        )

    if not result:
        raise ValueError("Nie znaleziono relacji do arkuszy skoroszytu.")
    return result

def _column_index(reference: str) -> int:
    match = re.match(r"^([A-Za-z]+)", reference or "")
    if not match:
        return 0

    result = 0
    for char in match.group(1).upper():
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result


def _date_style_indexes(archive: zipfile.ZipFile) -> set[int]:
    if "xl/styles.xml" not in archive.namelist():
        return set()

    root = _xml_root(archive, "xl/styles.xml")
    custom_formats: dict[int, str] = {}
    num_fmts = root.find(f"{{{MAIN_NS}}}numFmts")
    if num_fmts is not None:
        for fmt in num_fmts.findall(f"{{{MAIN_NS}}}numFmt"):
            try:
                fmt_id = int(fmt.attrib.get("numFmtId", ""))
            except ValueError:
                continue
            custom_formats[fmt_id] = fmt.attrib.get("formatCode", "")

    built_in_date_ids = {
        14, 15, 16, 17, 18, 19, 20, 21, 22,
        27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
        45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58,
    }

    def looks_like_date(fmt: str) -> bool:
        cleaned = re.sub(r'"[^"]*"', "", fmt.casefold())
        cleaned = re.sub(r"\\.", "", cleaned)
        cleaned = re.sub(r"\[[^\]]*\]", "", cleaned)
        return bool(re.search(r"(^|[^a-z])[dmyhs]+([^a-z]|$)", cleaned))

    result: set[int] = set()
    cell_xfs = root.find(f"{{{MAIN_NS}}}cellXfs")
    if cell_xfs is None:
        return result

    for index, xf in enumerate(cell_xfs.findall(f"{{{MAIN_NS}}}xf")):
        try:
            num_fmt_id = int(xf.attrib.get("numFmtId", "0"))
        except ValueError:
            continue
        if (
            num_fmt_id in built_in_date_ids
            or looks_like_date(custom_formats.get(num_fmt_id, ""))
        ):
            result.add(index)
    return result


def _excel_serial_to_value(value: float) -> object:
    converted = datetime(1899, 12, 30) + timedelta(days=value)
    if converted.time().isoformat() == "00:00:00":
        return converted.date()
    return converted


def _cell_value(
    cell: ET.Element,
    shared_strings: list[str],
    date_styles: set[int],
) -> object:
    cell_type = cell.attrib.get("t", "")
    style_index = 0
    try:
        style_index = int(cell.attrib.get("s", "0"))
    except ValueError:
        pass

    if cell_type == "inlineStr":
        inline = cell.find(f"{{{MAIN_NS}}}is")
        if inline is None:
            return ""
        return "".join(
            node.text or ""
            for node in inline.iter(f"{{{MAIN_NS}}}t")
        )

    value_node = cell.find(f"{{{MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return ""

    raw = value_node.text

    if cell_type == "s":
        try:
            index = int(raw)
            return shared_strings[index] if 0 <= index < len(shared_strings) else ""
        except ValueError:
            return ""
    if cell_type in {"str", "e", "d"}:
        return raw
    if cell_type == "b":
        return raw == "1"

    try:
        number = float(raw)
    except ValueError:
        return raw

    if style_index in date_styles:
        return _excel_serial_to_value(number)
    if number.is_integer():
        return int(number)
    return number


def _read_sheet_rows(
    archive: zipfile.ZipFile,
    sheet_path: str,
    shared_strings: list[str],
    date_styles: set[int],
) -> list[tuple[object, ...]]:
    root = _xml_root(archive, sheet_path)
    sheet_data = root.find(f"{{{MAIN_NS}}}sheetData")
    if sheet_data is None:
        return []

    result: list[tuple[object, ...]] = []
    for row in sheet_data.findall(f"{{{MAIN_NS}}}row"):
        values: dict[int, object] = {}
        max_column = 0
        for cell in row.findall(f"{{{MAIN_NS}}}c"):
            column = _column_index(cell.attrib.get("r", ""))
            if column <= 0:
                continue
            values[column] = _cell_value(cell, shared_strings, date_styles)
            max_column = max(max_column, column)

        if max_column == 0:
            result.append(tuple())
        else:
            result.append(
                tuple(values.get(column, "") for column in range(1, max_column + 1))
            )
    return result


def _header_candidate(
    rows: list[tuple[object, ...]],
    max_scan_rows: int = 120,
) -> tuple[int, dict[str, int], int]:
    best_row = 0
    best_mapping: dict[str, int] = {}
    best_score = 0
    normalized_aliases = {
        field: {_normalize_header(alias) for alias in aliases}
        for field, aliases in HEADER_ALIASES.items()
    }

    for row_no, row in enumerate(rows[:max_scan_rows], start=1):
        mapping: dict[str, int] = {}
        for column_index, value in enumerate(row, start=1):
            normalized = _normalize_header(value)
            if not normalized:
                continue
            for field, aliases in normalized_aliases.items():
                if normalized in aliases and field not in mapping:
                    mapping[field] = column_index

        score = len(mapping)
        if "quantity" in mapping:
            score += 1
        if "symbol" in mapping or "product" in mapping:
            score += 2
        if "order_code" in mapping:
            score += 1

        if score > best_score:
            best_score = score
            best_row = row_no
            best_mapping = mapping

    return best_row, best_mapping, best_score


def _sheet_rows(
    snapshot_path: Path,
) -> tuple[str, list[tuple[object, ...]], int, dict[str, int]]:
    try:
        archive = zipfile.ZipFile(snapshot_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(
            "Wybrany plik nie jest prawidłowym plikiem Excel .xlsx/.xlsm."
        ) from exc

    with archive:
        shared_strings = _read_shared_strings(archive)
        date_styles = _date_style_indexes(archive)
        workbook_sheets = _workbook_sheets(archive)

        candidates = []
        for sheet_name, sheet_path, is_active in workbook_sheets:
            rows = _read_sheet_rows(
                archive,
                sheet_path,
                shared_strings,
                date_styles,
            )
            header_row, mapping, semantic_score = _header_candidate(rows)
            name_bonus = 2 if "plan" in _normalize_header(sheet_name) else 0
            candidates.append(
                (
                    semantic_score + name_bonus,
                    semantic_score,
                    is_active,
                    sheet_name,
                    rows,
                    header_row,
                    mapping,
                )
            )

        candidates.sort(key=lambda item: (item[0], item[2]), reverse=True)
        (
            _rank_score,
            semantic_score,
            _active,
            sheet_name,
            rows,
            header_row,
            mapping,
        ) = candidates[0]

        if semantic_score < 3 or not (
            "symbol" in mapping or "product" in mapping
        ):
            detected = ", ".join(sorted(mapping)) or "brak"
            sheet_names = ", ".join(
                name for name, _path, _active in workbook_sheets
            )
            raise ValueError(
                "Nie rozpoznano nagłówków planu. "
                f"Arkusze: {sheet_names}. "
                f"Najlepszy kandydat: {sheet_name}, wiersz {header_row or '—'}, "
                f"rozpoznane pola: {detected}. "
                "Obsługiwane są m.in. Nr zlec., Produkt, Ilość:, "
                "Termin realizacji:/Data wysyłki oraz RAL."
            )

        return sheet_name, rows, header_row, mapping


def _cell(row: tuple[object, ...], column_index: int | None) -> object:
    if not column_index or column_index < 1 or column_index > len(row):
        return None
    return row[column_index - 1]


def _text(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value).strip()


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _split_product(product_text: str) -> tuple[str, str]:
    product_text = product_text.strip()
    if not product_text:
        return "", ""
    parts = product_text.split(maxsplit=1)
    first = parts[0]
    if re.match(r"^[A-Za-z0-9]+(?:[.\-_/][A-Za-z0-9]+)+$", first):
        return first, parts[1].strip() if len(parts) > 1 else ""
    return "", product_text


def inspect_plan_snapshot(
    snapshot_path: Path,
    *,
    max_rows: int = 40,
) -> list[dict]:
    """Zwraca podgląd arkuszy lokalnego snapshotu do ręcznego mapowania kolumn."""
    snapshot_path = Path(snapshot_path)
    try:
        archive = zipfile.ZipFile(snapshot_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(
            "Wybrany plik nie jest prawidłowym plikiem Excel .xlsx/.xlsm."
        ) from exc

    result: list[dict] = []
    with archive:
        shared_strings = _read_shared_strings(archive)
        date_styles = _date_style_indexes(archive)
        workbook_sheets = _workbook_sheets(archive)

        for sheet_name, sheet_path, is_active in workbook_sheets:
            rows = _read_sheet_rows(
                archive,
                sheet_path,
                shared_strings,
                date_styles,
            )
            header_row, mapping, score = _header_candidate(rows)
            result.append(
                {
                    "sheet_name": sheet_name,
                    "is_active": is_active,
                    "header_row": header_row or 1,
                    "detected_mapping": dict(mapping),
                    "score": score,
                    "rows": [list(row) for row in rows[:max_rows]],
                }
            )
    return result


def _sheet_rows_manual(
    snapshot_path: Path,
    sheet_name: str,
) -> list[tuple[object, ...]]:
    snapshot_path = Path(snapshot_path)
    try:
        archive = zipfile.ZipFile(snapshot_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(
            "Wybrany plik nie jest prawidłowym plikiem Excel .xlsx/.xlsm."
        ) from exc

    with archive:
        shared_strings = _read_shared_strings(archive)
        date_styles = _date_style_indexes(archive)
        workbook_sheets = _workbook_sheets(archive)
        for candidate_name, sheet_path, _is_active in workbook_sheets:
            if candidate_name == sheet_name:
                return _read_sheet_rows(
                    archive,
                    sheet_path,
                    shared_strings,
                    date_styles,
                )
    raise ValueError(f"Nie znaleziono arkusza {sheet_name} w snapshotcie.")


def read_plan_snapshot(
    snapshot_path: Path,
    *,
    sheet_name: str | None = None,
    header_row: int | None = None,
    mapping: dict[str, int] | None = None,
) -> ParsedPlan:
    """Parsuje wyłącznie lokalny snapshot; nigdy plik źródłowy.

    Gdy sheet_name/header_row/mapping są podane, używa ręcznego mapowania kolumn.
    """
    snapshot_path = Path(snapshot_path)

    manual = mapping is not None
    if manual:
        if not sheet_name:
            raise ValueError("Przy ręcznym mapowaniu trzeba wskazać arkusz.")
        if header_row is None or int(header_row) < 1:
            raise ValueError("Przy ręcznym mapowaniu trzeba wskazać wiersz nagłówków.")

        clean_mapping = {
            str(field): int(column)
            for field, column in dict(mapping or {}).items()
            if int(column or 0) > 0
        }
        if not (
            clean_mapping.get("product")
            or clean_mapping.get("symbol")
            or clean_mapping.get("name")
        ):
            raise ValueError(
                "Ręczne mapowanie musi wskazywać kolumnę Produkt, Symbol albo Nazwa."
            )

        worksheet_rows = _sheet_rows_manual(snapshot_path, sheet_name)
        header_row = int(header_row)
        mapping = clean_mapping
    else:
        sheet_name, worksheet_rows, header_row, mapping = _sheet_rows(snapshot_path)

    result: list[dict] = []
    last_order_code = ""
    occurrence: dict[str, int] = {}

    for row_no, row in enumerate(
        worksheet_rows[int(header_row):],
        start=int(header_row) + 1,
    ):
        order_code = _text(_cell(row, mapping.get("order_code")))
        if order_code:
            last_order_code = order_code
        else:
            order_code = last_order_code

        symbol = _text(_cell(row, mapping.get("symbol")))
        name = _text(_cell(row, mapping.get("name")))
        product_text = _text(_cell(row, mapping.get("product")))
        if product_text and not symbol:
            inferred_symbol, inferred_name = _split_product(product_text)
            symbol = inferred_symbol
            if not name:
                name = inferred_name
        elif product_text and not name:
            name = product_text

        quantity = _number(_cell(row, mapping.get("quantity")))
        shipping = _text(_cell(row, mapping.get("shipping")))
        ral = _text(_cell(row, mapping.get("ral")))

        if not any((order_code, symbol, name, quantity is not None, shipping, ral)):
            continue
        if not symbol and not name:
            continue

        base_key = "|".join(
            part.casefold().strip()
            for part in (order_code, symbol, name)
        )
        occurrence[base_key] = occurrence.get(base_key, 0) + 1
        row_key = f"{base_key}#{occurrence[base_key]}"

        result.append(
            {
                "row_key": row_key,
                "row_no": row_no,
                "order_code": order_code,
                "symbol": symbol,
                "name": name,
                "quantity": quantity,
                "shipping": shipping,
                "ral": ral,
            }
        )

    if manual and not result:
        raise ValueError(
            "Ręczne mapowanie nie zwróciło żadnych pozycji planu. "
            "Sprawdź arkusz, wiersz nagłówków i przypisane kolumny."
        )

    return ParsedPlan(
        sheet_name=str(sheet_name),
        header_row=int(header_row),
        rows=result,
    )

def compare_plan_rows(previous_rows: Iterable[dict], current_rows: Iterable[dict]) -> dict:
    previous = {str(row["row_key"]): dict(row) for row in previous_rows}
    current = {str(row["row_key"]): dict(row) for row in current_rows}

    added = [current[key] for key in current.keys() - previous.keys()]
    removed = [previous[key] for key in previous.keys() - current.keys()]

    fields = ("order_code", "symbol", "name", "quantity", "shipping", "ral")
    changed: list[dict] = []
    for key in current.keys() & previous.keys():
        before = previous[key]
        after = current[key]
        delta = {
            field: {"before": before.get(field), "after": after.get(field)}
            for field in fields
            if before.get(field) != after.get(field)
        }
        if delta:
            changed.append(
                {
                    "row_key": key,
                    "before": before,
                    "after": after,
                    "changes": delta,
                }
            )

    return {
        "added": sorted(added, key=lambda row: int(row.get("row_no", 0))),
        "removed": sorted(removed, key=lambda row: int(row.get("row_no", 0))),
        "changed": sorted(
            changed,
            key=lambda row: int(row["after"].get("row_no", 0)),
        ),
    }

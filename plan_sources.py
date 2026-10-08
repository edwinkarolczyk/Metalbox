from __future__ import annotations

"""Niezależne źródła firmowego planu. Excel otwierany wyłącznie do wykonania kopii."""
import fnmatch
import json
import os
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from plan_excel import compare_plan_rows, read_plan_snapshot, safe_snapshot


class PlanSources:
    """Podgląd wielu Exceli. Nie modyfikuje oryginałów ani planu zatwierdzonego."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "sources.json"
        self.resolutions_path = self.root / "conflict_resolutions.json"
        self.lock = threading.RLock()
        (self.root / "states").mkdir(exist_ok=True)
        (self.root / "snapshots").mkdir(exist_ok=True)

    @staticmethod
    def _load(path: Path) -> dict:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
        except (ValueError, OSError):
            return {}

    @staticmethod
    def _write(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temp.write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def list_sources(self) -> list[dict]:
        with self.lock:
            raw = self._load(self.config_path).get("sources", [])
            return [dict(s) for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []

    @staticmethod
    def _validate_path(path: str) -> str:
        result = str(path or "").strip().strip('"')
        if not result:
            raise ValueError("Podaj ścieżkę pliku planu Excel.")
        candidate = Path(result).expanduser()
        if candidate.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError("Źródło musi wskazywać plik .xlsx lub .xlsm.")
        return str(candidate.absolute())

    @staticmethod
    def _source_mode(mode: str) -> str:
        value = str(mode or "file").strip().lower()
        if value not in {"file", "folder"}:
            raise ValueError("Typ źródła musi być plikiem lub folderem.")
        return value

    @staticmethod
    def _exclude_patterns(value: str) -> str:
        parts = [part.strip() for part in str(value or "~$*").split(";") if part.strip()]
        if len(parts) > 30 or any(len(part) > 100 for part in parts):
            raise ValueError("Zbyt wiele wzorców wykluczenia.")
        if not any(part.casefold() == "~$*" for part in parts):
            parts.insert(0, "~$*")
        return ";".join(parts)

    def folder_candidates(self, path: str, *, exclude_patterns: str = "~$*") -> list[str]:
        folder = Path(str(path)).expanduser()
        if not folder.is_dir():
            raise ValueError(f"Nie znaleziono folderu źródłowego: {folder}")
        excluded = self._exclude_patterns(exclude_patterns).split(";")
        candidates: list[str] = []
        for entry in folder.iterdir():
            if not entry.is_file() or entry.suffix.casefold() not in {".xlsx", ".xlsm"}:
                continue
            name = entry.name
            if name.startswith(".") or any(
                fnmatch.fnmatchcase(name.casefold(), pattern.casefold())
                for pattern in excluded
            ):
                continue
            candidates.append(name)
        return sorted(candidates, key=str.casefold)

    def _resolved_file(self, source: dict) -> Path:
        mode = self._source_mode(source.get("mode", "file"))
        root = Path(source["path"])
        if mode == "file":
            return root
        candidates = self.folder_candidates(
            str(root), exclude_patterns=source.get("exclude_patterns", "~$*")
        )
        chosen = str(source.get("selected_file") or "").strip()
        if chosen:
            if chosen not in candidates or Path(chosen).name != chosen:
                raise ValueError(
                    "Wybrany Excel nie znajduje się w folderze lub jest wykluczony. "
                    "Wskaż go ponownie; ostatni poprawny plan pozostaje zachowany."
                )
            return root / chosen
        if len(candidates) == 1:
            return root / candidates[0]
        if not candidates:
            raise ValueError("Folder nie zawiera żadnego dozwolonego pliku Excel.")
        raise ValueError(
            f"Folder zawiera {len(candidates)} plików Excel. "
            "Wybierz konkretny aktywny plik; Metalbox nie zgaduje, która kopia jest aktualna."
        )

    @staticmethod
    def _source_identity(source: dict) -> tuple[str, str, str]:
        return (
            str(source.get("mode") or "file").casefold(),
            os.path.normcase(str(source.get("path") or "")).casefold(),
            str(source.get("selected_file") or "").casefold()
            if source.get("mode") == "folder" else "",
        )

    @staticmethod
    def _config_fingerprint(source: dict) -> str:
        mapping = source.get("column_mapping") or {}
        config = {
            "mode": source.get("mode", "file"),
            "path": source.get("path"),
            "selected_file": source.get("selected_file", ""),
            "exclude_patterns": source.get("exclude_patterns", "~$*"),
            "column_mapping": mapping,
        }
        return json.dumps(config, ensure_ascii=False, sort_keys=True)

    def add_source(
        self, *, name: str, path: str, interval_seconds: int = 120,
        enabled: bool = True, mode: str = "file",
        selected_file: str = "", exclude_patterns: str = "~$*",
    ) -> dict:
        mode = self._source_mode(mode)
        raw_path = str(path or "").strip().strip('"')
        if not raw_path:
            raise ValueError("Podaj ścieżkę pliku lub folderu planu.")
        path = (
            str(Path(raw_path).expanduser().absolute()) if mode == "folder"
            else self._validate_path(raw_path)
        )
        exclude_patterns = self._exclude_patterns(exclude_patterns)
        selected_file = str(selected_file or "").strip()
        if selected_file and (Path(selected_file).name != selected_file or Path(selected_file).suffix.casefold() not in {".xlsx", ".xlsm"}):
            raise ValueError("Wybierz samą nazwę pliku Excel z folderu.")
        name = str(name or "").strip()
        if not name:
            raise ValueError("Podaj nazwę źródła.")
        if len(name) > 100:
            raise ValueError("Nazwa źródła jest zbyt długa.")
        interval_seconds = int(interval_seconds)
        if not 30 <= interval_seconds <= 86400:
            raise ValueError("Interwał musi mieścić się w zakresie 30–86400 sekund.")
        with self.lock:
            sources = self.list_sources()
            if any(x.get("name", "").casefold() == name.casefold() for x in sources):
                raise ValueError("Źródło o tej nazwie już istnieje.")
            requested = {
                "mode": mode, "path": path, "selected_file": selected_file,
            }
            if any(
                self._source_identity(x) == self._source_identity(requested)
                for x in sources
            ):
                raise ValueError("Ten sam plik jest już monitorowany.")
            source = dict(
                id=uuid.uuid4().hex, name=name, path=path,
                interval_seconds=interval_seconds, enabled=bool(enabled),
                mode=mode, selected_file=selected_file,
                exclude_patterns=exclude_patterns, column_mapping={},
            )
            sources.append(source)
            self._write(self.config_path, {"schema": 1, "sources": sources})
            return source

    def update_source(
        self, source_id: str, *, name: str | None = None,
        path: str | None = None, interval_seconds: int | None = None,
        enabled: bool | None = None, mode: str | None = None,
        selected_file: str | None = None, exclude_patterns: str | None = None,
        column_mapping: dict | None = None,
    ) -> dict:
        with self.lock:
            sources = self.list_sources()
            found = next((item for item in sources if item["id"] == source_id), None)
            if found is None:
                raise ValueError("Nie znaleziono źródła Excel.")
            candidate = dict(found)
            if name is not None:
                candidate["name"] = str(name).strip()
                if not candidate["name"] or len(candidate["name"]) > 100:
                    raise ValueError("Nieprawidłowa nazwa źródła.")
            if mode is not None:
                candidate["mode"] = self._source_mode(mode)
            if path is not None:
                candidate["path"] = (
                    str(Path(path).expanduser().absolute()) if candidate.get("mode") == "folder"
                    else self._validate_path(path)
                )
            if selected_file is not None:
                selected_file = str(selected_file).strip()
                if selected_file and (Path(selected_file).name != selected_file or Path(selected_file).suffix.casefold() not in {".xlsx", ".xlsm"}):
                    raise ValueError("Nieprawidłowa nazwa pliku w folderze.")
                candidate["selected_file"] = selected_file
            if exclude_patterns is not None:
                candidate["exclude_patterns"] = self._exclude_patterns(exclude_patterns)
            if column_mapping is not None:
                if not isinstance(column_mapping, dict) or set(column_mapping) != {"sheet_name", "header_row", "mapping"}:
                    raise ValueError("Nieprawidłowe mapowanie kolumn źródła.")
                if not str(column_mapping["sheet_name"]).strip() or int(column_mapping["header_row"]) < 1:
                    raise ValueError("Mapowanie wymaga arkusza i numeru wiersza nagłówków.")
                candidate["column_mapping"] = {
                    "sheet_name": str(column_mapping["sheet_name"]),
                    "header_row": int(column_mapping["header_row"]),
                    "mapping": {str(k): int(v) for k, v in dict(column_mapping["mapping"]).items()},
                }
            if interval_seconds is not None:
                interval_seconds = int(interval_seconds)
                if not 30 <= interval_seconds <= 86400:
                    raise ValueError("Interwał musi mieścić się w zakresie 30–86400 sekund.")
                candidate["interval_seconds"] = interval_seconds
            if enabled is not None:
                candidate["enabled"] = bool(enabled)
            if any(x["id"] != source_id and (
                x["name"].casefold() == candidate["name"].casefold() or
                self._source_identity(x) == self._source_identity(candidate)
            ) for x in sources):
                raise ValueError("Nazwa albo ścieżka jest już zajęta przez inne źródło.")
            changed_path = self._config_fingerprint(candidate) != self._config_fingerprint(found)
            sources = [candidate if x["id"] == source_id else x for x in sources]
            self._write(self.config_path, {"schema": 1, "sources": sources})
            if changed_path:
                self._write(self._state_path(source_id), {})
            return candidate

    def mapping_snapshot(self, source_id: str) -> tuple[Path, str]:
        """Kopia do ręcznego mapowania, źródłowy uchwyt jest już zamknięty."""
        source = next(
            (s for s in self.list_sources() if s["id"] == source_id), None,
        )
        if source is None:
            raise ValueError("Nie znaleziono źródła Excel.")
        target = self._resolved_file(source)
        result = safe_snapshot(target, self.root / "mapping_snapshots" / source_id)
        return result.path, target.name

    def _state_path(self, source_id: str) -> Path:
        if not source_id or not all(c in "0123456789abcdef" for c in source_id):
            raise ValueError("Nieprawidłowy identyfikator źródła.")
        return self.root / "states" / (source_id + ".json")

    def get_state(self, source_id: str) -> dict:
        with self.lock:
            return self._load(self._state_path(source_id))

    def scan(self, source_id: str) -> dict:
        """Wykonuje tylko PODGLĄD zmian. Nie zatwierdza i nie publikuje planu."""
        with self.lock:
            source = next((s for s in self.list_sources() if s["id"] == source_id), None)
        if source is None:
            raise ValueError("Nie znaleziono źródła Excel.")
        if not source["enabled"]:
            return {"source_id": source_id, "status": "WYŁĄCZONE"}

        previous = self.get_state(source_id)
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            src = self._resolved_file(source)
            before = src.stat()
            fingerprint = self._config_fingerprint(source)
            signature = f"{src}:{before.st_size}:{before.st_mtime_ns}:{fingerprint}"
            if (previous.get("signature") == signature and
                    previous.get("status") in {"BEZ ZMIAN", "NOWE ZMIANY", "GOTOWE"}):
                # Oczekująca zmiana nie znika przy następnym odczycie bez zmian.
                state = {**previous, "checked_at": checked_at}
                self._write(self._state_path(source_id), state)
                return {**state, "source_id": source_id}
            snapshot = safe_snapshot(src, self.root / "snapshots" / source_id)
            after = src.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                snapshot.path.unlink(missing_ok=True)
                raise ValueError("Źródło zmieniło się podczas kopiowania — ponów odczyt.")
            if previous.get("sha256") == snapshot.sha256:
                snapshot.path.unlink(missing_ok=True)
                state = {
                    **previous,
                    "signature": signature, "checked_at": checked_at, "error": "",
                }
                self._write(self._state_path(source_id), state)
                return {**state, "source_id": source_id}

            mapping = source.get("column_mapping") or {}
            parsed = (
                read_plan_snapshot(
                    snapshot.path, sheet_name=str(mapping["sheet_name"]),
                    header_row=int(mapping["header_row"]),
                    mapping=dict(mapping["mapping"]),
                ) if mapping else read_plan_snapshot(snapshot.path)
            )
            old_rows = list(previous.get("rows") or [])
            diff = compare_plan_rows(old_rows, parsed.rows)
            state = {
                "status": "NOWE ZMIANY" if any(diff.values()) else "GOTOWE",
                "source_name": source["name"],
                "source_path": str(src),
                "source_root": source["path"],
                "mapping_used": mapping,
                "source_file": src.name,
                "signature": signature,
                "sha256": snapshot.sha256,
                "snapshot_path": str(snapshot.path),
                "sheet_name": parsed.sheet_name,
                "rows": parsed.rows,
                "row_count": len(parsed.rows),
                "diff": diff,
                "change_counts": {name: len(rows) for name, rows in diff.items()},
                "checked_at": checked_at,
                "updated_at": checked_at,
                "error": "",
            }
            # Nie podmieniamy zaakceptowanego planu. Osobne stany chronią każde źródło.
            self._write(self._state_path(source_id), state)
            return {**state, "source_id": source_id}
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
            # Awaria źródła nie oznacza usunięcia pozycji, a innego źródła nie blokuje.
            state = {
                **previous, "status": "BŁĄD ODCZYTU", "error": str(exc),
                "checked_at": checked_at,
            }
            self._write(self._state_path(source_id), state)
            return {**state, "source_id": source_id}

    def build_combined_preview(self) -> dict:
        """Łączy ostatnie poprawne odczyty dopiero na wyraźne żądanie kierownika.

        Nie zatwierdza, nie nadpisuje zleceń i blokuje nieznane/konfliktowe źródła.
        """
        active = [src for src in self.list_sources() if src.get("enabled")]
        if not active:
            raise ValueError("Włącz przynajmniej jedno źródło Excel.")
        conflicts = self.check_conflicts()
        undecided = [
            item for item in conflicts
            if not item.get("chosen_source_id") and not item.get("keep_all")
        ]
        if undecided:
            raise ValueError(
                f"Źródła zawierają {len(undecided)} nierozstrzygniętych pozycji ZL/produkt. "
                "Wybierz właściwe źródło dla każdego konfliktu lub duplikatu."
            )
        winners = {
            (item["order_code"], item["symbol"]): item["chosen_source_id"]
            for item in conflicts
        }

        rows = []
        versions = []
        for src in active:
            state = self.get_state(src["id"])
            if state.get("status") not in {"NOWE ZMIANY", "BEZ ZMIAN", "GOTOWE"}:
                raise ValueError(
                    f'Źródło {src["name"]} nie ma aktualnego poprawnego odczytu. '
                    "Nie zastępuj go pustym planem."
                )
            if not state.get("rows") or not state.get("sha256"):
                raise ValueError(f'Źródło {src["name"]} nie ma pozycji do scalenia.')
            # Między automatycznym odczytem a ręcznym przygotowaniem planu
            # źródłowy Excel mógł ulec zmianie. W takim przypadku blokuj.
            try:
                resolved = self._resolved_file(src)
                stat = resolved.stat()
            except OSError as exc:
                raise ValueError(
                    f'Plik źródła {src["name"]} jest niedostępny. '
                    "Ostatni poprawny stan zachowano, lecz publikacja jest wstrzymana."
                ) from exc
            signature = f"{resolved}:{stat.st_size}:{stat.st_mtime_ns}:{self._config_fingerprint(src)}"
            if signature != state.get("signature"):
                raise ValueError(
                    f'Źródło {src["name"]} zmieniło się od ostatniego odczytu. '
                    "Najpierw sprawdź je ponownie."
                )
            if not Path(state["snapshot_path"]).is_file():
                raise ValueError(
                    f'Snapshot źródła {src["name"]} nie jest dostępny.'
                )
            versions.append({
                "id": src["id"], "name": src["name"],
                "sha256": state["sha256"], "checked_at": state["checked_at"],
            })
            for row in state["rows"]:
                pair = (
                    str(row.get("order_code") or "").strip().upper(),
                    str(row.get("symbol") or "").strip().upper(),
                )
                chosen = winners.get(pair)
                if chosen and chosen != src["id"]:
                    continue
                entry = dict(row)
                entry["source_name"] = src["name"]
                entry["source_id"] = src["id"]
                entry["source_row_no"] = row.get("row_no")
                entry["row_key"] = f'{src["id"]}|{row["row_key"]}'
                entry["row_no"] = len(rows) + 1
                rows.append(entry)
        return {"rows": rows, "sources": versions, "row_count": len(rows)}

    def acknowledge_accepted_sources(self, versions: list[dict]) -> int:
        """Czyści alert zmian tylko dla wersji naprawdę zaakceptowanych przez kierownika."""
        acknowledged = 0
        with self.lock:
            valid_ids = {source["id"] for source in self.list_sources()}
            for item in versions:
                if not isinstance(item, dict):
                    continue
                source_id = str(item.get("id") or "")
                if source_id not in valid_ids:
                    continue
                state = self.get_state(source_id)
                if not state.get("sha256") or state["sha256"] != item.get("sha256"):
                    continue
                state.update(
                    status="BEZ ZMIAN",
                    diff={"added": [], "changed": [], "removed": []},
                    change_counts={"added": 0, "changed": 0, "removed": 0},
                    accepted_sha256=state["sha256"],
                    accepted_at=datetime.now(timezone.utc).isoformat(),
                )
                self._write(self._state_path(source_id), state)
                acknowledged += 1
        return acknowledged

    def resolve_conflict(
        self, *, order_code: str, symbol: str,
        chosen_source_id: str = "", keep_all: bool = False,
        actor: str = "development-user",
    ) -> dict:
        """Zapamiętuje świadomy wybór źródła z kontrolą wersji obu Exceli."""
        code = str(order_code or "").strip().upper()
        symbol = str(symbol or "").strip().upper()
        item = next(
            (row for row in self.check_conflicts()
             if row["order_code"] == code and row["symbol"] == symbol),
            None,
        )
        if item is None:
            raise ValueError("Brak konfliktu lub duplikatu do rozstrzygnięcia.")
        if not keep_all and chosen_source_id not in item["source_ids"]:
            raise ValueError("Wybrane źródło nie zawiera tej pozycji.")
        if keep_all and chosen_source_id:
            raise ValueError(
                "Wybierz albo jedno źródło, albo pozostaw wszystkie osobne partie."
            )
        signatures = {
            source_id: str(self.get_state(source_id).get("sha256") or "")
            for source_id in item["source_ids"]
        }
        if not all(signatures.values()):
            raise ValueError("Wymagany poprawny snapshot każdego źródła.")
        key = f"{code}|{symbol}"
        with self.lock:
            decisions = self._load(self.resolutions_path)
            decisions[key] = {
                "chosen_source_id": "" if keep_all else chosen_source_id,
                "mode": "keep_all" if keep_all else "choose_source",
                "signatures": signatures,
                "actor": str(actor).strip() or "development-user",
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write(self.resolutions_path, decisions)
        return dict(decisions[key])

    def check_conflicts(self) -> list[dict]:
        """Konflikty między aktywnymi źródłami, wyłącznie informacyjnie."""
        values: dict[tuple[str, str], list[dict]] = {}
        for src in self.list_sources():
            if not src.get("enabled"):
                continue
            state = self.get_state(src["id"])
            for row in state.get("rows", []):
                code = str(row.get("order_code") or "").strip().upper()
                symbol = str(row.get("symbol") or "").strip().upper()
                if not code or not symbol:
                    continue
                values.setdefault((code, symbol), []).append(
                    {"source_id": src["id"], "source": src["name"], "row": row}
                )
        conflicts = []
        decisions = self._load(self.resolutions_path)
        for (code, symbol), matches in values.items():
            if len({m["source_id"] for m in matches}) < 2:
                continue
            signatures = {
                (
                    str(m["row"].get("quantity") or ""),
                    str(m["row"].get("shipping") or ""),
                    str(m["row"].get("ral") or ""),
                    str(m["row"].get("name") or ""),
                ) for m in matches
            }
            decision = decisions.get(f"{code}|{symbol}", {})
            versions = {
                match["source_id"]: str(self.get_state(match["source_id"]).get("sha256") or "")
                for match in matches
            }
            versions_valid = decision.get("signatures") == versions
            chosen = (
                decision.get("chosen_source_id")
                if versions_valid and decision.get("chosen_source_id") in versions
                else None
            )
            keep_all = bool(
                versions_valid and decision.get("mode") == "keep_all"
                and len(versions) >= 2
            )
            conflicts.append({
                "order_code": code, "symbol": symbol,
                "status": (
                    "ODRĘBNE PARTIE" if keep_all
                    else "ROZSTRZYGNIĘTY" if chosen
                    else "DO ROZSTRZYGNIĘCIA" if len(signatures) > 1
                    else "DUPLIKAT"
                ),
                "chosen_source_id": chosen,
                "keep_all": keep_all,
                "source_ids": [m["source_id"] for m in matches],
                "sources": [m["source"] for m in matches],
                "details": [
                    {
                        "source": m["source"],
                        "source_id": m["source_id"],
                        "quantity": m["row"].get("quantity"),
                        "shipping": m["row"].get("shipping"),
                        "ral": m["row"].get("ral"),
                    }
                    for m in matches
                ],
            })
        return conflicts

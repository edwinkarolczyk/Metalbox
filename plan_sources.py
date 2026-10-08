from __future__ import annotations

"""Niezależne źródła firmowego planu. Excel otwierany wyłącznie do wykonania kopii."""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from plan_excel import compare_plan_rows, read_plan_snapshot, safe_snapshot


class PlanSources:
    """Podgląd wielu Exceli. Nie modyfikuje oryginałów ani planu zatwierdzonego."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "sources.json"
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

    def add_source(
        self, *, name: str, path: str, interval_seconds: int = 120,
        enabled: bool = True,
    ) -> dict:
        path = self._validate_path(path)
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
            if any(os.path.normcase(x.get("path", "")) == os.path.normcase(path) for x in sources):
                raise ValueError("Ten sam plik jest już monitorowany.")
            source = dict(
                id=uuid.uuid4().hex, name=name, path=path,
                interval_seconds=interval_seconds, enabled=bool(enabled),
            )
            sources.append(source)
            self._write(self.config_path, {"schema": 1, "sources": sources})
            return source

    def update_source(
        self, source_id: str, *, name: str | None = None,
        path: str | None = None, interval_seconds: int | None = None,
        enabled: bool | None = None,
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
            if path is not None:
                candidate["path"] = self._validate_path(path)
            if interval_seconds is not None:
                interval_seconds = int(interval_seconds)
                if not 30 <= interval_seconds <= 86400:
                    raise ValueError("Interwał musi mieścić się w zakresie 30–86400 sekund.")
                candidate["interval_seconds"] = interval_seconds
            if enabled is not None:
                candidate["enabled"] = bool(enabled)
            if any(x["id"] != source_id and (
                x["name"].casefold() == candidate["name"].casefold() or
                os.path.normcase(x["path"]) == os.path.normcase(candidate["path"])
            ) for x in sources):
                raise ValueError("Nazwa albo ścieżka jest już zajęta przez inne źródło.")
            changed_path = candidate["path"] != found["path"]
            sources = [candidate if x["id"] == source_id else x for x in sources]
            self._write(self.config_path, {"schema": 1, "sources": sources})
            if changed_path:
                self._write(self._state_path(source_id), {})
            return candidate

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
        src = Path(source["path"])
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            before = src.stat()
            signature = f"{before.st_size}:{before.st_mtime_ns}"
            if (previous.get("signature") == signature and
                    previous.get("status") in {"BEZ ZMIAN", "NOWE ZMIANY", "GOTOWE"}):
                state = {**previous, "status": "BEZ ZMIAN", "checked_at": checked_at}
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
                    **previous, "status": "BEZ ZMIAN",
                    "signature": signature, "checked_at": checked_at, "error": "",
                }
                self._write(self._state_path(source_id), state)
                return {**state, "source_id": source_id}

            parsed = read_plan_snapshot(snapshot.path)
            old_rows = list(previous.get("rows") or [])
            diff = compare_plan_rows(old_rows, parsed.rows)
            state = {
                "status": "NOWE ZMIANY" if any(diff.values()) else "GOTOWE",
                "source_name": source["name"],
                "source_path": source["path"],
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
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Awaria źródła nie oznacza usunięcia pozycji, a innego źródła nie blokuje.
            state = {
                **previous, "status": "BŁĄD ODCZYTU", "error": str(exc),
                "checked_at": checked_at,
            }
            self._write(self._state_path(source_id), state)
            return {**state, "source_id": source_id}

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
            conflicts.append({
                "order_code": code, "symbol": symbol,
                "status": "DO ROZSTRZYGNIĘCIA" if len(signatures) > 1 else "DUPLIKAT",
                "sources": [m["source"] for m in matches],
            })
        return conflicts

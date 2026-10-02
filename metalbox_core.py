from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 7
DEFAULT_ROUTE = ("Laser", "Giętarki", "Zgrzewarki", "Malarnia", "Pakownia")


class MetalboxStore:
    """Warstwa danych Development. Ten sam kontrakt będzie później obsługiwał Metalbox Server."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connect() as db:
            current = int(db.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Baza Metalbox ma nowszy schemat ({current}) niż aplikacja ({SCHEMA_VERSION})."
                )

            # Zawsze odtwarzamy brakujące obiekty schematu. To naprawia bazy,
            # w których PRAGMA user_version zdążył się zapisać, ale poprzedni
            # proces został przerwany przed utworzeniem wszystkich tabel/indeksów.
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    client TEXT NOT NULL DEFAULT '',
                    deadline TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL DEFAULT 'NORMALNY',
                    status TEXT NOT NULL DEFAULT 'NOWE',
                    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
                    ready_percent INTEGER NOT NULL DEFAULT 0 CHECK(ready_percent BETWEEN 0 AND 100),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    position_no INTEGER NOT NULL DEFAULT 1,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    quantity INTEGER NOT NULL CHECK(quantity >= 0),
                    UNIQUE(order_id, position_no)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system',
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS operation_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_item_id INTEGER NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
                    department TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    planned_qty INTEGER NOT NULL CHECK(planned_qty >= 0),
                    good_qty INTEGER NOT NULL DEFAULT 0 CHECK(good_qty >= 0),
                    reject_qty INTEGER NOT NULL DEFAULT 0 CHECK(reject_qty >= 0),
                    rework_qty INTEGER NOT NULL DEFAULT 0 CHECK(rework_qty >= 0),
                    scrap_qty INTEGER NOT NULL DEFAULT 0 CHECK(scrap_qty >= 0),
                    status TEXT NOT NULL DEFAULT 'OCZEKUJE',
                    updated_at TEXT NOT NULL,
                    UNIQUE(order_item_id, department)
                );

                CREATE INDEX IF NOT EXISTS idx_order_items_order
                    ON order_items(order_id);

                CREATE INDEX IF NOT EXISTS idx_audit_entity
                    ON audit_events(entity_type, entity_id, occurred_at);

                CREATE INDEX IF NOT EXISTS idx_operation_progress_item
                    ON operation_progress(order_item_id);

                CREATE INDEX IF NOT EXISTS idx_operation_progress_department
                    ON operation_progress(department, status);

                CREATE TABLE IF NOT EXISTS production_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    order_item_id INTEGER REFERENCES order_items(id) ON DELETE CASCADE,
                    department TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'AKTYWNA',
                    started_at TEXT NOT NULL,
                    paused_at TEXT,
                    ended_at TEXT,
                    created_by TEXT NOT NULL DEFAULT 'system',
                    note TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS session_workers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES production_sessions(id) ON DELETE CASCADE,
                    worker_name TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    left_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_order_department
                    ON production_sessions(order_id, department, status);

                CREATE INDEX IF NOT EXISTS idx_session_workers_session
                    ON session_workers(session_id, left_at);

                CREATE TABLE IF NOT EXISTS quality_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    order_item_id INTEGER REFERENCES order_items(id) ON DELETE SET NULL,
                    department TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    reason TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    session_id INTEGER REFERENCES production_sessions(id) ON DELETE SET NULL,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system'
                );

                CREATE INDEX IF NOT EXISTS idx_quality_order
                    ON quality_events(order_id, occurred_at);

                CREATE INDEX IF NOT EXISTS idx_quality_department
                    ON quality_events(department, kind, occurred_at);

                CREATE TABLE IF NOT EXISTS rework_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    order_item_id INTEGER NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
                    source_operation_id INTEGER NOT NULL REFERENCES operation_progress(id) ON DELETE CASCADE,
                    target_operation_id INTEGER NOT NULL REFERENCES operation_progress(id) ON DELETE CASCADE,
                    source_department TEXT NOT NULL,
                    target_department TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    status TEXT NOT NULL DEFAULT 'DO_NAPRAWY',
                    reason TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    session_id INTEGER REFERENCES production_sessions(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system'
                );

                CREATE INDEX IF NOT EXISTS idx_rework_order
                    ON rework_jobs(order_id, status, updated_at);

                CREATE INDEX IF NOT EXISTS idx_rework_target
                    ON rework_jobs(target_department, status, updated_at);
                """
            )

            self._ensure_column(
                db,
                "orders",
                "progress",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                db,
                "orders",
                "ready_percent",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                db,
                "orders",
                "created_at",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                db,
                "orders",
                "updated_at",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                db,
                "operation_progress",
                "scrap_qty",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                db,
                "quality_events",
                "order_item_id",
                "INTEGER REFERENCES order_items(id) ON DELETE SET NULL",
            )
            self._ensure_column(
                db,
                "production_sessions",
                "order_item_id",
                "INTEGER REFERENCES order_items(id) ON DELETE CASCADE",
            )

            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

            integrity = str(db.execute("PRAGMA quick_check").fetchone()[0])
            if integrity.lower() != "ok":
                raise RuntimeError(
                    f"Baza Metalbox nie przeszła kontroli integralności: {integrity}"
                )

    @staticmethod
    def _ensure_column(
        db: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column in columns:
            return
        db.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )

    def is_empty(self) -> bool:
        with self._connect() as db:
            count = int(db.execute("SELECT COUNT(*) FROM orders").fetchone()[0])
            return count == 0

    def seed_development_data(self) -> bool:
        """Wstawia dane demonstracyjne tylko do całkowicie pustej bazy."""
        if not self.is_empty():
            return False

        orders = [
            {
                "code": "ZL-740",
                "client": "Sorta",
                "deadline": "2026-10-18",
                "priority": "WYSOKI",
                "status": "W TRAKCIE",
                "progress": 58,
                "ready_percent": 31,
                "items": [
                    ("1.435.135", "SC600 RP Sorta", 65),
                    ("1.325.68", "SC400 RP Sorta", 120),
                    ("1.380.100", "SC900 RP Sorta", 40),
                    ("1.435.68", "SC500 RP Sorta", 375),
                    ("1.380.68", "SC200 RP Sorta", 1800),
                ],
            },
            {
                "code": "ZL-763",
                "client": "Elimger",
                "deadline": "2026-10-08",
                "priority": "NORMALNY",
                "status": "W TRAKCIE",
                "progress": 79,
                "ready_percent": 71,
                "items": [("1.330.50", "Elimger", 864)],
            },
            {
                "code": "ZL-781",
                "client": "DELKER",
                "deadline": "2026-10-15",
                "priority": "NORMALNY",
                "status": "WSTRZYMANE",
                "progress": 39,
                "ready_percent": 17,
                "items": [("2.510.240", "DELKER", 48)],
            },
            {
                "code": "ZL-785",
                "client": "WIST",
                "deadline": "2026-10-16",
                "priority": "NORMALNY",
                "status": "W TRAKCIE",
                "progress": 82,
                "ready_percent": 64,
                "items": [("1.380.68", "WIST", 50)],
            },
        ]

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            for order in orders:
                cursor = db.execute(
                    """
                    INSERT INTO orders(
                        code, client, deadline, priority, status,
                        progress, ready_percent, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order["code"],
                        order["client"],
                        order["deadline"],
                        order["priority"],
                        order["status"],
                        order["progress"],
                        order["ready_percent"],
                        now,
                        now,
                    ),
                )
                order_id = int(cursor.lastrowid)
                stage_factors_by_order = {
                    "ZL-740": [1.00, 1.00, 0.59, 0.48, 0.31],
                    "ZL-763": [1.00, 1.00, 1.00, 0.80, 0.71],
                    "ZL-781": [1.00, 0.75, 0.45, 0.25, 0.17],
                    "ZL-785": [1.00, 1.00, 0.90, 0.75, 0.64],
                }
                departments = ["Laser", "Giętarki", "Zgrzewarki", "Malarnia", "Pakownia"]
                factors = stage_factors_by_order.get(
                    order["code"],
                    [1.00, 0.80, 0.60, 0.40, 0.20],
                )

                for position_no, (symbol, name, quantity) in enumerate(order["items"], start=1):
                    cursor_item = db.execute(
                        """
                        INSERT INTO order_items(order_id, position_no, symbol, name, quantity)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (order_id, position_no, symbol, name, quantity),
                    )
                    order_item_id = int(cursor_item.lastrowid)

                    for sequence_no, (department, factor) in enumerate(
                        zip(departments, factors),
                        start=1,
                    ):
                        good_qty = min(quantity, max(0, round(quantity * factor)))
                        if good_qty >= quantity and quantity > 0:
                            status = "GOTOWE"
                        elif good_qty > 0:
                            status = "AKTYWNE"
                        else:
                            status = "OCZEKUJE"

                        if order["code"] == "ZL-781" and department == "Zgrzewarki":
                            status = "WSTRZYMANE"

                        db.execute(
                            """
                            INSERT INTO operation_progress(
                                order_item_id,
                                department,
                                sequence_no,
                                planned_qty,
                                good_qty,
                                reject_qty,
                                rework_qty,
                                status,
                                updated_at
                            )
                            VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
                            """,
                            (
                                order_item_id,
                                department,
                                sequence_no,
                                quantity,
                                good_qty,
                                status,
                                now,
                            ),
                        )

                self._audit_in_connection(
                    db,
                    actor="system",
                    action="seed_created",
                    entity_type="order",
                    entity_id=order["code"],
                    payload={"development": True},
                )
        return True

    def ensure_development_progress_seeded(self) -> bool:
        """Uzupełnia postęp etapów dla istniejącej bazy Development po migracji 1 → 2."""
        departments = ["Laser", "Giętarki", "Zgrzewarki", "Malarnia", "Pakownia"]
        stage_factors_by_order = {
            "ZL-740": [1.00, 1.00, 0.59, 0.48, 0.31],
            "ZL-763": [1.00, 1.00, 1.00, 0.80, 0.71],
            "ZL-781": [1.00, 0.75, 0.45, 0.25, 0.17],
            "ZL-785": [1.00, 1.00, 0.90, 0.75, 0.64],
        }
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0

        with self._connect() as db:
            items = db.execute(
                """
                SELECT
                    oi.id,
                    oi.quantity,
                    o.code
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                """
            ).fetchall()

            for item in items:
                factors = stage_factors_by_order.get(
                    str(item["code"]),
                    [1.00, 0.80, 0.60, 0.40, 0.20],
                )
                quantity = int(item["quantity"])

                for sequence_no, (department, factor) in enumerate(
                    zip(departments, factors),
                    start=1,
                ):
                    exists = db.execute(
                        """
                        SELECT 1
                        FROM operation_progress
                        WHERE order_item_id = ? AND department = ?
                        """,
                        (int(item["id"]), department),
                    ).fetchone()
                    if exists is not None:
                        continue

                    good_qty = min(quantity, max(0, round(quantity * factor)))
                    if good_qty >= quantity and quantity > 0:
                        status = "GOTOWE"
                    elif good_qty > 0:
                        status = "AKTYWNE"
                    else:
                        status = "OCZEKUJE"

                    if str(item["code"]) == "ZL-781" and department == "Zgrzewarki":
                        status = "WSTRZYMANE"

                    db.execute(
                        """
                        INSERT INTO operation_progress(
                            order_item_id,
                            department,
                            sequence_no,
                            planned_qty,
                            good_qty,
                            reject_qty,
                            rework_qty,
                            status,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
                        """,
                        (
                            int(item["id"]),
                            department,
                            sequence_no,
                            quantity,
                            good_qty,
                            status,
                            now,
                        ),
                    )
                    inserted += 1

        return inserted > 0

    def get_order_stage_progress(self, code: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT
                    op.department,
                    MIN(op.sequence_no) AS sequence_no,
                    SUM(op.planned_qty) AS planned_qty,
                    SUM(op.good_qty) AS good_qty,
                    SUM(op.reject_qty) AS reject_qty,
                    SUM(op.rework_qty) AS rework_qty,
                    SUM(op.scrap_qty) AS scrap_qty,
                    CASE
                        WHEN SUM(CASE WHEN op.status = 'WSTRZYMANE' THEN 1 ELSE 0 END) > 0
                            THEN 'WSTRZYMANE'
                        WHEN SUM(op.planned_qty) > 0
                             AND SUM(op.good_qty) >= SUM(op.planned_qty)
                            THEN 'GOTOWE'
                        WHEN SUM(op.good_qty) > 0
                            THEN 'AKTYWNE'
                        ELSE 'OCZEKUJE'
                    END AS status
                FROM operation_progress op
                JOIN order_items oi ON oi.id = op.order_item_id
                JOIN orders o ON o.id = oi.order_id
                WHERE o.code = ?
                GROUP BY op.department
                ORDER BY MIN(op.sequence_no)
                """,
                (code,),
            ).fetchall()

        return [dict(row) for row in rows]

    @staticmethod
    def _normalize_order_payload(
        *,
        code: str,
        client: str,
        deadline: str,
        priority: str,
        status: str,
        items: list[dict],
    ) -> dict:
        code = code.strip().upper()
        client = client.strip()
        deadline = deadline.strip()
        priority = priority.strip().upper()
        status = status.strip().upper()

        if not code:
            raise ValueError("Numer ZL jest wymagany.")
        if len(code) > 40:
            raise ValueError("Numer ZL jest za długi.")
        if not client:
            raise ValueError("Klient jest wymagany.")
        if priority not in {"NORMALNY", "WYSOKI"}:
            raise ValueError("Nieprawidłowy priorytet.")
        if status not in {"NOWE", "W TRAKCIE", "WSTRZYMANE", "ZAKOŃCZONE", "ANULOWANE"}:
            raise ValueError("Nieprawidłowy status zlecenia.")

        if deadline:
            try:
                datetime.strptime(deadline, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError("Termin musi mieć format RRRR-MM-DD.") from exc

        cleaned_items: list[dict] = []
        if not items:
            raise ValueError("Zlecenie musi mieć co najmniej jedną pozycję.")

        for index, item in enumerate(items, start=1):
            symbol = str(item.get("symbol", "")).strip()
            name = str(item.get("name", "")).strip()
            try:
                quantity = int(item.get("quantity", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Pozycja {index}: ilość musi być liczbą całkowitą.") from exc

            if not symbol:
                raise ValueError(f"Pozycja {index}: symbol jest wymagany.")
            if not name:
                raise ValueError(f"Pozycja {index}: nazwa produktu jest wymagana.")
            if quantity <= 0:
                raise ValueError(f"Pozycja {index}: ilość musi być większa od zera.")

            cleaned_items.append(
                {
                    "position_no": index,
                    "symbol": symbol,
                    "name": name,
                    "quantity": quantity,
                }
            )

        return {
            "code": code,
            "client": client,
            "deadline": deadline,
            "priority": priority,
            "status": status,
            "items": cleaned_items,
        }

    @staticmethod
    def _insert_default_route(
        db: sqlite3.Connection,
        *,
        order_item_id: int,
        quantity: int,
        now: str,
    ) -> None:
        for sequence_no, department in enumerate(DEFAULT_ROUTE, start=1):
            db.execute(
                """
                INSERT INTO operation_progress(
                    order_item_id,
                    department,
                    sequence_no,
                    planned_qty,
                    good_qty,
                    reject_qty,
                    rework_qty,
                    status,
                    updated_at
                )
                VALUES (?, ?, ?, ?, 0, 0, 0, 'OCZEKUJE', ?)
                """,
                (
                    order_item_id,
                    department,
                    sequence_no,
                    quantity,
                    now,
                ),
            )

    def create_order(
        self,
        *,
        code: str,
        client: str,
        deadline: str,
        priority: str,
        status: str,
        items: list[dict],
        actor: str = "development-user",
    ) -> dict:
        payload = self._normalize_order_payload(
            code=code,
            client=client,
            deadline=deadline,
            priority=priority,
            status=status,
            items=items,
        )
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as db:
            exists = db.execute(
                "SELECT 1 FROM orders WHERE code = ?",
                (payload["code"],),
            ).fetchone()
            if exists is not None:
                raise ValueError(f"Zlecenie {payload['code']} już istnieje.")

            cursor = db.execute(
                """
                INSERT INTO orders(
                    code, client, deadline, priority, status,
                    progress, ready_percent, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (
                    payload["code"],
                    payload["client"],
                    payload["deadline"],
                    payload["priority"],
                    payload["status"],
                    now,
                    now,
                ),
            )
            order_id = int(cursor.lastrowid)

            for item in payload["items"]:
                item_cursor = db.execute(
                    """
                    INSERT INTO order_items(
                        order_id, position_no, symbol, name, quantity
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        item["position_no"],
                        item["symbol"],
                        item["name"],
                        item["quantity"],
                    ),
                )
                self._insert_default_route(
                    db,
                    order_item_id=int(item_cursor.lastrowid),
                    quantity=int(item["quantity"]),
                    now=now,
                )

            self._audit_in_connection(
                db,
                actor=actor,
                action="order_created",
                entity_type="order",
                entity_id=payload["code"],
                payload={
                    "client": payload["client"],
                    "deadline": payload["deadline"],
                    "priority": payload["priority"],
                    "status": payload["status"],
                    "items": payload["items"],
                },
            )

        created = self.get_order(payload["code"])
        if created is None:
            raise RuntimeError("Zlecenie zostało zapisane, ale nie można go ponownie odczytać.")
        return created

    def order_has_production_activity(self, code: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT 1
                FROM operation_progress op
                JOIN order_items oi ON oi.id = op.order_item_id
                JOIN orders o ON o.id = oi.order_id
                WHERE o.code = ?
                  AND (
                      op.good_qty > 0
                      OR op.reject_qty > 0
                      OR op.rework_qty > 0
                      OR op.status IN ('AKTYWNE', 'WSTRZYMANE', 'GOTOWE')
                  )
                LIMIT 1
                """,
                (code,),
            ).fetchone()
        return row is not None

    def update_order(
        self,
        original_code: str,
        *,
        code: str,
        client: str,
        deadline: str,
        priority: str,
        status: str,
        items: list[dict],
        actor: str = "development-user",
    ) -> dict:
        payload = self._normalize_order_payload(
            code=code,
            client=client,
            deadline=deadline,
            priority=priority,
            status=status,
            items=items,
        )
        original_code = original_code.strip().upper()
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as db:
            order = db.execute(
                "SELECT id FROM orders WHERE code = ?",
                (original_code,),
            ).fetchone()
            if order is None:
                raise ValueError(f"Nie znaleziono zlecenia {original_code}.")
            order_id = int(order["id"])

            if payload["code"] != original_code:
                collision = db.execute(
                    "SELECT 1 FROM orders WHERE code = ?",
                    (payload["code"],),
                ).fetchone()
                if collision is not None:
                    raise ValueError(f"Zlecenie {payload['code']} już istnieje.")

            activity = db.execute(
                """
                SELECT 1
                FROM operation_progress op
                JOIN order_items oi ON oi.id = op.order_item_id
                WHERE oi.order_id = ?
                  AND (
                      op.good_qty > 0
                      OR op.reject_qty > 0
                      OR op.rework_qty > 0
                      OR op.status IN ('AKTYWNE', 'WSTRZYMANE', 'GOTOWE')
                  )
                LIMIT 1
                """,
                (order_id,),
            ).fetchone() is not None

            existing_items = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT position_no, symbol, name, quantity
                    FROM order_items
                    WHERE order_id = ?
                    ORDER BY position_no
                    """,
                    (order_id,),
                ).fetchall()
            ]

            structural_change = existing_items != payload["items"]
            if activity and structural_change:
                raise ValueError(
                    "Nie można zmieniać pozycji ani ilości ZL po rozpoczęciu produkcji. "
                    "Możesz nadal zmienić klienta, termin, priorytet lub status."
                )

            db.execute(
                """
                UPDATE orders
                SET code = ?, client = ?, deadline = ?, priority = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["code"],
                    payload["client"],
                    payload["deadline"],
                    payload["priority"],
                    payload["status"],
                    now,
                    order_id,
                ),
            )

            if structural_change:
                db.execute(
                    "DELETE FROM order_items WHERE order_id = ?",
                    (order_id,),
                )
                for item in payload["items"]:
                    item_cursor = db.execute(
                        """
                        INSERT INTO order_items(
                            order_id, position_no, symbol, name, quantity
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            order_id,
                            item["position_no"],
                            item["symbol"],
                            item["name"],
                            item["quantity"],
                        ),
                    )
                    self._insert_default_route(
                        db,
                        order_item_id=int(item_cursor.lastrowid),
                        quantity=int(item["quantity"]),
                        now=now,
                    )

            self._audit_in_connection(
                db,
                actor=actor,
                action="order_updated",
                entity_type="order",
                entity_id=payload["code"],
                payload={
                    "previous_code": original_code,
                    "client": payload["client"],
                    "deadline": payload["deadline"],
                    "priority": payload["priority"],
                    "status": payload["status"],
                    "structural_change": structural_change,
                    "items": payload["items"],
                },
            )

        updated = self.get_order(payload["code"])
        if updated is None:
            raise RuntimeError("Zlecenie zostało zmienione, ale nie można go ponownie odczytać.")
        return updated

    def list_orders(
        self,
        search: str = "",
        filter_key: str = "Wszystkie",
    ) -> list[dict]:
        search = search.strip()
        where: list[str] = []
        params: list[object] = []

        if search:
            token = f"%{search}%"
            where.append(
                """
                (
                    o.code LIKE ? COLLATE NOCASE
                    OR o.client LIKE ? COLLATE NOCASE
                    OR EXISTS (
                        SELECT 1
                        FROM order_items oi
                        WHERE oi.order_id = o.id
                          AND (
                              oi.symbol LIKE ? COLLATE NOCASE
                              OR oi.name LIKE ? COLLATE NOCASE
                          )
                    )
                )
                """
            )
            params.extend([token, token, token, token])

        if filter_key == "Aktywne":
            where.append("o.status NOT IN ('ZAKOŃCZONE', 'ANULOWANE', 'WSTRZYMANE')")
        elif filter_key == "Opóźnione":
            where.append(
                "o.deadline <> '' AND o.deadline < date('now') "
                "AND o.status NOT IN ('ZAKOŃCZONE', 'ANULOWANE')"
            )
        elif filter_key == "Wstrzymane":
            where.append("o.status = 'WSTRZYMANE'")
        elif filter_key == "Zakończone":
            where.append("o.status = 'ZAKOŃCZONE'")

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT
                    o.code,
                    o.client,
                    o.deadline,
                    o.priority,
                    o.status,
                    o.progress,
                    o.ready_percent
                FROM orders o
                {where_sql}
                ORDER BY o.deadline ASC, o.code ASC
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]

    def get_order(self, code: str) -> dict | None:
        with self._connect() as db:
            order = db.execute(
                """
                SELECT id, code, client, deadline, priority, status, progress, ready_percent
                FROM orders
                WHERE code = ?
                """,
                (code,),
            ).fetchone()
            if order is None:
                return None

            items = db.execute(
                """
                SELECT id, position_no, symbol, name, quantity
                FROM order_items
                WHERE order_id = ?
                ORDER BY position_no ASC
                """,
                (int(order["id"]),),
            ).fetchall()

        result = dict(order)
        result["items"] = [dict(row) for row in items]
        return result

    def list_department_queue(self, department: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT
                    o.code,
                    o.client,
                    oi.id AS order_item_id,
                    oi.position_no,
                    oi.symbol,
                    oi.name,
                    oi.quantity AS order_item_quantity,
                    op.planned_qty,
                    op.good_qty,
                    op.reject_qty,
                    op.rework_qty,
                    op.scrap_qty,
                    op.status,
                    o.deadline,
                    o.priority
                FROM operation_progress op
                JOIN order_items oi ON oi.id = op.order_item_id
                JOIN orders o ON o.id = oi.order_id
                WHERE op.department = ?
                  AND o.status NOT IN ('ANULOWANE')
                ORDER BY
                    CASE
                        WHEN o.priority = 'WYSOKI' THEN 0
                        ELSE 1
                    END,
                    o.deadline ASC,
                    o.code ASC,
                    oi.position_no ASC
                """,
                (department,),
            ).fetchall()

        return [dict(row) for row in rows]


    def department_summary(self, department: str) -> dict:
        queue = self.list_department_queue(department)
        return {
            "active": sum(1 for row in queue if row["status"] == "AKTYWNE"),
            "waiting": sum(1 for row in queue if row["status"] == "OCZEKUJE"),
            "paused": sum(1 for row in queue if row["status"] == "WSTRZYMANE"),
            "done": sum(1 for row in queue if row["status"] == "GOTOWE"),
            "remaining_qty": sum(
                max(0, int(row["planned_qty"]) - int(row["good_qty"]))
                for row in queue
            ),
        }

    def get_department_session(
        self,
        code: str,
        department: str,
        order_item_id: int | None = None,
    ) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT
                    s.id,
                    s.order_item_id,
                    s.status,
                    s.started_at,
                    s.paused_at,
                    s.ended_at,
                    s.created_by,
                    s.note,
                    oi.position_no,
                    oi.symbol,
                    oi.name
                FROM production_sessions s
                JOIN orders o ON o.id = s.order_id
                LEFT JOIN order_items oi ON oi.id = s.order_item_id
                WHERE o.code = ?
                  AND s.department = ?
                  AND (? IS NULL OR s.order_item_id = ?)
                  AND s.status IN ('AKTYWNA', 'WSTRZYMANA')
                ORDER BY s.id DESC
                LIMIT 1
                """,
                (code, department, order_item_id, order_item_id),
            ).fetchone()
            if row is None:
                return None

            workers = db.execute(
                """
                SELECT worker_name, joined_at, left_at
                FROM session_workers
                WHERE session_id = ?
                ORDER BY id
                """,
                (int(row["id"]),),
            ).fetchall()

        result = dict(row)
        result["workers"] = [dict(worker) for worker in workers]
        return result


    def start_production_session(
        self,
        code: str,
        department: str,
        workers: list[str],
        *,
        actor: str = "development-user",
        note: str = "",
        order_item_id: int | None = None,
    ) -> dict:
        cleaned_workers: list[str] = []
        for worker in workers:
            worker = str(worker).strip()
            if worker and worker not in cleaned_workers:
                cleaned_workers.append(worker)
        if not cleaned_workers:
            raise ValueError("Podaj co najmniej jedną osobę w obsadzie.")

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            order = db.execute(
                "SELECT id FROM orders WHERE code = ?",
                (code,),
            ).fetchone()
            if order is None:
                raise ValueError(f"Nie znaleziono zlecenia {code}.")
            order_id = int(order["id"])

            if order_item_id is not None:
                item = db.execute(
                    """
                    SELECT id
                    FROM order_items
                    WHERE id = ? AND order_id = ?
                    """,
                    (int(order_item_id), order_id),
                ).fetchone()
                if item is None:
                    raise ValueError("Wybrana pozycja nie należy do tego ZL.")

            existing = db.execute(
                """
                SELECT id
                FROM production_sessions
                WHERE order_id = ?
                  AND department = ?
                  AND (? IS NULL OR order_item_id = ?)
                  AND status IN ('AKTYWNA', 'WSTRZYMANA')
                LIMIT 1
                """,
                (order_id, department, order_item_id, order_item_id),
            ).fetchone()
            if existing is not None:
                raise ValueError(
                    f"Dla {code} w dziale {department} istnieje już otwarta sesja "
                    "dla tej pozycji."
                )

            rows = self._department_operation_rows(
                db,
                order_id=order_id,
                department=department,
            )
            if order_item_id is not None:
                rows = [
                    row
                    for row in rows
                    if int(row["order_item_id"]) == int(order_item_id)
                ]

            eligible = [
                row
                for row in rows
                if self._row_available_to_process(row) > 0
                and int(row["good_qty"]) < int(row["planned_qty"])
            ]
            if not eligible:
                raise ValueError(
                    f"Brak dostępnych sztuk dla {code} w dziale {department}."
                )

            cursor = db.execute(
                """
                INSERT INTO production_sessions(
                    order_id,
                    order_item_id,
                    department,
                    status,
                    started_at,
                    created_by,
                    note
                )
                VALUES (?, ?, ?, 'AKTYWNA', ?, ?, ?)
                """,
                (
                    order_id,
                    order_item_id,
                    department,
                    now,
                    actor,
                    note.strip(),
                ),
            )
            session_id = int(cursor.lastrowid)

            for worker in cleaned_workers:
                db.execute(
                    """
                    INSERT INTO session_workers(
                        session_id, worker_name, joined_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (session_id, worker, now),
                )

            for row in eligible:
                db.execute(
                    """
                    UPDATE operation_progress
                    SET status = 'AKTYWNE', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, int(row["id"])),
                )

            self._audit_in_connection(
                db,
                actor=actor,
                action="session_started",
                entity_type="order",
                entity_id=code,
                payload={
                    "session_id": session_id,
                    "department": department,
                    "order_item_id": order_item_id,
                    "workers": cleaned_workers,
                },
            )

        session = self.get_department_session(
            code,
            department,
            order_item_id,
        )
        if session is None:
            raise RuntimeError("Sesja została utworzona, ale nie można jej odczytać.")
        return session


    def add_session_worker(
        self,
        code: str,
        department: str,
        worker_name: str,
        *,
        actor: str = "development-user",
    ) -> dict:
        worker_name = worker_name.strip()
        if not worker_name:
            raise ValueError("Podaj nazwę pracownika.")

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            session = db.execute(
                """
                SELECT s.id
                FROM production_sessions s
                JOIN orders o ON o.id = s.order_id
                WHERE o.code = ?
                  AND s.department = ?
                  AND s.status IN ('AKTYWNA', 'WSTRZYMANA')
                ORDER BY s.id DESC
                LIMIT 1
                """,
                (code, department),
            ).fetchone()
            if session is None:
                raise ValueError("Brak otwartej sesji.")

            session_id = int(session["id"])
            exists = db.execute(
                """
                SELECT 1
                FROM session_workers
                WHERE session_id = ?
                  AND lower(worker_name) = lower(?)
                  AND left_at IS NULL
                """,
                (session_id, worker_name),
            ).fetchone()
            if exists is not None:
                raise ValueError(f"{worker_name} jest już w obsadzie tej sesji.")

            db.execute(
                """
                INSERT INTO session_workers(
                    session_id, worker_name, joined_at
                )
                VALUES (?, ?, ?)
                """,
                (session_id, worker_name, now),
            )

            self._audit_in_connection(
                db,
                actor=actor,
                action="session_worker_joined",
                entity_type="order",
                entity_id=code,
                payload={
                    "session_id": session_id,
                    "department": department,
                    "worker": worker_name,
                },
            )

        result = self.get_department_session(code, department)
        if result is None:
            raise RuntimeError("Nie można odczytać sesji po zmianie obsady.")
        return result

    def remove_session_worker(
        self,
        code: str,
        department: str,
        worker_name: str,
        *,
        actor: str = "development-user",
    ) -> dict:
        worker_name = worker_name.strip()
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as db:
            session = db.execute(
                """
                SELECT s.id
                FROM production_sessions s
                JOIN orders o ON o.id = s.order_id
                WHERE o.code = ?
                  AND s.department = ?
                  AND s.status IN ('AKTYWNA', 'WSTRZYMANA')
                ORDER BY s.id DESC
                LIMIT 1
                """,
                (code, department),
            ).fetchone()
            if session is None:
                raise ValueError("Brak otwartej sesji.")

            session_id = int(session["id"])
            active_workers = db.execute(
                """
                SELECT id, worker_name
                FROM session_workers
                WHERE session_id = ?
                  AND left_at IS NULL
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()

            target = next(
                (
                    row
                    for row in active_workers
                    if str(row["worker_name"]).casefold() == worker_name.casefold()
                ),
                None,
            )
            if target is None:
                raise ValueError(f"{worker_name} nie jest aktywnie w tej sesji.")
            if len(active_workers) <= 1:
                raise ValueError(
                    "Nie można usunąć ostatniej osoby z otwartej sesji. "
                    "Najpierw dodaj inną osobę albo zakończ sesję."
                )

            db.execute(
                """
                UPDATE session_workers
                SET left_at = ?
                WHERE id = ?
                """,
                (now, int(target["id"])),
            )

            self._audit_in_connection(
                db,
                actor=actor,
                action="session_worker_left",
                entity_type="order",
                entity_id=code,
                payload={
                    "session_id": session_id,
                    "department": department,
                    "worker": worker_name,
                },
            )

        result = self.get_department_session(code, department)
        if result is None:
            raise RuntimeError("Nie można odczytać sesji po zmianie obsady.")
        return result

    def pause_production_session(
        self,
        code: str,
        department: str,
        *,
        actor: str = "development-user",
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT s.id, s.order_id
                FROM production_sessions s
                JOIN orders o ON o.id = s.order_id
                WHERE o.code = ?
                  AND s.department = ?
                  AND s.status = 'AKTYWNA'
                ORDER BY s.id DESC
                LIMIT 1
                """,
                (code, department),
            ).fetchone()
            if row is None:
                raise ValueError("Brak aktywnej sesji do wstrzymania.")

            session_id = int(row["id"])
            order_id = int(row["order_id"])

            db.execute(
                """
                UPDATE production_sessions
                SET status = 'WSTRZYMANA', paused_at = ?
                WHERE id = ?
                """,
                (now, session_id),
            )
            db.execute(
                """
                UPDATE operation_progress
                SET status = 'WSTRZYMANE', updated_at = ?
                WHERE department = ?
                  AND order_item_id IN (
                      SELECT id FROM order_items WHERE order_id = ?
                  )
                  AND good_qty < planned_qty
                  AND status = 'AKTYWNE'
                """,
                (now, department, order_id),
            )

            self._audit_in_connection(
                db,
                actor=actor,
                action="session_paused",
                entity_type="order",
                entity_id=code,
                payload={"session_id": session_id, "department": department},
            )

        session = self.get_department_session(code, department)
        if session is None:
            raise RuntimeError("Nie można odczytać wstrzymanej sesji.")
        return session

    def resume_production_session(
        self,
        code: str,
        department: str,
        *,
        actor: str = "development-user",
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT s.id, s.order_id
                FROM production_sessions s
                JOIN orders o ON o.id = s.order_id
                WHERE o.code = ?
                  AND s.department = ?
                  AND s.status = 'WSTRZYMANA'
                ORDER BY s.id DESC
                LIMIT 1
                """,
                (code, department),
            ).fetchone()
            if row is None:
                raise ValueError("Brak wstrzymanej sesji do wznowienia.")

            session_id = int(row["id"])
            order_id = int(row["order_id"])
            rows = self._department_operation_rows(
                db,
                order_id=order_id,
                department=department,
            )
            eligible = [
                operation
                for operation in rows
                if self._row_available_to_process(operation) > 0
                and int(operation["good_qty"]) < int(operation["planned_qty"])
            ]
            if not eligible:
                raise ValueError(
                    "Nie można wznowić sesji — brak dostępnych sztuk z poprzedniego etapu."
                )

            db.execute(
                """
                UPDATE production_sessions
                SET status = 'AKTYWNA', paused_at = NULL
                WHERE id = ?
                """,
                (session_id,),
            )
            for operation in eligible:
                db.execute(
                    """
                    UPDATE operation_progress
                    SET status = 'AKTYWNE', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, int(operation["id"])),
                )

            self._audit_in_connection(
                db,
                actor=actor,
                action="session_resumed",
                entity_type="order",
                entity_id=code,
                payload={"session_id": session_id, "department": department},
            )

        session = self.get_department_session(code, department)
        if session is None:
            raise RuntimeError("Nie można odczytać wznowionej sesji.")
        return session

    def finish_production_session(
        self,
        code: str,
        department: str,
        *,
        actor: str = "development-user",
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT s.id, s.order_id
                FROM production_sessions s
                JOIN orders o ON o.id = s.order_id
                WHERE o.code = ?
                  AND s.department = ?
                  AND s.status IN ('AKTYWNA', 'WSTRZYMANA')
                ORDER BY s.id DESC
                LIMIT 1
                """,
                (code, department),
            ).fetchone()
            if row is None:
                raise ValueError("Brak otwartej sesji do zakończenia.")

            session_id = int(row["id"])
            order_id = int(row["order_id"])

            db.execute(
                """
                UPDATE production_sessions
                SET status = 'ZAKOŃCZONA', ended_at = ?
                WHERE id = ?
                """,
                (now, session_id),
            )
            db.execute(
                """
                UPDATE session_workers
                SET left_at = COALESCE(left_at, ?)
                WHERE session_id = ?
                """,
                (now, session_id),
            )
            db.execute(
                """
                UPDATE operation_progress
                SET
                    status = CASE
                        WHEN good_qty >= planned_qty THEN 'GOTOWE'
                        ELSE 'OCZEKUJE'
                    END,
                    updated_at = ?
                WHERE department = ?
                  AND order_item_id IN (
                      SELECT id FROM order_items WHERE order_id = ?
                  )
                  AND status IN ('AKTYWNE', 'WSTRZYMANE')
                """,
                (now, department, order_id),
            )

            self._audit_in_connection(
                db,
                actor=actor,
                action="session_finished",
                entity_type="order",
                entity_id=code,
                payload={"session_id": session_id, "department": department},
            )

        return session_id

    def set_department_order_status(
        self,
        code: str,
        department: str,
        status: str,
        *,
        actor: str = "development-user",
    ) -> int:
        allowed = {"AKTYWNE", "WSTRZYMANE"}
        if status not in allowed:
            raise ValueError(f"Nieobsługiwany status operacji: {status}")

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            order = db.execute(
                "SELECT id FROM orders WHERE code = ?",
                (code,),
            ).fetchone()
            if order is None:
                raise ValueError(f"Nie znaleziono zlecenia {code}.")
            order_id = int(order["id"])

            if status == "WSTRZYMANE":
                result = db.execute(
                    """
                    UPDATE operation_progress
                    SET status = ?, updated_at = ?
                    WHERE department = ?
                      AND order_item_id IN (
                          SELECT id FROM order_items WHERE order_id = ?
                      )
                      AND good_qty < planned_qty
                      AND status = 'AKTYWNE'
                    """,
                    (status, now, department, order_id),
                )
                affected = int(result.rowcount or 0)
            else:
                rows = self._department_operation_rows(
                    db,
                    order_id=order_id,
                    department=department,
                )
                eligible_ids = [
                    int(row["id"])
                    for row in rows
                    if self._row_available_to_process(row) > 0
                    and int(row["good_qty"]) < int(row["planned_qty"])
                ]
                affected = 0
                for operation_id in eligible_ids:
                    result = db.execute(
                        """
                        UPDATE operation_progress
                        SET status = 'AKTYWNE', updated_at = ?
                        WHERE id = ?
                        """,
                        (now, operation_id),
                    )
                    affected += int(result.rowcount or 0)

            if affected == 0:
                if status == "AKTYWNE":
                    raise ValueError(
                        f"Brak dostępnych sztuk dla {code} w dziale {department}. "
                        "Najpierw poprzedni etap musi przekazać dobre sztuki."
                    )
                raise ValueError(
                    f"Brak aktywnych pozycji {code} w dziale {department} do wstrzymania."
                )

            self._audit_in_connection(
                db,
                actor=actor,
                action="operation_status_changed",
                entity_type="order",
                entity_id=code,
                payload={
                    "department": department,
                    "status": status,
                    "affected_rows": affected,
                },
            )

        return affected

    def add_department_good_qty(
        self,
        code: str,
        department: str,
        quantity: int,
        *,
        actor: str = "development-user",
        session_id: int | None = None,
    ) -> dict:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError("Ilość musi być większa od zera.")

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            order = db.execute(
                "SELECT id FROM orders WHERE code = ?",
                (code,),
            ).fetchone()
            if order is None:
                raise ValueError(f"Nie znaleziono zlecenia {code}.")
            order_id = int(order["id"])

            rows = self._department_operation_rows(
                db,
                order_id=order_id,
                department=department,
            )

            if not rows:
                raise ValueError(f"Brak operacji {department} dla {code}.")

            available_total = sum(
                self._row_available_to_process(row)
                for row in rows
            )
            if available_total <= 0:
                raise ValueError(
                    f"Brak dostępnych sztuk dla {code} w dziale {department}. "
                    "Najpierw poprzedni etap musi przekazać dobre sztuki."
                )
            if quantity > available_total:
                raise ValueError(
                    f"Można teraz dodać maksymalnie {available_total} szt. "
                    "Limit wynika z dobrych sztuk przekazanych przez poprzedni etap."
                )

            left = quantity
            touched = 0
            for row in rows:
                if left <= 0:
                    break

                planned = int(row["planned_qty"])
                current_good = int(row["good_qty"])
                available = self._row_available_to_process(row)
                if available <= 0:
                    continue

                add = min(left, available)
                new_good = current_good + add
                new_status = "GOTOWE" if new_good >= planned else "AKTYWNE"

                db.execute(
                    """
                    UPDATE operation_progress
                    SET good_qty = ?, status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_good, new_status, now, int(row["id"])),
                )
                touched += 1
                left -= add

            self._recalculate_order_percentages(db, order_id)

            self._audit_in_connection(
                db,
                actor=actor,
                action="good_quantity_added",
                entity_type="order",
                entity_id=code,
                payload={
                    "department": department,
                    "quantity": quantity,
                    "rows": touched,
                    "session_id": session_id,
                },
            )

            progress_row = db.execute(
                """
                SELECT progress, ready_percent
                FROM orders
                WHERE id = ?
                """,
                (order_id,),
            ).fetchone()

        return {
            "added": quantity,
            "progress": int(progress_row["progress"]),
            "ready_percent": int(progress_row["ready_percent"]),
        }

    def report_quality_quantity(
        self,
        code: str,
        department: str,
        kind: str,
        quantity: int,
        *,
        reason: str = "",
        note: str = "",
        actor: str = "development-user",
        session_id: int | None = None,
        rework_target_department: str | None = None,
        order_item_id: int | None = None,
    ) -> dict:
        kind = kind.strip().upper()
        aliases = {
            "BRAK": "BRAK",
            "REJECT": "BRAK",
            "POPRAWKA": "POPRAWKA",
            "REWORK": "POPRAWKA",
            "ZŁOM": "ZŁOM",
            "ZLOM": "ZŁOM",
            "SCRAP": "ZŁOM",
        }
        kind = aliases.get(kind, kind)
        if kind not in {"BRAK", "POPRAWKA", "ZŁOM"}:
            raise ValueError("Nieprawidłowy typ zgłoszenia jakości.")

        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError("Ilość musi być większa od zera.")

        reason = reason.strip()
        if not reason:
            raise ValueError("Podaj przyczynę zgłoszenia jakości.")

        if kind == "POPRAWKA":
            rework_target_department = str(rework_target_department or "").strip()
            if not rework_target_department:
                raise ValueError("Wybierz wcześniejszy etap, do którego ma wrócić poprawka.")

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            order = db.execute(
                "SELECT id FROM orders WHERE code = ?",
                (code,),
            ).fetchone()
            if order is None:
                raise ValueError(f"Nie znaleziono zlecenia {code}.")
            order_id = int(order["id"])

            rows = self._department_operation_rows(
                db,
                order_id=order_id,
                department=department,
            )
            if order_item_id is not None:
                rows = [
                    row
                    for row in rows
                    if int(row["order_item_id"]) == int(order_item_id)
                ]
            if not rows:
                raise ValueError(f"Brak operacji {department} dla {code}.")

            target_operations: dict[int, int] = {}
            if kind == "POPRAWKA":
                for row in rows:
                    target = db.execute(
                        """
                        SELECT id
                        FROM operation_progress
                        WHERE order_item_id = ?
                          AND department = ?
                          AND sequence_no < ?
                        LIMIT 1
                        """,
                        (
                            int(row["order_item_id"]),
                            rework_target_department,
                            int(row["sequence_no"]),
                        ),
                    ).fetchone()
                    if target is None:
                        raise ValueError(
                            f"Etap {rework_target_department} nie jest wcześniejszym "
                            f"etapem dla {department}."
                        )
                    target_operations[int(row["id"])] = int(target["id"])

            available_total = sum(
                self._row_available_to_process(row)
                for row in rows
            )
            if quantity > available_total:
                raise ValueError(
                    f"Można zgłosić maksymalnie {available_total} szt. "
                    "Tyle sztuk jest jeszcze dostępnych do rozliczenia w tym etapie."
                )

            target_column = {
                "BRAK": "reject_qty",
                "POPRAWKA": "rework_qty",
                "ZŁOM": "scrap_qty",
            }[kind]

            left = quantity
            touched = 0
            for row in rows:
                if left <= 0:
                    break
                available = self._row_available_to_process(row)
                if available <= 0:
                    continue

                add = min(left, available)
                source_operation_id = int(row["id"])
                db.execute(
                    f"""
                    UPDATE operation_progress
                    SET {target_column} = {target_column} + ?,
                        status = CASE
                            WHEN status = 'OCZEKUJE' THEN 'AKTYWNE'
                            ELSE status
                        END,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (add, now, source_operation_id),
                )

                if kind == "POPRAWKA":
                    db.execute(
                        """
                        INSERT INTO rework_jobs(
                            order_id,
                            order_item_id,
                            source_operation_id,
                            target_operation_id,
                            source_department,
                            target_department,
                            quantity,
                            status,
                            reason,
                            note,
                            session_id,
                            created_at,
                            updated_at,
                            actor
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'DO_NAPRAWY', ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            order_id,
                            int(row["order_item_id"]),
                            source_operation_id,
                            target_operations[source_operation_id],
                            department,
                            rework_target_department,
                            add,
                            reason,
                            note.strip(),
                            session_id,
                            now,
                            now,
                            actor,
                        ),
                    )

                left -= add
                touched += 1

            db.execute(
                """
                INSERT INTO quality_events(
                    order_id, order_item_id, department, kind, quantity, reason, note,
                    session_id, occurred_at, actor
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    order_item_id,
                    department,
                    kind,
                    quantity,
                    reason,
                    note.strip(),
                    session_id,
                    now,
                    actor,
                ),
            )

            self._recalculate_order_percentages(db, order_id)

            self._audit_in_connection(
                db,
                actor=actor,
                action="quality_reported",
                entity_type="order",
                entity_id=code,
                payload={
                    "department": department,
                    "order_item_id": order_item_id,
                    "kind": kind,
                    "quantity": quantity,
                    "reason": reason,
                    "note": note.strip(),
                    "session_id": session_id,
                    "rework_target_department": rework_target_department,
                    "rows": touched,
                },
            )

        return {
            "kind": kind,
            "quantity": quantity,
            "remaining_capacity": max(0, available_total - quantity),
            "rework_target_department": rework_target_department,
            "order_item_id": order_item_id,
        }

    def get_rework_target_departments(
        self,
        code: str,
        department: str,
        order_item_id: int | None = None,
    ) -> list[str]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT DISTINCT
                    source.sequence_no AS source_sequence,
                    target.department AS target_department,
                    target.sequence_no AS target_sequence
                FROM operation_progress source
                JOIN order_items oi ON oi.id = source.order_item_id
                JOIN orders o ON o.id = oi.order_id
                JOIN operation_progress target
                    ON target.order_item_id = source.order_item_id
                   AND target.sequence_no < source.sequence_no
                WHERE o.code = ?
                  AND source.department = ?
                  AND (? IS NULL OR source.order_item_id = ?)
                ORDER BY target.sequence_no DESC
                """,
                (code, department, order_item_id, order_item_id),
            ).fetchall()

        seen: set[str] = set()
        result: list[str] = []
        for row in rows:
            name = str(row["target_department"])
            if name not in seen:
                seen.add(name)
                result.append(name)
        return result

    def list_rework_jobs(
        self,
        *,
        code: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        where: list[str] = []
        params: list[object] = []

        if code:
            where.append("o.code = ?")
            params.append(code)
        if status:
            where.append("r.status = ?")
            params.append(status)

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        params.append(max(1, min(int(limit), 2000)))

        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT
                    r.id,
                    o.code,
                    oi.symbol,
                    oi.name,
                    r.source_department,
                    r.target_department,
                    r.quantity,
                    r.status,
                    r.reason,
                    r.note,
                    r.session_id,
                    r.created_at,
                    r.updated_at,
                    r.actor
                FROM rework_jobs r
                JOIN orders o ON o.id = r.order_id
                JOIN order_items oi ON oi.id = r.order_item_id
                {where_sql}
                ORDER BY
                    CASE r.status
                        WHEN 'DO_NAPRAWY' THEN 0
                        WHEN 'W_NAPRAWIE' THEN 1
                        WHEN 'DO_KONTROLI' THEN 2
                        ELSE 3
                    END,
                    r.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]

    def transition_rework_job(
        self,
        job_id: int,
        action: str,
        *,
        actor: str = "development-user",
    ) -> dict:
        action = action.strip().upper()
        transitions = {
            "START": ("DO_NAPRAWY", "W_NAPRAWIE"),
            "NAPRAWIONE": ("W_NAPRAWIE", "DO_KONTROLI"),
            "AKCEPTUJ": ("DO_KONTROLI", "ZAMKNIĘTA"),
        }
        if action not in {*transitions.keys(), "ZŁOM", "ZLOM"}:
            raise ValueError("Nieprawidłowa akcja poprawki.")

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT
                    r.*,
                    o.code
                FROM rework_jobs r
                JOIN orders o ON o.id = r.order_id
                WHERE r.id = ?
                """,
                (int(job_id),),
            ).fetchone()
            if row is None:
                raise ValueError("Nie znaleziono poprawki.")

            current = str(row["status"])
            quantity = int(row["quantity"])

            if action in {"ZŁOM", "ZLOM"}:
                if current not in {"DO_NAPRAWY", "W_NAPRAWIE", "DO_KONTROLI"}:
                    raise ValueError("Tej poprawki nie można już zezłomować.")

                source = db.execute(
                    """
                    SELECT rework_qty, scrap_qty
                    FROM operation_progress
                    WHERE id = ?
                    """,
                    (int(row["source_operation_id"]),),
                ).fetchone()
                if source is None or int(source["rework_qty"]) < quantity:
                    raise RuntimeError("Niespójna ilość poprawki w operacji źródłowej.")

                db.execute(
                    """
                    UPDATE operation_progress
                    SET
                        rework_qty = rework_qty - ?,
                        scrap_qty = scrap_qty + ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        quantity,
                        quantity,
                        now,
                        int(row["source_operation_id"]),
                    ),
                )
                new_status = "ZŁOM"
            else:
                expected, new_status = transitions[action]
                if current != expected:
                    raise ValueError(
                        f"Akcja {action} wymaga statusu {expected}, "
                        f"a poprawka ma status {current}."
                    )

                if action == "AKCEPTUJ":
                    source = db.execute(
                        """
                        SELECT rework_qty
                        FROM operation_progress
                        WHERE id = ?
                        """,
                        (int(row["source_operation_id"]),),
                    ).fetchone()
                    if source is None or int(source["rework_qty"]) < quantity:
                        raise RuntimeError("Niespójna ilość poprawki w operacji źródłowej.")

                    db.execute(
                        """
                        UPDATE operation_progress
                        SET
                            rework_qty = rework_qty - ?,
                            status = CASE
                                WHEN good_qty >= planned_qty THEN 'GOTOWE'
                                ELSE 'AKTYWNE'
                            END,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            quantity,
                            now,
                            int(row["source_operation_id"]),
                        ),
                    )

            db.execute(
                """
                UPDATE rework_jobs
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, now, int(job_id)),
            )

            self._recalculate_order_percentages(db, int(row["order_id"]))

            self._audit_in_connection(
                db,
                actor=actor,
                action="rework_status_changed",
                entity_type="order",
                entity_id=str(row["code"]),
                payload={
                    "rework_id": int(job_id),
                    "action": action,
                    "from": current,
                    "to": new_status,
                    "quantity": quantity,
                    "source_department": row["source_department"],
                    "target_department": row["target_department"],
                },
            )

        jobs = self.list_rework_jobs(code=str(row["code"]), limit=1000)
        updated = next((job for job in jobs if int(job["id"]) == int(job_id)), None)
        if updated is None:
            raise RuntimeError("Nie można odczytać poprawki po zmianie statusu.")
        return updated

    def list_quality_events(
        self,
        *,
        code: str | None = None,
        department: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        where: list[str] = []
        params: list[object] = []

        if code:
            where.append("o.code = ?")
            params.append(code)
        if department:
            where.append("q.department = ?")
            params.append(department)

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        params.append(max(1, min(int(limit), 2000)))

        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT
                    q.id,
                    o.code,
                    q.order_item_id,
                    oi.position_no,
                    oi.symbol,
                    oi.name,
                    q.department,
                    q.kind,
                    q.quantity,
                    q.reason,
                    q.note,
                    q.session_id,
                    q.occurred_at,
                    q.actor
                FROM quality_events q
                JOIN orders o ON o.id = q.order_id
                LEFT JOIN order_items oi ON oi.id = q.order_item_id
                {where_sql}
                ORDER BY q.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]

    def quality_summary(self) -> dict:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT kind, COALESCE(SUM(quantity), 0) AS quantity
                FROM quality_events
                GROUP BY kind
                """
            ).fetchall()
        values = {str(row["kind"]): int(row["quantity"]) for row in rows}
        return {
            "reject": values.get("BRAK", 0),
            "rework": values.get("POPRAWKA", 0),
            "scrap": values.get("ZŁOM", 0),
        }

    def get_item_department_capacity(
        self,
        code: str,
        order_item_id: int,
        department: str,
    ) -> dict:
        with self._connect() as db:
            order = db.execute(
                "SELECT id FROM orders WHERE code = ?",
                (code,),
            ).fetchone()
            if order is None:
                raise ValueError(f"Nie znaleziono zlecenia {code}.")

            rows = self._department_operation_rows(
                db,
                order_id=int(order["id"]),
                department=department,
            )
            rows = [
                row
                for row in rows
                if int(row["order_item_id"]) == int(order_item_id)
            ]
            if not rows:
                raise ValueError(
                    "Wybrana pozycja nie ma tej operacji."
                )

        return {
            "remaining": sum(
                max(0, int(row["planned_qty"]) - int(row["good_qty"]))
                for row in rows
            ),
            "available_now": sum(
                self._row_available_to_process(row)
                for row in rows
            ),
        }

    def get_department_order_capacity(
        self,
        code: str,
        department: str,
        order_item_id: int | None = None,
    ) -> dict:
        with self._connect() as db:
            order = db.execute(
                "SELECT id FROM orders WHERE code = ?",
                (code,),
            ).fetchone()
            if order is None:
                raise ValueError(f"Nie znaleziono zlecenia {code}.")

            rows = self._department_operation_rows(
                db,
                order_id=int(order["id"]),
                department=department,
            )

        demand_remaining = sum(
            max(0, int(row["planned_qty"]) - int(row["good_qty"]))
            for row in rows
        )
        available_now = sum(self._row_available_to_process(row) for row in rows)
        return {
            "remaining": demand_remaining,
            "available_now": available_now,
        }

    @staticmethod
    def _department_operation_rows(
        db: sqlite3.Connection,
        *,
        order_id: int,
        department: str,
    ) -> list[sqlite3.Row]:
        return db.execute(
            """
            SELECT
                op.id,
                op.order_item_id,
                op.sequence_no,
                op.planned_qty,
                op.good_qty,
                op.reject_qty,
                op.rework_qty,
                op.scrap_qty,
                op.status,
                oi.position_no,
                CASE
                    WHEN op.sequence_no = 1 THEN op.planned_qty
                    ELSE COALESCE(prev.good_qty, 0)
                END AS upstream_good_qty
            FROM operation_progress op
            JOIN order_items oi ON oi.id = op.order_item_id
            LEFT JOIN operation_progress prev
                ON prev.order_item_id = op.order_item_id
               AND prev.sequence_no = op.sequence_no - 1
            WHERE oi.order_id = ?
              AND op.department = ?
            ORDER BY oi.position_no ASC
            """,
            (order_id, department),
        ).fetchall()

    @staticmethod
    def _row_available_to_process(row: sqlite3.Row) -> int:
        planned = max(0, int(row["planned_qty"]))
        good = max(0, int(row["good_qty"]))
        reject = max(0, int(row["reject_qty"]))
        rework = max(0, int(row["rework_qty"]))
        scrap = max(0, int(row["scrap_qty"]))
        upstream_good = max(0, int(row["upstream_good_qty"]))
        allowed_total = min(planned, upstream_good)
        processed = good + reject + rework + scrap
        return max(0, allowed_total - processed)

    @staticmethod
    def _recalculate_order_percentages(
        db: sqlite3.Connection,
        order_id: int,
    ) -> None:
        totals = db.execute(
            """
            SELECT
                COALESCE(SUM(op.planned_qty), 0) AS planned,
                COALESCE(SUM(op.good_qty), 0) AS good
            FROM operation_progress op
            JOIN order_items oi ON oi.id = op.order_item_id
            WHERE oi.order_id = ?
            """,
            (order_id,),
        ).fetchone()

        final_totals = db.execute(
            """
            SELECT
                COALESCE(SUM(op.planned_qty), 0) AS planned,
                COALESCE(SUM(op.good_qty), 0) AS good
            FROM operation_progress op
            JOIN order_items oi ON oi.id = op.order_item_id
            WHERE oi.order_id = ?
              AND op.sequence_no = (
                  SELECT MAX(op2.sequence_no)
                  FROM operation_progress op2
                  WHERE op2.order_item_id = op.order_item_id
              )
            """,
            (order_id,),
        ).fetchone()

        planned = int(totals["planned"])
        good = int(totals["good"])
        final_planned = int(final_totals["planned"])
        final_good = int(final_totals["good"])

        progress = round((good / planned) * 100) if planned > 0 else 0
        ready_percent = (
            round((final_good / final_planned) * 100)
            if final_planned > 0
            else 0
        )

        db.execute(
            """
            UPDATE orders
            SET progress = ?, ready_percent = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                max(0, min(100, progress)),
                max(0, min(100, ready_percent)),
                datetime.now(timezone.utc).isoformat(),
                order_id,
            ),
        )

    def dashboard_live_orders(self, limit: int = 4) -> list[dict]:
        result: list[dict] = []
        orders = [
            row
            for row in self.list_orders()
            if row["status"] not in {"ZAKOŃCZONE", "ANULOWANE"}
        ]

        for order in orders:
            stages = self.get_order_stage_progress(str(order["code"]))
            if not stages:
                continue

            current = next(
                (stage for stage in stages if stage["status"] == "WSTRZYMANE"),
                None,
            )
            if current is None:
                current = next(
                    (
                        stage
                        for stage in stages
                        if int(stage["good_qty"]) < int(stage["planned_qty"])
                    ),
                    stages[-1],
                )

            details = self.get_order(str(order["code"])) or {}
            items = details.get("items", [])
            if items:
                first = items[0]
                product = f'{first["symbol"]} {first["name"]}'.strip()
                if len(items) > 1:
                    product += f"  +{len(items) - 1}"
            else:
                product = str(order["client"] or "—")

            result.append(
                {
                    "code": order["code"],
                    "department": current["department"],
                    "product": product,
                    "planned_qty": int(current["planned_qty"]),
                    "good_qty": int(current["good_qty"]),
                    "status": current["status"],
                    "deadline": order["deadline"],
                    "priority": order["priority"],
                }
            )
            if len(result) >= max(1, int(limit)):
                break

        return result

    def list_alerts(self) -> list[dict]:
        alerts: list[dict] = []

        for order in self.list_orders(filter_key="Opóźnione"):
            alerts.append(
                {
                    "severity": "WYSOKI",
                    "code": order["code"],
                    "area": "Termin",
                    "message": (
                        f"Termin {order['deadline']} minął, "
                        f"gotowość {order['ready_percent']}%."
                    ),
                    "owner": "Kierownik",
                    "kind": "deadline",
                }
            )

        with self._connect() as db:
            rows = db.execute(
                """
                SELECT DISTINCT
                    o.code,
                    op.department
                FROM operation_progress op
                JOIN order_items oi ON oi.id = op.order_item_id
                JOIN orders o ON o.id = oi.order_id
                WHERE op.status = 'WSTRZYMANE'
                  AND o.status NOT IN ('ZAKOŃCZONE', 'ANULOWANE')
                ORDER BY o.code, op.department
                """
            ).fetchall()

        for row in rows:
            alerts.append(
                {
                    "severity": "WYSOKI",
                    "code": row["code"],
                    "area": row["department"],
                    "message": "Etap produkcji jest wstrzymany.",
                    "owner": "Brygadzista",
                    "kind": "paused",
                }
            )

        return alerts

    def dashboard_alert_count(self) -> int:
        return len(self.list_alerts())

    def list_audit_events(
        self,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        where: list[str] = []
        params: list[object] = []

        if entity_type:
            where.append("entity_type = ?")
            params.append(entity_type)
        if entity_id:
            where.append("entity_id = ?")
            params.append(entity_id)

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        params.append(max(1, min(int(limit), 1000)))

        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT
                    occurred_at,
                    actor,
                    action,
                    entity_type,
                    entity_id,
                    payload_json
                FROM audit_events
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json"))
            except (ValueError, TypeError):
                item["payload"] = {}
                item.pop("payload_json", None)
            result.append(item)
        return result

    def add_audit_event(
        self,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: dict | None = None,
    ) -> None:
        with self._connect() as db:
            self._audit_in_connection(
                db,
                actor=actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload or {},
            )

    @staticmethod
    def _audit_in_connection(
        db: sqlite3.Connection,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: dict,
    ) -> None:
        db.execute(
            """
            INSERT INTO audit_events(
                occurred_at, actor, action, entity_type, entity_id, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                actor,
                action,
                entity_type,
                entity_id,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 1


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

            if current < 1:
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

                    CREATE INDEX IF NOT EXISTS idx_order_items_order
                        ON order_items(order_id);

                    CREATE INDEX IF NOT EXISTS idx_audit_entity
                        ON audit_events(entity_type, entity_id, occurred_at);
                    """
                )
                db.execute("PRAGMA user_version = 1")

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
                for position_no, (symbol, name, quantity) in enumerate(order["items"], start=1):
                    db.execute(
                        """
                        INSERT INTO order_items(order_id, position_no, symbol, name, quantity)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (order_id, position_no, symbol, name, quantity),
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

    def list_orders(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT code, client, deadline, priority, status, progress, ready_percent
                FROM orders
                ORDER BY deadline ASC, code ASC
                """
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
                SELECT position_no, symbol, name, quantity
                FROM order_items
                WHERE order_id = ?
                ORDER BY position_no ASC
                """,
                (int(order["id"]),),
            ).fetchall()

        result = dict(order)
        result["items"] = [dict(row) for row in items]
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

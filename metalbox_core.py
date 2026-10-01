from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 2


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

            if current < 2:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS operation_progress (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        order_item_id INTEGER NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
                        department TEXT NOT NULL,
                        sequence_no INTEGER NOT NULL,
                        planned_qty INTEGER NOT NULL CHECK(planned_qty >= 0),
                        good_qty INTEGER NOT NULL DEFAULT 0 CHECK(good_qty >= 0),
                        reject_qty INTEGER NOT NULL DEFAULT 0 CHECK(reject_qty >= 0),
                        rework_qty INTEGER NOT NULL DEFAULT 0 CHECK(rework_qty >= 0),
                        status TEXT NOT NULL DEFAULT 'OCZEKUJE',
                        updated_at TEXT NOT NULL,
                        UNIQUE(order_item_id, department)
                    );

                    CREATE INDEX IF NOT EXISTS idx_operation_progress_item
                        ON operation_progress(order_item_id);

                    CREATE INDEX IF NOT EXISTS idx_operation_progress_department
                        ON operation_progress(department, status);
                    """
                )
                db.execute("PRAGMA user_version = 2")

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

    def list_department_queue(self, department: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT
                    o.code,
                    o.client,
                    GROUP_CONCAT(DISTINCT oi.symbol || ' ' || oi.name) AS products,
                    SUM(op.planned_qty) AS planned_qty,
                    SUM(op.good_qty) AS good_qty,
                    SUM(op.reject_qty) AS reject_qty,
                    SUM(op.rework_qty) AS rework_qty,
                    CASE
                        WHEN SUM(CASE WHEN op.status = 'WSTRZYMANE' THEN 1 ELSE 0 END) > 0
                            THEN 'WSTRZYMANE'
                        WHEN SUM(op.planned_qty) > 0
                             AND SUM(op.good_qty) >= SUM(op.planned_qty)
                            THEN 'GOTOWE'
                        WHEN SUM(op.good_qty) > 0
                            THEN 'AKTYWNE'
                        ELSE 'OCZEKUJE'
                    END AS status,
                    o.deadline,
                    o.priority
                FROM operation_progress op
                JOIN order_items oi ON oi.id = op.order_item_id
                JOIN orders o ON o.id = oi.order_id
                WHERE op.department = ?
                  AND o.status NOT IN ('ANULOWANE')
                GROUP BY o.id, o.code, o.client, o.deadline, o.priority
                ORDER BY
                    CASE
                        WHEN o.priority = 'WYSOKI' THEN 0
                        ELSE 1
                    END,
                    o.deadline ASC,
                    o.code ASC
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

            result = db.execute(
                """
                UPDATE operation_progress
                SET status = ?, updated_at = ?
                WHERE department = ?
                  AND order_item_id IN (
                      SELECT id FROM order_items WHERE order_id = ?
                  )
                  AND good_qty < planned_qty
                """,
                (status, now, department, int(order["id"])),
            )

            affected = int(result.rowcount or 0)
            if affected == 0:
                raise ValueError(
                    f"Brak aktywnych pozycji {code} w dziale {department} do zmiany statusu."
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

            rows = db.execute(
                """
                SELECT
                    op.id,
                    op.planned_qty,
                    op.good_qty,
                    op.status,
                    oi.position_no
                FROM operation_progress op
                JOIN order_items oi ON oi.id = op.order_item_id
                WHERE oi.order_id = ?
                  AND op.department = ?
                ORDER BY oi.position_no ASC
                """,
                (order_id, department),
            ).fetchall()

            if not rows:
                raise ValueError(f"Brak operacji {department} dla {code}.")

            remaining_total = sum(
                max(0, int(row["planned_qty"]) - int(row["good_qty"]))
                for row in rows
            )
            if quantity > remaining_total:
                raise ValueError(
                    f"Można dodać maksymalnie {remaining_total} szt. "
                    f"Pozostało do wykonania w tym dziale."
                )

            left = quantity
            touched = 0
            for row in rows:
                if left <= 0:
                    break

                planned = int(row["planned_qty"])
                current_good = int(row["good_qty"])
                remaining = max(0, planned - current_good)
                if remaining == 0:
                    continue

                add = min(left, remaining)
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

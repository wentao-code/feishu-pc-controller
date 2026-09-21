"""Durable, idempotent storage for task reports received by the controller."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from task_protocol import TaskReport


class ReportStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self._lock = threading.RLock()
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS task_reports (
                event_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS task_latest (
                task_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self._connection.commit()

    def record(self, report: TaskReport) -> bool:
        payload = json.dumps(report.to_json(), ensure_ascii=False)
        received_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO task_reports(event_id, task_id, payload, received_at)
                VALUES (?, ?, ?, ?)
                """,
                (report.event_id, report.task_id, payload, received_at),
            )
            if cursor.rowcount == 0:
                return False
            self._connection.execute(
                """
                INSERT INTO task_latest(task_id, source, task_type, status, payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    source=excluded.source,
                    task_type=excluded.task_type,
                    status=excluded.status,
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (
                    report.task_id,
                    report.source,
                    report.task_type,
                    report.status,
                    payload,
                    received_at,
                ),
            )
            self._connection.commit()
            return True

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM task_latest WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row[0])

    def latest_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM task_latest ORDER BY updated_at DESC LIMIT ?",
                (max(int(limit), 1),),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._connection.close()

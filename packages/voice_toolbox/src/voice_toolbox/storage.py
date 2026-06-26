from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from voice_toolbox.models import Artifact, OperationResult


class MetadataStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self._create_tables()

    def _create_tables(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                artifact_ids TEXT NOT NULL DEFAULT '[]',
                error_summary TEXT
            )
            """
        )
        self.connection.commit()

    def table_names(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        return {row[0] for row in rows}

    def insert_artifact(self, artifact: Artifact | None = None, **fields: Any) -> None:
        if artifact is not None:
            payload = artifact.model_dump(mode="json")
        else:
            payload = fields

        self.connection.execute(
            """
            INSERT INTO artifacts (
                id, kind, provider_id, operation, path, mime_type, created_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["id"],
                payload["kind"],
                payload["provider_id"],
                payload["operation"],
                str(payload["path"]),
                payload["mime_type"],
                payload["created_at"],
                json.dumps(payload.get("metadata", {}), ensure_ascii=False, sort_keys=True),
            ),
        )
        self.connection.commit()

    def insert_operation(self, operation: OperationResult | None = None, **fields: Any) -> None:
        if operation is not None:
            payload = operation.model_dump(mode="json")
        else:
            payload = fields

        self.connection.execute(
            """
            INSERT INTO operations (
                operation_id, operation, status, started_at, finished_at, artifact_ids, error_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["operation_id"],
                payload["operation"],
                payload["status"],
                payload["started_at"],
                payload["finished_at"],
                json.dumps(payload.get("artifact_ids", []), ensure_ascii=False, sort_keys=True),
                payload.get("error_summary"),
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> MetadataStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

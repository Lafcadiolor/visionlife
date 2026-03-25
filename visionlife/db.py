"""SQLite history storage for dedupe and processing outcomes."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class HistoryRecord:
    """One persisted media-history row materialized as a typed object."""
    file_hash: str
    source_path: str
    status: str
    first_seen_at: str
    last_seen_at: str
    analysis_path: str | None
    result_path: str | None
    fast_sort_label: str | None
    fast_sort_confidence: float | None
    notes: list[str]
    metadata_json: dict[str, Any]
    last_error: str | None


class HistoryStore:
    """Repository wrapper around the local SQLite media history database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.initialize()

    def initialize(self) -> None:
        """Create the history table if it does not already exist."""
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS media_history (
                    file_hash TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    analysis_path TEXT,
                    result_path TEXT,
                    fast_sort_label TEXT,
                    fast_sort_confidence REAL,
                    notes_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    last_error TEXT
                )
                """
            )

    def get(self, file_hash: str) -> HistoryRecord | None:
        """Look up a previously seen file by its content hash."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT file_hash, source_path, status, first_seen_at, last_seen_at,
                       analysis_path, result_path, fast_sort_label, fast_sort_confidence,
                       notes_json, metadata_json, last_error
                FROM media_history
                WHERE file_hash = ?
                """,
                (file_hash,),
            ).fetchone()

        if row is None:
            return None

        return HistoryRecord(
            file_hash=row[0],
            source_path=row[1],
            status=row[2],
            first_seen_at=row[3],
            last_seen_at=row[4],
            analysis_path=row[5],
            result_path=row[6],
            fast_sort_label=row[7],
            fast_sort_confidence=row[8],
            notes=json.loads(row[9]),
            metadata_json=json.loads(row[10]),
            last_error=row[11],
        )

    def upsert(
        self,
        *,
        file_hash: str,
        source_path: Path,
        status: str,
        analysis_path: Path | None = None,
        result_path: Path | None = None,
        fast_sort_label: str | None = None,
        fast_sort_confidence: float | None = None,
        notes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        last_error: str | None = None,
    ) -> None:
        """Insert or update the latest known processing state for a file hash."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO media_history (
                    file_hash,
                    source_path,
                    status,
                    analysis_path,
                    result_path,
                    fast_sort_label,
                    fast_sort_confidence,
                    notes_json,
                    metadata_json,
                    last_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_hash) DO UPDATE SET
                    source_path = excluded.source_path,
                    status = excluded.status,
                    analysis_path = excluded.analysis_path,
                    result_path = excluded.result_path,
                    fast_sort_label = excluded.fast_sort_label,
                    fast_sort_confidence = excluded.fast_sort_confidence,
                    notes_json = excluded.notes_json,
                    metadata_json = excluded.metadata_json,
                    last_error = excluded.last_error,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (
                    file_hash,
                    str(source_path),
                    status,
                    str(analysis_path) if analysis_path else None,
                    str(result_path) if result_path else None,
                    fast_sort_label,
                    fast_sort_confidence,
                    json.dumps(notes or []),
                    json.dumps(metadata or {}),
                    last_error,
                ),
            )

    def mark_duplicate(self, file_hash: str, source_path: Path, note: str) -> None:
        """Record that a previously seen asset was observed again."""
        existing = self.get(file_hash)
        notes = list(existing.notes) if existing else []
        notes.append(note)

        self.upsert(
            file_hash=file_hash,
            source_path=source_path,
            status=existing.status if existing else "duplicate",
            analysis_path=Path(existing.analysis_path) if existing and existing.analysis_path else None,
            result_path=Path(existing.result_path) if existing and existing.result_path else None,
            fast_sort_label=existing.fast_sort_label if existing else None,
            fast_sort_confidence=existing.fast_sort_confidence if existing else None,
            notes=notes,
            metadata=existing.metadata_json if existing else {},
            last_error=existing.last_error if existing else None,
        )

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with WAL mode enabled for concurrent readers."""
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

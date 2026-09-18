"""SQLite database operations for TranscribeRec."""

import sqlite3
import os
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Iterator

from src.config import DATABASE_PATH, UPLOADS_PATH


class Database:
    """Handle all database operations."""

    def __init__(self, db_path: str = DATABASE_PATH):
        """Initialize database connection."""
        self.db_path = db_path
        self.ensure_uploads_dir()
        self.init_db()

    def ensure_uploads_dir(self) -> None:
        """Ensure uploads directory exists."""
        os.makedirs(UPLOADS_PATH, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Get database connection with foreign key enforcement enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # SQLite defaults foreign_keys to OFF and the setting is per-connection,
        # so ON DELETE CASCADE is inert unless this runs on every connection.
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _cursor(self, commit: bool = False) -> Iterator[sqlite3.Cursor]:
        """Yield a cursor on a fresh connection, closing it even if the body raises."""
        conn = self.get_connection()
        try:
            yield conn.cursor()
            if commit:
                conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initialize database schema if it doesn't exist."""
        with self._cursor(commit=True) as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration REAL,
                    file_size INTEGER,
                    language TEXT DEFAULT 'en-US'
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transcriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL,
                    transcript TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT,
                    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcription_id INTEGER NOT NULL,
                    summary_text TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    summary_length INTEGER,
                    error_message TEXT,
                    FOREIGN KEY (transcription_id) REFERENCES transcriptions(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_transcriptions_recording_id
                ON transcriptions(recording_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_summaries_transcription_id
                ON summaries(transcription_id)
            """)

    def add_recording(self, filename: str, file_path: str, file_size: int,
                      language: str = "en-US") -> int:
        """Add a new recording and its pending transcription row."""
        with self._cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO recordings (filename, file_path, file_size, language)
                VALUES (?, ?, ?, ?)
            """, (filename, file_path, file_size, language))

            recording_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO transcriptions (recording_id, status)
                VALUES (?, 'pending')
            """, (recording_id,))

        return recording_id

    def get_recordings(self) -> List[Dict[str, Any]]:
        """Get all recordings, newest first."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM recordings ORDER BY upload_date DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_recording(self, recording_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific recording."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,))
            row = cursor.fetchone()

        return dict(row) if row else None

    def update_transcription(self, transcription_id: int, transcript: str,
                             status: str = "completed") -> None:
        """Update transcription with transcript text."""
        with self._cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE transcriptions
                SET transcript = ?, status = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (transcript, status, transcription_id))

    def update_transcription_error(self, transcription_id: int, error_message: str,
                                   partial_transcript: Optional[str] = None) -> None:
        """Mark a transcription failed, never discarding text already recognized.

        A failure after the transcript was committed must not blank it; the run
        keeps whatever text exists and is recorded as partial rather than failed.
        """
        with self._cursor(commit=True) as cursor:
            if partial_transcript:
                cursor.execute("""
                    UPDATE transcriptions
                    SET status = 'partial', transcript = ?, error_message = ?,
                        completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (partial_transcript, error_message, transcription_id))
            else:
                cursor.execute("""
                    UPDATE transcriptions
                    SET status = CASE
                            WHEN transcript IS NOT NULL AND transcript != '' THEN 'partial'
                            ELSE 'failed'
                        END,
                        error_message = ?,
                        completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (error_message, transcription_id))

    def get_transcription(self, recording_id: int) -> Optional[Dict[str, Any]]:
        """Get transcription for a recording."""
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT * FROM transcriptions WHERE recording_id = ?
            """, (recording_id,))
            row = cursor.fetchone()

        return dict(row) if row else None

    def add_summary(self, transcription_id: int) -> int:
        """Add a pending summary record for a transcription."""
        with self._cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO summaries (transcription_id, status)
                VALUES (?, 'pending')
            """, (transcription_id,))
            summary_id = cursor.lastrowid

        return summary_id

    def update_summary(self, summary_id: int, summary_text: str,
                       status: str = "completed") -> None:
        """Update summary with summary text."""
        with self._cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE summaries
                SET summary_text = ?, status = ?, summary_length = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (summary_text, status, len(summary_text), summary_id))

    def update_summary_error(self, summary_id: int, error_message: str) -> None:
        """Mark a summary as failed with an error message."""
        with self._cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE summaries
                SET status = 'failed', error_message = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (error_message, summary_id))

    def update_summary_skipped(self, summary_id: int, reason: str) -> None:
        """Mark a summary as never attempted, recording why.

        Distinct from 'failed': no Azure call was made, so this is not an error.
        """
        with self._cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE summaries
                SET status = 'skipped', error_message = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (reason, summary_id))

    def get_summary(self, transcription_id: int) -> Optional[Dict[str, Any]]:
        """Get summary for a transcription."""
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT * FROM summaries WHERE transcription_id = ?
            """, (transcription_id,))
            row = cursor.fetchone()

        return dict(row) if row else None

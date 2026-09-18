"""SQLite database operations for TranscribeRec."""

import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from config import DATABASE_PATH, UPLOADS_PATH

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
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initialize database schema if it doesn't exist."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Create recordings table
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

        # Create transcriptions table
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

        # Create summaries table
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

        conn.commit()
        conn.close()

    def add_recording(self, filename: str, file_path: str, file_size: int,
                     language: str = "en-US") -> int:
        """Add a new recording to the database."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO recordings (filename, file_path, file_size, language)
            VALUES (?, ?, ?, ?)
        """, (filename, file_path, file_size, language))

        recording_id = cursor.lastrowid

        # Create corresponding transcription record
        cursor.execute("""
            INSERT INTO transcriptions (recording_id, status)
            VALUES (?, 'pending')
        """, (recording_id,))

        conn.commit()
        conn.close()

        return recording_id

    def get_recordings(self) -> List[Dict[str, Any]]:
        """Get all recordings."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM recordings ORDER BY upload_date DESC")
        recordings = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return recordings

    def get_recording(self, recording_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific recording."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()

        conn.close()
        return dict(row) if row else None

    def update_transcription(self, transcription_id: int, transcript: str,
                            status: str = "completed") -> None:
        """Update transcription with transcript text."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE transcriptions
            SET transcript = ?, status = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (transcript, status, transcription_id))

        conn.commit()
        conn.close()

    def update_transcription_error(self, transcription_id: int, error_message: str) -> None:
        """Mark transcription as failed with error message."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE transcriptions
            SET status = 'failed', error_message = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (error_message, transcription_id))

        conn.commit()
        conn.close()

    def get_transcription(self, recording_id: int) -> Optional[Dict[str, Any]]:
        """Get transcription for a recording."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM transcriptions WHERE recording_id = ?
        """, (recording_id,))
        row = cursor.fetchone()

        conn.close()
        return dict(row) if row else None

    def add_summary(self, transcription_id: int) -> int:
        """Add a summary record for a transcription."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO summaries (transcription_id, status)
            VALUES (?, 'pending')
        """, (transcription_id,))

        summary_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return summary_id

    def update_summary(self, summary_id: int, summary_text: str,
                      status: str = "completed") -> None:
        """Update summary with summary text."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE summaries
            SET summary_text = ?, status = ?, summary_length = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (summary_text, status, len(summary_text), summary_id))

        conn.commit()
        conn.close()

    def get_summary(self, transcription_id: int) -> Optional[Dict[str, Any]]:
        """Get summary for a transcription."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM summaries WHERE transcription_id = ?
        """, (transcription_id,))
        row = cursor.fetchone()

        conn.close()
        return dict(row) if row else None

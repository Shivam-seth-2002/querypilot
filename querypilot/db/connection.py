"""Read-only SQLite database connection management with timeout guardrails."""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from querypilot.config import settings


class TimedCursor(sqlite3.Cursor):
    """Cursor that resets query start time on each statement execution."""
    def execute(self, *args, **kwargs):
        if hasattr(self.connection, "_query_start"):
            self.connection._query_start = time.time()
        return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        if hasattr(self.connection, "_query_start"):
            self.connection._query_start = time.time()
        return super().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        if hasattr(self.connection, "_query_start"):
            self.connection._query_start = time.time()
        return super().executescript(*args, **kwargs)


class TimedConnection(sqlite3.Connection):
    """Connection that tracks per-query execution timeouts."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query_start = time.time()
        self._timeout = settings.query_timeout_seconds

    def cursor(self, factory=TimedCursor):
        return super().cursor(factory=factory)

    def execute(self, *args, **kwargs):
        self._query_start = time.time()
        return super().execute(*args, **kwargs)


def get_readonly_connection(
    db_path: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
) -> sqlite3.Connection:
    """Open a strictly read-only SQLite connection.

    Enforces:
    1. URI read-only mode (?mode=ro)
    2. PRAGMA query_only = ON;
    3. progress_handler timeout abort
    """
    target_path = Path(db_path or settings.db_path).resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"Database file not found: {target_path}")

    # Use forward slashes in URI mode
    posix_path = target_path.as_posix()
    uri = f"file:{posix_path}?mode=ro"

    conn = sqlite3.connect(uri, uri=True, check_same_thread=False, factory=TimedConnection)
    conn.execute("PRAGMA query_only = ON;")

    # Progress handler for query timeout
    timeout = timeout_seconds if timeout_seconds is not None else settings.query_timeout_seconds
    conn._timeout = timeout
    if timeout and timeout > 0:
        def timeout_handler() -> int:
            if time.time() - conn._query_start > conn._timeout:
                return 1  # Non-zero return aborts query with OperationalError: interrupted
            return 0

        # Called every 1000 SQLite VM instructions
        conn.set_progress_handler(timeout_handler, 1000)

    return conn


@contextmanager
def readonly_connection(
    db_path: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for safe read-only database connections."""
    conn = get_readonly_connection(db_path=db_path, timeout_seconds=timeout_seconds)
    try:
        yield conn
    finally:
        conn.close()


def get_app_log_connection(log_db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a writable connection for the separate application log database."""
    target_path = Path(log_db_path or settings.app_log_db_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), check_same_thread=False)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS query_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        question TEXT NOT NULL,
        intent TEXT NOT NULL,
        retrieved_tables TEXT,
        sql TEXT,
        row_count INTEGER,
        execution_ms REAL,
        success INTEGER NOT NULL,
        error TEXT
    )
    """)
    conn.commit()
    return conn

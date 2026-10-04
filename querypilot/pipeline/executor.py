"""SQL execution engine executing queries against read-only SQLite database."""

import time
from typing import Any, List, Optional
import pandas as pd
from pydantic import BaseModel, Field

from querypilot.config import settings
from querypilot.db.connection import get_readonly_connection


class ExecutionResult(BaseModel):
    """Result of executing a validated SQL query."""
    columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: int = 0
    execution_ms: float = 0.0
    error: Optional[str] = None
    success: bool = True

    def to_dataframe(self) -> pd.DataFrame:
        """Convert rows and columns back into a pandas DataFrame."""
        if not self.columns:
            return pd.DataFrame()
        return pd.DataFrame(self.rows, columns=self.columns)


class SQLExecutor:
    """Executes validated SQL queries against read-only SQLite database."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.db_path

    def run(self, sql: str, timeout_seconds: Optional[int] = None) -> ExecutionResult:
        """Run SQL query safely in read-only mode and return structured results."""
        conn = get_readonly_connection(
            db_path=self.db_path,
            timeout_seconds=timeout_seconds or settings.query_timeout_seconds,
        )

        start_time = time.perf_counter()
        try:
            # Use pandas read_sql_query for clean typed columnar results
            df = pd.read_sql_query(sql, conn)
            execution_ms = round((time.perf_counter() - start_time) * 1000, 2)

            columns = list(df.columns)
            # Convert NaN/NaT to None for clean JSON serialization
            df_clean = df.where(pd.notnull(df), None)
            rows = df_clean.values.tolist()

            return ExecutionResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_ms=execution_ms,
                success=True,
                error=None,
            )
        except Exception as e:
            execution_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return ExecutionResult(
                columns=[],
                rows=[],
                row_count=0,
                execution_ms=execution_ms,
                success=False,
                error=str(e),
            )
        finally:
            conn.close()

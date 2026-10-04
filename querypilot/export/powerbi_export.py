"""Power BI CSV export manager for QueryPilot query results and operational logs."""

from datetime import datetime, timezone
import re
from pathlib import Path
from typing import Optional, Tuple
import pandas as pd
import sqlite3

from querypilot.config import settings


def slugify(text: str) -> str:
    """Convert text into a safe file slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40].strip("_") or "export"


class PowerBIExporter:
    """Handles exporting dataframes and query logs to CSV format for Power BI Desktop."""

    def __init__(self, exports_dir: Optional[str] = None):
        self.exports_dir = Path(exports_dir or settings.exports_path).resolve()
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def export_dataframe(
        self, df: pd.DataFrame, question_or_name: str
    ) -> Tuple[Path, Path]:
        """Export DataFrame to a timestamped CSV and a 'latest_<slug>.csv' file.

        Returns:
            Tuple of (timestamped_path, latest_path)
        """
        slug = slugify(question_or_name)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        timestamped_file = self.exports_dir / f"{timestamp}_{slug}.csv"
        latest_file = self.exports_dir / f"latest_{slug}.csv"

        # Write CSVs
        df.to_csv(timestamped_file, index=False, encoding="utf-8")
        df.to_csv(latest_file, index=False, encoding="utf-8")

        return timestamped_file, latest_file

    def export_query_log(self, app_log_db_path: Optional[str] = None) -> Path:
        """Export the query_log table from app_log.db to data/exports/query_log.csv."""
        log_db = Path(app_log_db_path or settings.app_log_db_path).resolve()
        output_file = self.exports_dir / "query_log.csv"

        if not log_db.exists():
            # Create empty query log CSV with standard headers
            empty_df = pd.DataFrame(
                columns=[
                    "id", "timestamp", "question", "intent", "retrieved_tables",
                    "sql", "row_count", "execution_ms", "success", "error"
                ]
            )
            empty_df.to_csv(output_file, index=False, encoding="utf-8")
            return output_file

        conn = sqlite3.connect(str(log_db))
        try:
            df = pd.read_sql_query("SELECT * FROM query_log ORDER BY id DESC", conn)
            df.to_csv(output_file, index=False, encoding="utf-8")
            return output_file
        finally:
            conn.close()

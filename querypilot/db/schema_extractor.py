"""Schema extraction from SQLite database using PRAGMA and system catalog."""

import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from querypilot.config import settings
from querypilot.db.connection import get_readonly_connection


class ColumnInfo(BaseModel):
    """Metadata for a single database column."""
    name: str
    data_type: str
    is_pk: bool = False
    not_null: bool = False
    default_value: Optional[Any] = None
    sample_values: List[str] = Field(default_factory=list)


class ForeignKeyInfo(BaseModel):
    """Metadata for a foreign key relationship."""
    from_column: str
    to_table: str
    to_column: str


class TableInfo(BaseModel):
    """Metadata for a database table."""
    table_name: str
    row_count: int = 0
    columns: List[ColumnInfo] = Field(default_factory=list)
    foreign_keys: List[ForeignKeyInfo] = Field(default_factory=list)
    primary_keys: List[str] = Field(default_factory=list)

    @property
    def column_names(self) -> List[str]:
        return [col.name for col in self.columns]


class DatabaseSchema(BaseModel):
    """Complete extracted database schema with hash for change detection."""
    tables: Dict[str, TableInfo] = Field(default_factory=dict)
    schema_hash: str = ""

    def get_table(self, name: str) -> Optional[TableInfo]:
        return self.tables.get(name)


class SchemaExtractor:
    """Extracts schema, relationships, and representative sample values from SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.db_path

    def extract(self) -> DatabaseSchema:
        """Extract full schema from the database."""
        conn = get_readonly_connection(self.db_path)
        try:
            cursor = conn.cursor()

            # Retrieve all user tables (exclude sqlite internal tables)
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)
            table_names = [row[0] for row in cursor.fetchall()]

            tables: Dict[str, TableInfo] = {}

            for tbl in table_names:
                # 1. Row count
                cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
                row_count = cursor.fetchone()[0]

                # 2. Table info (columns, PKs)
                cursor.execute(f"PRAGMA table_info({tbl})")
                col_rows = cursor.fetchall()

                columns: List[ColumnInfo] = []
                pks: List[str] = []

                for col_row in col_rows:
                    # cid, name, type, notnull, dflt_value, pk
                    _, c_name, c_type, notnull, dflt_val, is_pk = col_row
                    if is_pk:
                        pks.append(c_name)

                    # Extract sample values for low-cardinality or categorical columns
                    sample_vals: List[str] = []
                    is_sensitive = any(
                        sens.lower() == f"{tbl}.{c_name}".lower() or sens.lower() == c_name.lower()
                        for sens in settings.sensitive_columns
                    )

                    if not is_sensitive and not is_pk and not c_name.endswith("_id"):
                        try:
                            cursor.execute(
                                f"SELECT DISTINCT {c_name} FROM {tbl} "
                                f"WHERE {c_name} IS NOT NULL LIMIT 4"
                            )
                            distinct_rows = cursor.fetchall()
                            if len(distinct_rows) <= 3:
                                sample_vals = [str(r[0]) for r in distinct_rows]
                            elif c_type.upper() in ("TEXT", "VARCHAR", ""):
                                # For text columns, take top 3 samples
                                sample_vals = [str(r[0]) for r in distinct_rows[:3]]
                        except Exception:
                            sample_vals = []

                    columns.append(
                        ColumnInfo(
                            name=c_name,
                            data_type=c_type or "TEXT",
                            is_pk=bool(is_pk),
                            not_null=bool(notnull),
                            default_value=dflt_val,
                            sample_values=sample_vals,
                        )
                    )

                # 3. Foreign key list
                cursor.execute(f"PRAGMA foreign_key_list({tbl})")
                fk_rows = cursor.fetchall()
                foreign_keys: List[ForeignKeyInfo] = []
                for fk_row in fk_rows:
                    # id, seq, table, from, to, on_update, on_delete, match
                    _, _, to_table, from_col, to_col, _, _, _ = fk_row
                    foreign_keys.append(
                        ForeignKeyInfo(
                            from_column=from_col,
                            to_table=to_table,
                            to_column=to_col,
                        )
                    )

                tables[tbl] = TableInfo(
                    table_name=tbl,
                    row_count=row_count,
                    columns=columns,
                    foreign_keys=foreign_keys,
                    primary_keys=pks,
                )

            # Compute schema hash
            schema_representation = []
            for t_name in sorted(tables.keys()):
                t_info = tables[t_name]
                col_repr = [f"{c.name}:{c.data_type}" for c in t_info.columns]
                fk_repr = [f"{fk.from_column}->{fk.to_table}.{fk.to_column}" for fk in t_info.foreign_keys]
                schema_representation.append(f"{t_name}({','.join(col_repr)})[{','.join(fk_repr)}]")

            hash_str = hashlib.sha256(";".join(schema_representation).encode("utf-8")).hexdigest()

            return DatabaseSchema(tables=tables, schema_hash=hash_str)
        finally:
            conn.close()

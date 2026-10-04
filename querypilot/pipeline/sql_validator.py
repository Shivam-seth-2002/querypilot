"""Read-only SQL validator implementing defense-in-depth security guardrails."""

import re
from typing import List, Optional, Set
import sqlglot
import sqlglot.expressions as exp

from querypilot.config import settings
from querypilot.models import ValidationResult

# Disallowed SQLGlot AST node classes
DISALLOWED_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Pragma,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)

# Dangerous keywords/commands caught via pattern matching
DANGEROUS_PATTERNS = [
    r"\battach\s+database\b",
    r"\bdetach\s+database\b",
    r"\bload_extension\b",
    r"\bpragma\b",
    r"\bvacuum\b",
    r"\breindex\b",
]

DEFAULT_ALLOWED_TABLES = {
    "customers",
    "products",
    "orders",
    "order_items",
    "returns",
    "warehouses",
    "inventory",
    "marketing_campaigns",
    "employees",
}


class SQLValidator:
    """Validates that SQL queries are strictly read-only, schema-compliant, and safe."""

    def __init__(
        self,
        allowed_tables: Optional[Set[str]] = None,
        sensitive_columns: Optional[List[str]] = None,
        default_limit: Optional[int] = None,
        max_limit: Optional[int] = None,
    ):
        self.allowed_tables = {t.lower() for t in (allowed_tables or DEFAULT_ALLOWED_TABLES)}
        self.sensitive_columns = [
            c.lower() for c in (sensitive_columns or settings.sensitive_columns)
        ]
        self.default_limit = default_limit or settings.default_row_limit
        self.max_limit = max_limit or settings.max_row_limit

    def validate(self, sql: str) -> ValidationResult:
        """Validate, sanitize, and enforce LIMIT on SQL query."""
        errors: List[str] = []

        if not sql or not sql.strip():
            return ValidationResult(is_valid=False, errors=["SQL query is empty"])

        # Clean string
        clean_sql = sql.strip()

        # Remove trailing semicolons before parsing
        clean_sql = re.sub(r";+\s*$", "", clean_sql)

        # 1. Regex check for explicit dangerous commands
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, clean_sql, re.IGNORECASE):
                errors.append(f"Forbidden command detected matching pattern: {pattern}")

        if errors:
            return ValidationResult(is_valid=False, errors=errors)

        # 2. Parse with sqlglot for SQLite dialect
        try:
            statements = sqlglot.parse(clean_sql, read="sqlite")
        except Exception as e:
            return ValidationResult(
                is_valid=False, errors=[f"SQL syntax parse error: {str(e)}"]
            )

        # Filter out empty statements (like comments or empty lines)
        non_empty_stmts = [s for s in statements if s is not None]

        if not non_empty_stmts:
            return ValidationResult(is_valid=False, errors=["No executable SQL statement found"])

        # Multiple statements separated by semicolon are strictly prohibited
        if len(non_empty_stmts) > 1:
            return ValidationResult(
                is_valid=False,
                errors=["Multiple SQL statements are strictly prohibited"],
            )

        stmt = non_empty_stmts[0]

        # 3. Must be a SELECT query or UNION of SELECT queries
        if not isinstance(stmt, (exp.Select, exp.Union)):
            return ValidationResult(
                is_valid=False,
                errors=[f"Only SELECT queries are allowed. Found: {type(stmt).__name__}"],
            )

        # 4. Check for disallowed AST nodes anywhere in the query
        for disallowed_type in DISALLOWED_NODE_TYPES:
            for node in stmt.find_all(disallowed_type):
                errors.append(f"Forbidden SQL operation: {type(node).__name__}")

        if errors:
            return ValidationResult(is_valid=False, errors=errors)

        # 5. Extract CTE aliases so they are not rejected by the table whitelist
        cte_aliases: Set[str] = set()
        for cte in stmt.find_all(exp.CTE):
            alias = cte.alias_or_name.lower()
            if alias:
                cte_aliases.add(alias)

        # 6. Table Whitelist Check
        referenced_tables: Set[str] = set()
        for table_node in stmt.find_all(exp.Table):
            t_name = table_node.name.lower()
            # If the table is a CTE alias, ignore it in the base table whitelist check
            if t_name not in cte_aliases:
                referenced_tables.add(t_name)
                if t_name not in self.allowed_tables:
                    errors.append(
                        f"Table '{t_name}' is not in the allowed schema whitelist"
                    )

        # 7. Sensitive Column & Star Check
        sensitive_bare_cols = {col.split(".")[-1] for col in self.sensitive_columns}
        tables_with_sensitive_cols = {
            col.split(".")[0] for col in self.sensitive_columns if "." in col
        }

        # Check explicit column nodes
        for col_node in stmt.find_all(exp.Column):
            col_name = col_node.name.lower()
            col_tbl = col_node.table.lower() if col_node.table else None

            # Check full qualified "table.column"
            if col_tbl and f"{col_tbl}.{col_name}" in self.sensitive_columns:
                errors.append(
                    f"Access to sensitive column '{col_tbl}.{col_name}' is forbidden"
                )
            # Check bare column name matching sensitive columns
            elif col_name in sensitive_bare_cols:
                errors.append(
                    f"Access to sensitive column '{col_name}' is forbidden"
                )

        # Check for star '*' on tables containing sensitive columns
        for star_node in stmt.find_all(exp.Star):
            parent = star_node.parent
            # Check if star is qualified like `employees.*`
            if isinstance(parent, exp.Column) and parent.table:
                if parent.table.lower() in tables_with_sensitive_cols:
                    errors.append(
                        f"Wildcard selection '*' is forbidden on table '{parent.table}' with sensitive columns"
                    )
            else:
                # Unqualified star `SELECT *` while querying a table with sensitive columns
                for t in referenced_tables:
                    if t in tables_with_sensitive_cols:
                        errors.append(
                            f"Wildcard selection '*' is forbidden when querying table '{t}' containing sensitive columns. Please specify columns explicitly."
                        )

        if errors:
            return ValidationResult(is_valid=False, errors=errors)

        # 8. Enforce LIMIT guardrail
        sanitized_stmt = stmt.copy()
        limit_node = sanitized_stmt.args.get("limit")

        if limit_node is None:
            # Add default limit
            sanitized_stmt.limit(self.default_limit, copy=False)
        else:
            try:
                # Extract numeric limit value
                current_limit = int(limit_node.expression.this)
                if current_limit > self.max_limit:
                    limit_node.set("expression", exp.Literal.number(self.max_limit))
                elif current_limit <= 0:
                    limit_node.set("expression", exp.Literal.number(self.default_limit))
            except Exception:
                # Fallback to capping
                limit_node.set("expression", exp.Literal.number(self.max_limit))

        sanitized_sql = sanitized_stmt.sql(dialect="sqlite")

        return ValidationResult(
            is_valid=True,
            sanitized_sql=sanitized_sql,
            errors=[],
        )

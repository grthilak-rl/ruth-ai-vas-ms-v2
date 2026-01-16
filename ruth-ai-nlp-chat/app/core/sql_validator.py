"""SQL validation and sanitization for chat queries.

Security layer to ensure only safe read-only queries are executed.
"""

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# Dangerous SQL patterns (case-insensitive)
DANGEROUS_PATTERNS = [
    r"\bDROP\b",
    r"\bDELETE\b",
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bALTER\b",
    r"\bCREATE\b",
    r"\bTRUNCATE\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bEXEC\b",
    r"\bEXECUTE\b",
    r"\bCALL\b",
    r"--",  # SQL comments
    r"/\*",  # Block comments
    r";.*SELECT",  # Multiple statements
    r"\bINTO\s+\w",  # SELECT INTO
    r"\bLOAD\b",
    r"\bCOPY\b",
    r"\bPG_",  # PostgreSQL system functions
    r"\bINFORMATION_SCHEMA\b",
]

# Compile patterns for efficiency
COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]


@dataclass
class ValidationResult:
    """Result of SQL validation."""

    is_valid: bool
    error: str | None = None
    sanitized_sql: str | None = None


class SQLValidator:
    """Validates and sanitizes SQL queries for chat functionality."""

    def __init__(
        self,
        allowed_tables: list[str],
        max_result_rows: int = 100,
    ) -> None:
        self._allowed_tables = set(t.lower() for t in allowed_tables)
        self._max_result_rows = max_result_rows

    def validate(self, sql: str) -> ValidationResult:
        """Validate SQL query for safety."""
        if not sql or not sql.strip():
            return ValidationResult(is_valid=False, error="Empty query")

        sql_clean = sql.strip()
        sql_upper = sql_clean.upper()

        # 1. Must be a SELECT statement
        if not sql_upper.startswith("SELECT"):
            return ValidationResult(
                is_valid=False,
                error="Only SELECT statements are allowed",
            )

        # 2. Check for dangerous patterns
        for pattern in COMPILED_PATTERNS:
            if pattern.search(sql_clean):
                logger.warning(
                    "Blocked dangerous SQL pattern",
                    pattern=pattern.pattern,
                    query=sql_clean[:200],
                )
                return ValidationResult(
                    is_valid=False,
                    error="Query contains prohibited SQL patterns",
                )

        # 3. Check for multiple statements
        if ";" in sql_clean.rstrip(";"):
            return ValidationResult(
                is_valid=False,
                error="Multiple statements not allowed",
            )

        # 4. Validate table names
        tables_in_query = self._extract_table_names(sql_clean)
        for table in tables_in_query:
            if table.lower() not in self._allowed_tables:
                return ValidationResult(
                    is_valid=False,
                    error=f"Table '{table}' is not accessible",
                )

        # 5. Add LIMIT if not present
        sanitized = self._add_limit_if_missing(sql_clean)

        return ValidationResult(
            is_valid=True,
            sanitized_sql=sanitized,
        )

    def _extract_table_names(self, sql: str) -> set[str]:
        """Extract table names from SQL query."""
        tables = set()
        from_pattern = re.compile(r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
        join_pattern = re.compile(r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
        tables.update(m.group(1) for m in from_pattern.finditer(sql))
        tables.update(m.group(1) for m in join_pattern.finditer(sql))
        return tables

    def _add_limit_if_missing(self, sql: str) -> str:
        """Add LIMIT clause if not present."""
        if "LIMIT" not in sql.upper():
            sql = sql.rstrip(";")
            sql = f"{sql} LIMIT {self._max_result_rows}"
        return sql

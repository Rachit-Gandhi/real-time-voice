from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import create_engine, inspect as sa_inspect, text

logger = logging.getLogger(__name__)

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|MERGE|REPLACE|CALL|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)

MAX_ROWS = 50

_engine_cache: dict[str, Any] = {}


def _get_engine(database_url: str) -> Any:
    if database_url not in _engine_cache:
        connect_args = {"timeout": 10} if "sqlite" in database_url else {}
        _engine_cache[database_url] = create_engine(database_url, connect_args=connect_args)
    return _engine_cache[database_url]


class SQLQueryEngine:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._schema_cache: dict[str, list[dict]] | None = None

    @property
    def _engine(self) -> Any:
        return _get_engine(self.database_url)

    def introspect_schema(self) -> dict[str, list[dict]]:
        if self._schema_cache is not None:
            return self._schema_cache
        inspector = sa_inspect(self._engine)
        schema: dict[str, list[dict]] = {}
        for table in inspector.get_table_names():
            cols = inspector.get_columns(table)
            schema[table] = [{"name": c["name"], "type": str(c["type"])} for c in cols]
        self._schema_cache = schema
        return schema

    def schema_as_prompt(self) -> str:
        schema = self.introspect_schema()
        lines: list[str] = []
        for table, cols in schema.items():
            col_str = ", ".join(f"{c['name']} ({c['type']})" for c in cols)
            lines.append(f"  {table}({col_str})")
        return "Tables:\n" + "\n".join(lines)

    def is_safe(self, sql: str) -> tuple[bool, str]:
        stripped = sql.strip()
        if not stripped.upper().startswith("SELECT"):
            return False, "Only SELECT queries are allowed."
        if _FORBIDDEN.search(stripped):
            return False, "Query contains a forbidden keyword (INSERT/UPDATE/DELETE/DDL)."
        return True, ""

    def add_limit(self, sql: str) -> str:
        sql = sql.rstrip().rstrip(";")
        if not _LIMIT_RE.search(sql):
            sql = f"SELECT * FROM ({sql}) _q LIMIT {MAX_ROWS}"
        return sql

    def execute(self, sql: str) -> list[dict[str, Any]]:
        safe, reason = self.is_safe(sql)
        if not safe:
            raise ValueError(f"Rejected: {reason}")
        final_sql = self.add_limit(sql)
        with self._engine.connect() as conn:
            result = conn.execute(text(final_sql))
            return [dict(row) for row in result.mappings().fetchmany(MAX_ROWS)]

    def generate_sql(self, question: str) -> str:
        import os

        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for SQL generation.")

        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=model, temperature=0)
        system = (
            "You are a SQL expert. Given a database schema and a question, write one SELECT query. "
            "Rules: SELECT only, no INSERT/UPDATE/DELETE/DDL, no markdown fences, no explanation. "
            "Return only the raw SQL."
        )
        response = llm.invoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": f"{self.schema_as_prompt()}\n\nQuestion: {question}"},
            ]
        )
        return response.content.strip().strip("```sql").strip("```").strip()

    def answer_question(self, question: str) -> dict[str, Any]:
        try:
            sql = self.generate_sql(question)
        except Exception as exc:
            logger.warning("SQL generation failed: %s", exc)
            return {"error": str(exc)}

        try:
            rows = self.execute(sql)
            return {"sql": sql, "rows": rows, "row_count": len(rows)}
        except ValueError as exc:
            return {"error": str(exc), "sql": sql}
        except Exception as exc:
            logger.warning("SQL execution failed: %s", exc)
            return {"error": f"Execution error: {exc}", "sql": sql}

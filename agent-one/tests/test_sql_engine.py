"""Tests for SQLQueryEngine: schema introspection, safe execution, rejection of writes."""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest


@pytest.fixture
def db_url(tmp_path):
    """SQLite test database with a products table."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, price REAL NOT NULL)"
    )
    conn.execute("INSERT INTO products VALUES (1, 'Widget', 9.99)")
    conn.execute("INSERT INTO products VALUES (2, 'Gadget', 19.99)")
    conn.execute("INSERT INTO products VALUES (3, 'Doohickey', 4.99)")
    conn.execute(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, product_id INTEGER, qty INTEGER)"
    )
    conn.execute("INSERT INTO orders VALUES (1, 1, 2)")
    conn.commit()
    conn.close()
    return f"sqlite:///{db_path}"


@pytest.fixture
def engine(db_url):
    from app.database.sql_engine import SQLQueryEngine
    return SQLQueryEngine(db_url)


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

def test_introspect_schema_returns_tables(engine):
    schema = engine.introspect_schema()
    assert "products" in schema
    assert "orders" in schema


def test_introspect_schema_columns(engine):
    schema = engine.introspect_schema()
    col_names = [c["name"] for c in schema["products"]]
    assert "id" in col_names
    assert "name" in col_names
    assert "price" in col_names


def test_schema_as_prompt_contains_table_names(engine):
    prompt = engine.schema_as_prompt()
    assert "products" in prompt
    assert "orders" in prompt


# ---------------------------------------------------------------------------
# Safe execution
# ---------------------------------------------------------------------------

def test_execute_select_returns_rows(engine):
    rows = engine.execute("SELECT * FROM products")
    assert len(rows) == 3
    assert rows[0]["name"] in ("Widget", "Gadget", "Doohickey")


def test_execute_select_with_where(engine):
    rows = engine.execute("SELECT * FROM products WHERE price < 10.0")
    assert len(rows) == 2
    names = {r["name"] for r in rows}
    assert "Widget" in names
    assert "Doohickey" in names


def test_add_limit_appended_when_absent(engine):
    sql = engine.add_limit("SELECT * FROM products")
    assert "LIMIT" in sql.upper()


def test_add_limit_not_doubled_when_present(engine):
    sql = engine.add_limit("SELECT * FROM products LIMIT 5")
    assert sql.upper().count("LIMIT") == 1


def test_add_limit_strips_trailing_semicolon(engine):
    sql = engine.add_limit("SELECT 1;")
    assert not sql.rstrip().endswith(";")


# ---------------------------------------------------------------------------
# Safety: write-query rejection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_sql", [
    "INSERT INTO products VALUES (99, 'hack', 0.01)",
    "UPDATE products SET price = 0 WHERE id = 1",
    "DELETE FROM products WHERE id = 1",
    "DROP TABLE products",
    "CREATE TABLE evil (x TEXT)",
    "ALTER TABLE products ADD COLUMN secret TEXT",
    "TRUNCATE TABLE products",
    "select 1; DELETE FROM products",
])
def test_is_safe_rejects_write_queries(engine, bad_sql):
    safe, reason = engine.is_safe(bad_sql)
    assert not safe, f"Expected rejection for: {bad_sql!r}"
    assert reason


@pytest.mark.parametrize("bad_sql", [
    "INSERT INTO products VALUES (99, 'hack', 0.01)",
    "DELETE FROM products",
    "DROP TABLE products",
])
def test_execute_raises_on_write_query(engine, bad_sql):
    with pytest.raises(ValueError, match="Rejected"):
        engine.execute(bad_sql)


def test_is_safe_accepts_plain_select(engine):
    safe, reason = engine.is_safe("SELECT id, name FROM products WHERE id = 1")
    assert safe
    assert reason == ""


def test_is_safe_accepts_select_with_join(engine):
    safe, _ = engine.is_safe(
        "SELECT p.name, o.qty FROM products p JOIN orders o ON p.id = o.product_id"
    )
    assert safe


# ---------------------------------------------------------------------------
# SQLite-backed store round-trip
# ---------------------------------------------------------------------------

def test_sqlite_store_persists_and_reloads(tmp_path):
    from app.retrieval.store import SQLiteVectorStore
    from app.retrieval.pipeline import WebsiteChunk

    db = str(tmp_path / "chunks.db")
    store1 = SQLiteVectorStore(db_path=db)
    chunk = WebsiteChunk(
        chunk_id="c1", website_id="site-a", url="https://a.com", title="A", content="hello world"
    )
    store1.add_chunks([chunk])
    assert store1.chunk_count == 1

    # Reload from same DB
    store2 = SQLiteVectorStore(db_path=db)
    assert store2.chunk_count == 1
    results = store2.search("hello", website_id="site-a", top_k=1)
    assert results[0].chunk_id == "c1"


def test_sqlite_store_clear_website(tmp_path):
    from app.retrieval.store import SQLiteVectorStore
    from app.retrieval.pipeline import WebsiteChunk

    db = str(tmp_path / "chunks.db")
    store = SQLiteVectorStore(db_path=db)
    store.add_chunks([
        WebsiteChunk(chunk_id="c1", website_id="site-a", url="u1", title="T1", content="foo"),
        WebsiteChunk(chunk_id="c2", website_id="site-b", url="u2", title="T2", content="bar"),
    ])
    assert store.chunk_count == 2

    store.clear_website("site-a")
    assert store.chunk_count == 1
    assert store.has_website("site-b")
    assert not store.has_website("site-a")

    # Reload confirms DB was updated too
    store2 = SQLiteVectorStore(db_path=db)
    assert store2.chunk_count == 1

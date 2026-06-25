"""SQLite store for L1 support — companies, sites, applications, tickets."""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app import config as cfg

_lock = threading.Lock()


def _db_path() -> Path:
    return Path(cfg.L1_TICKETS_DB)


@contextmanager
def _conn():
    with _lock:
        con = sqlite3.connect(str(_db_path()))
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


# ── Schema + seed ──────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS companies (
    code         TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    support_email TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sites (
    site_id      TEXT PRIMARY KEY,
    company_code TEXT NOT NULL REFERENCES companies(code),
    name         TEXT NOT NULL,
    city         TEXT NOT NULL,
    state        TEXT NOT NULL,
    postal_code  TEXT NOT NULL,
    country      TEXT NOT NULL DEFAULT 'US'
);

CREATE TABLE IF NOT EXISTS applications (
    app_id            TEXT PRIMARY KEY,
    company_code      TEXT NOT NULL REFERENCES companies(code),
    product_reference TEXT NOT NULL,
    name              TEXT NOT NULL,
    support_email     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id         TEXT PRIMARY KEY,
    customer_code     TEXT NOT NULL,
    site_id           TEXT,
    product_reference TEXT NOT NULL,
    application_name  TEXT NOT NULL,
    company_name      TEXT NOT NULL,
    issue_description TEXT NOT NULL,
    contact_name      TEXT,
    contact_email     TEXT,
    employee_number   TEXT,
    status            TEXT NOT NULL DEFAULT 'open',
    email_sent        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);
"""

_SEED = """
INSERT OR IGNORE INTO companies VALUES
  ('SAMSUNG',   'Samsung Electronics',    'support@samsung-service.com'),
  ('PANASONIC', 'Panasonic Corporation',  'support@panasonic-service.com'),
  ('HAVELLS',   'Havells India Ltd',      'support@havells-service.com');

INSERT OR IGNORE INTO sites VALUES
  ('SAM-SEA', 'SAMSUNG',   'Samsung Seattle HQ',          'Seattle',       'WA', '98101', 'US'),
  ('SAM-NYC', 'SAMSUNG',   'Samsung New York',             'New York',      'NY', '10001', 'US'),
  ('SAM-DAL', 'SAMSUNG',   'Samsung Dallas',               'Dallas',        'TX', '75201', 'US'),
  ('PAN-CHI', 'PANASONIC', 'Panasonic Chicago',            'Chicago',       'IL', '60601', 'US'),
  ('PAN-HOU', 'PANASONIC', 'Panasonic Houston',            'Houston',       'TX', '77001', 'US'),
  ('PAN-LAX', 'PANASONIC', 'Panasonic Los Angeles',        'Los Angeles',   'CA', '90001', 'US'),
  ('HAV-ATL', 'HAVELLS',   'Havells Atlanta',              'Atlanta',       'GA', '30301', 'US'),
  ('HAV-DFW', 'HAVELLS',   'Havells Dallas-Fort Worth',    'Dallas',        'TX', '75001', 'US'),
  ('HAV-PHX', 'HAVELLS',   'Havells Phoenix',              'Phoenix',       'AZ', '85001', 'US');

INSERT OR IGNORE INTO applications VALUES
  ('SAMSUNG-SVP', 'SAMSUNG',   'SAMSUNG-SVP', 'SmartView Portal',   'svp-support@samsung-service.com'),
  ('SAMSUNG-FSA', 'SAMSUNG',   'SAMSUNG-FSA', 'Field Service App',  'fsa-support@samsung-service.com'),
  ('PAN-RM',      'PANASONIC', 'PAN-RM',      'Remote Monitor',     'rm-support@panasonic-service.com'),
  ('PAN-AT',      'PANASONIC', 'PAN-AT',      'Asset Tracker',      'at-support@panasonic-service.com'),
  ('HAVELLS-ED',  'HAVELLS',   'HAVELLS-ED',  'Energy Dashboard',   'ed-support@havells-service.com'),
  ('HAVELLS-SP',  'HAVELLS',   'HAVELLS-SP',  'Support Portal',     'sp-support@havells-service.com');
"""


def init_db() -> None:
    with _conn() as con:
        con.executescript(_DDL)
        con.executescript(_SEED)
        # Migrate: add employee_number if the column doesn't exist yet
        try:
            con.execute("ALTER TABLE tickets ADD COLUMN employee_number TEXT")
        except sqlite3.OperationalError:
            pass


# ── Query helpers ──────────────────────────────────────────────────────────────

def all_companies() -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute("SELECT * FROM companies")]


def all_applications() -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT a.*, c.name AS company_name FROM applications a "
            "JOIN companies c ON c.code = a.company_code"
        )]


def apps_for_company(company_code: str) -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM applications WHERE company_code = ?", (company_code,)
        )]


def find_site(company_code: str, hint: str | None = None) -> dict | None:
    """Return first site for company, optionally filtering by city/name hint."""
    with _conn() as con:
        if hint:
            h = f"%{hint.lower()}%"
            row = con.execute(
                "SELECT * FROM sites WHERE company_code = ? "
                "AND (LOWER(name) LIKE ? OR LOWER(city) LIKE ?)",
                (company_code, h, h),
            ).fetchone()
            if row:
                return dict(row)
        row = con.execute(
            "SELECT * FROM sites WHERE company_code = ? LIMIT 1", (company_code,)
        ).fetchone()
        return dict(row) if row else None


def insert_ticket(ticket: dict) -> None:
    with _conn() as con:
        con.execute(
            """INSERT INTO tickets
               (ticket_id, customer_code, site_id, product_reference,
                application_name, company_name, issue_description,
                contact_name, contact_email, employee_number,
                status, email_sent, created_at)
               VALUES (:ticket_id, :customer_code, :site_id, :product_reference,
                       :application_name, :company_name, :issue_description,
                       :contact_name, :contact_email, :employee_number,
                       :status, :email_sent, :created_at)""",
            ticket,
        )


def mark_email_sent(ticket_id: str) -> None:
    with _conn() as con:
        con.execute("UPDATE tickets SET email_sent = 1 WHERE ticket_id = ?", (ticket_id,))


def get_ticket(ticket_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        return dict(row) if row else None


def all_tickets() -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM tickets ORDER BY created_at DESC"
        )]


def find_tickets_by_employee(employee_number: str) -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM tickets WHERE employee_number = ? ORDER BY created_at DESC",
            (employee_number,)
        )]


def update_ticket_status(ticket_id: str, status: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE tickets SET status = ? WHERE ticket_id = ?",
            (status, ticket_id),
        )


# Run schema + seed on import
init_db()

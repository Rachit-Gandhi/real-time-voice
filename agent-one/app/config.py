import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=False)

WEBSITE_START_URL: str = os.getenv("WEBSITE_START_URL", "")
WEBSITE_MAX_PAGES: int = int(os.getenv("WEBSITE_MAX_PAGES", "10"))
WEBSITE_ALLOWED_DOMAIN: str = os.getenv("WEBSITE_ALLOWED_DOMAIN", "")
INDEX_DB_PATH: str = os.getenv("INDEX_DB_PATH", "agent_one_index.db")
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# SMTP — leave blank to disable email
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM: str = os.getenv("SMTP_FROM", "")

L1_TICKETS_DB: str = os.getenv("L1_TICKETS_DB", "l1_tickets.db")

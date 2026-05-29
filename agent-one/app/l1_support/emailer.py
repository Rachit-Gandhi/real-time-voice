"""SMTP email sender for L1 ticket notifications."""
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app import config as cfg

log = logging.getLogger(__name__)


def _enabled() -> bool:
    return bool(cfg.SMTP_HOST and cfg.SMTP_USER and cfg.SMTP_PASSWORD)


def send_ticket_email(
    *,
    to: str,
    ticket_id: str,
    company_name: str,
    application_name: str,
    issue_description: str,
    contact_name: str | None,
    contact_email: str | None,
    site_id: str | None,
) -> bool:
    """Send ticket notification. Returns True on success."""
    if not _enabled():
        log.warning("SMTP not configured — skipping email for ticket %s", ticket_id)
        return False

    subject = f"[Support Ticket {ticket_id}] {company_name} — {application_name}"

    body_html = f"""
<html><body>
<h2>New Support Ticket: {ticket_id}</h2>
<table>
  <tr><td><b>Company</b></td><td>{company_name}</td></tr>
  <tr><td><b>Application</b></td><td>{application_name}</td></tr>
  <tr><td><b>Site ID</b></td><td>{site_id or '—'}</td></tr>
  <tr><td><b>Contact</b></td><td>{contact_name or '—'}</td></tr>
  <tr><td><b>Contact Email</b></td><td>{contact_email or '—'}</td></tr>
</table>
<h3>Issue Description</h3>
<p>{issue_description}</p>
</body></html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg.SMTP_FROM or cfg.SMTP_USER
    msg["To"] = to
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
            server.sendmail(msg["From"], [to], msg.as_string())
        log.info("Ticket email sent to %s for %s", to, ticket_id)
        return True
    except Exception as exc:
        log.error("Failed to send ticket email for %s: %s", ticket_id, exc)
        return False

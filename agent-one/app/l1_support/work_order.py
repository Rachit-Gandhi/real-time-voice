"""Work order creation — maps L1 ticket data to the Batch Open Work Order schema."""
import time
from dataclasses import dataclass, field
from datetime import datetime, UTC

from app.l1_support import db as _db


@dataclass
class WorkOrder:
    # Required
    customer_code: str
    product_reference: str
    # Site
    site_id: str | None = None
    customer_city: str | None = None
    customer_postal_code: str | None = None
    customer_state: str | None = None
    customer_country: str = "US"
    # Contact
    contact_name: str | None = None
    contact_email: str | None = None
    employee_number: str | None = None
    # Meta
    customer_call_number: str = ""
    open_remarks: str = ""
    model: str = ""
    # Derived
    ticket_id: str = field(default_factory=lambda: f"TKT-{int(time.time())}")
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def build_work_order(
    *,
    company_code: str,
    application: dict,
    site: dict | None,
    issue_description: str,
    contact_name: str | None,
    contact_email: str | None,
    employee_number: str | None = None,
) -> WorkOrder:
    wo = WorkOrder(
        customer_code=company_code,
        product_reference=application["product_reference"],
        open_remarks=issue_description,
        model=application["product_reference"],
        contact_name=contact_name,
        contact_email=contact_email,
        employee_number=employee_number,
    )

    if site:
        wo.site_id = site["site_id"]
        wo.customer_city = site["city"]
        wo.customer_state = site["state"]
        wo.customer_postal_code = site["postal_code"]
        wo.customer_country = site.get("country", "US")
    else:
        wo.customer_city = "Unknown"
        wo.customer_postal_code = "00000"

    return wo


def persist_work_order(wo: WorkOrder, company: dict, application: dict) -> str:
    """Save work order to SQLite. Returns ticket_id."""
    _db.insert_ticket({
        "ticket_id": wo.ticket_id,
        "customer_code": wo.customer_code,
        "site_id": wo.site_id,
        "product_reference": wo.product_reference,
        "application_name": application["name"],
        "company_name": company["name"],
        "issue_description": wo.open_remarks,
        "contact_name": wo.contact_name,
        "contact_email": wo.contact_email,
        "employee_number": wo.employee_number,
        "status": "open",
        "email_sent": 0,
        "created_at": wo.created_at,
    })
    return wo.ticket_id

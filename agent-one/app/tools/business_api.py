from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


class BusinessApiTools(Protocol):
    def get_customer(self, identifier: str | None = None) -> dict: ...

    def get_order_status(self, order_id: str | None = None) -> dict: ...

    def get_invoice_summary(self, customer_id: str | None = None) -> dict: ...

    def search_appointments(self, customer_id: str | None = None) -> dict: ...


@dataclass
class MockBusinessApiTools:
    customers: dict[str, dict] | None = None
    orders: dict[str, dict] | None = None
    invoices: dict[str, dict] | None = None
    appointments: dict[str, list[dict]] | None = None

    def __post_init__(self) -> None:
        self.customers = self.customers or {
            "cust_123": {
                "customer_id": "cust_123",
                "name": "Demo Customer",
                "email": "demo@example.com",
                "plan": "Professional",
            }
        }
        self.orders = self.orders or {
            "ord_1001": {
                "order_id": "ord_1001",
                "customer_id": "cust_123",
                "status": "in transit",
                "eta": "2026-05-29",
                "latest_note": "Package left the regional facility.",
            }
        }
        self.invoices = self.invoices or {
            "cust_123": {
                "customer_id": "cust_123",
                "open_invoice_count": 1,
                "total_due": 149.0,
                "currency": "USD",
                "next_due_date": "2026-06-01",
            }
        }
        self.appointments = self.appointments or {
            "cust_123": [
                {"slot_id": "slot_1", "starts_at": "2026-05-27T10:00:00", "status": "available"},
                {"slot_id": "slot_2", "starts_at": "2026-05-27T14:30:00", "status": "available"},
            ]
        }

    def get_customer(self, identifier: str | None = None) -> dict:
        customer_id = identifier or "cust_123"
        return {"tool": "get_customer", "data": self.customers.get(customer_id, self.customers["cust_123"])}

    def get_order_status(self, order_id: str | None = None) -> dict:
        resolved_id = order_id or "ord_1001"
        return {"tool": "get_order_status", "data": self.orders.get(resolved_id, self.orders["ord_1001"])}

    def get_invoice_summary(self, customer_id: str | None = None) -> dict:
        resolved_id = customer_id or "cust_123"
        return {"tool": "get_invoice_summary", "data": self.invoices.get(resolved_id, self.invoices["cust_123"])}

    def search_appointments(self, customer_id: str | None = None) -> dict:
        resolved_id = customer_id or "cust_123"
        return {
            "tool": "search_appointments",
            "data": {
                "customer_id": resolved_id,
                "available_slots": self.appointments.get(resolved_id, self.appointments["cust_123"]),
            },
        }


def extract_order_id(message: str) -> str | None:
    match = re.search(r"\b(?:ord|order)[-_ ]?(\d{3,})\b", message, flags=re.IGNORECASE)
    if not match:
        return None
    return f"ord_{match.group(1)}"

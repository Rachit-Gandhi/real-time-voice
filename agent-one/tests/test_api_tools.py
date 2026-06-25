from app.graph.nodes.api_tools import call_api_tool


def test_call_api_tool_routes_order_status():
    result = call_api_tool(
        {
            "user_message": "What is my order status?",
            "thread_id": "t1",
            "context": {"customer_id": "cust_123"},
        }
    )

    assert result["api_action"] == "get_order_status"
    assert result["api_result"]["data"]["order_id"] == "ord_1001"


def test_call_api_tool_routes_invoice_summary():
    result = call_api_tool(
        {
            "user_message": "Do I have unpaid invoices?",
            "thread_id": "t2",
            "context": {"customer_id": "cust_123"},
        }
    )

    assert result["api_action"] == "get_invoice_summary"
    assert result["api_result"]["data"]["open_invoice_count"] == 1

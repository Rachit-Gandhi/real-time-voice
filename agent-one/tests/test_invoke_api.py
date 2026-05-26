def test_invoke_returns_answer_and_speak(client):
    response = client.post(
        "/agents/agent-one/invoke",
        json={"message": "What services do you offer?", "thread_id": "t1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["answer"], str)
    assert isinstance(body["speak"], str)
    assert body["intent"] == "website_qa"
    assert isinstance(body["citations"], list)
    assert isinstance(body["confidence"], float)


def test_invoke_supports_api_intent(client):
    response = client.post(
        "/agents/agent-one/invoke",
        json={"message": "What is my order status?", "thread_id": "t2", "user_id": "cust_123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "sql_qa"
    assert "order" in body["answer"].lower()
    assert body["sources"] == [{"type": "api", "tool": "get_order_status"}]


def test_invoke_supports_hybrid_intent(client):
    response = client.post(
        "/agents/agent-one/invoke",
        json={"message": "What is the refund policy and my order status?", "thread_id": "t3"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "hybrid"
    assert "refund" in body["answer"].lower()
    assert any(source["type"] == "website" for source in body["sources"])
    assert any(source["type"] == "api" for source in body["sources"])

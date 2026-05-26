def test_invoke_returns_answer_and_speak(client):
    response = client.post(
        "/agents/agent-one/invoke",
        json={"message": "What services do you offer?", "thread_id": "t1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["answer"], str)
    assert isinstance(body["speak"], str)

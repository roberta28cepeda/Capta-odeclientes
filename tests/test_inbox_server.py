from unittest.mock import patch

import pytest

from src.inbox.schema import SuggestedReply
from src.inbox.server import create_app

PROFILE = {"freelancer_name": "Ana Dev"}


@pytest.fixture
def client():
    app = create_app(PROFILE)
    app.testing = True
    return app.test_client()


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_webhook_returns_suggested_reply(client):
    fake_reply = SuggestedReply(
        category="dúvida sobre serviço",
        priority="média",
        suggested_reply="Claro, posso te explicar melhor...",
        reasoning="Pergunta simples sobre o serviço.",
    )

    with patch("src.inbox.server.generate_suggested_reply", return_value=fake_reply) as mock_generate:
        response = client.post("/webhook", json={"message": "Como funciona o serviço?"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["category"] == "dúvida sobre serviço"
    assert body["suggested_reply"].startswith("Claro")
    mock_generate.assert_called_once()
    _, call_kwargs = mock_generate.call_args
    assert call_kwargs["thread_history"] is None


def test_webhook_requires_message_field(client):
    response = client.post("/webhook", json={})

    assert response.status_code == 400
    assert "message" in response.get_json()["error"]

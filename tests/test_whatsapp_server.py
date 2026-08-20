from unittest.mock import patch

import pytest

from src.inbox.schema import SuggestedReply
from src.whatsapp.server import IncomingMessage, create_app, parse_incoming_messages

PROFILE = {"freelancer_name": "Ana Dev"}

SAMPLE_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "WABA_ID",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "15550001111", "phone_number_id": "PHONE_ID"},
                        "contacts": [{"profile": {"name": "João"}, "wa_id": "5511999999999"}],
                        "messages": [
                            {
                                "from": "5511999999999",
                                "id": "wamid.abc",
                                "timestamp": "1700000000",
                                "type": "text",
                                "text": {"body": "Quanto custa um site?"},
                            }
                        ],
                    },
                    "field": "messages",
                }
            ],
        }
    ],
}

SAMPLE_PAYLOAD_NON_TEXT = {
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "contacts": [{"profile": {"name": "João"}, "wa_id": "5511999999999"}],
                        "messages": [{"from": "5511999999999", "id": "wamid.img", "type": "image"}],
                    }
                }
            ]
        }
    ]
}


def test_parse_incoming_messages_extracts_text_and_contact_name():
    messages = parse_incoming_messages(SAMPLE_PAYLOAD)

    assert messages == [
        IncomingMessage(
            from_number="5511999999999",
            text="Quanto custa um site?",
            message_id="wamid.abc",
            contact_name="João",
        )
    ]


def test_parse_incoming_messages_skips_non_text_messages():
    assert parse_incoming_messages(SAMPLE_PAYLOAD_NON_TEXT) == []


def test_parse_incoming_messages_handles_empty_payload():
    assert parse_incoming_messages({}) == []


@pytest.fixture
def app():
    return create_app(PROFILE, verify_token="secret-token", phone_number_id="PHONE_ID", access_token="TOKEN")


def test_webhook_verification_succeeds_with_correct_token(app):
    client = app.test_client()
    response = client.get(
        "/webhook",
        query_string={"hub.mode": "subscribe", "hub.verify_token": "secret-token", "hub.challenge": "12345"},
    )
    assert response.status_code == 200
    assert response.data == b"12345"


def test_webhook_verification_fails_with_wrong_token(app):
    client = app.test_client()
    response = client.get(
        "/webhook",
        query_string={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"},
    )
    assert response.status_code == 403


def test_webhook_post_generates_reply_but_does_not_auto_send_by_default(app):
    fake_reply = SuggestedReply(
        category="pedido de orçamento",
        priority="alta",
        suggested_reply="Consigo te passar um orçamento, sim!",
        reasoning="Lead pedindo preço.",
    )
    with (
        patch("src.whatsapp.server.generate_suggested_reply", return_value=fake_reply) as mock_generate,
        patch("src.whatsapp.server.send_text_message") as mock_send,
    ):
        response = app.test_client().post("/webhook", json=SAMPLE_PAYLOAD)

    assert response.status_code == 200
    mock_generate.assert_called_once()
    mock_send.assert_not_called()


def test_webhook_post_auto_replies_when_enabled():
    fake_reply = SuggestedReply(
        category="pedido de orçamento",
        priority="alta",
        suggested_reply="Consigo te passar um orçamento, sim!",
        reasoning="Lead pedindo preço.",
    )
    app = create_app(
        PROFILE, verify_token="secret-token", phone_number_id="PHONE_ID", access_token="TOKEN", auto_reply=True
    )

    with (
        patch("src.whatsapp.server.generate_suggested_reply", return_value=fake_reply),
        patch("src.whatsapp.server.send_text_message") as mock_send,
    ):
        app.test_client().post("/webhook", json=SAMPLE_PAYLOAD)

    mock_send.assert_called_once_with(
        "5511999999999", "Consigo te passar um orçamento, sim!", "PHONE_ID", "TOKEN"
    )

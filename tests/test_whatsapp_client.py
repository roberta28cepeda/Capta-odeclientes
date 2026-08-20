from unittest.mock import MagicMock, mock_open, patch

import pytest

from src.whatsapp.client import (
    WhatsAppError,
    send_document_message,
    send_pdf,
    send_text_message,
    upload_media,
)


def _mock_response(status_code=200, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    return response


def test_send_text_message_builds_expected_payload():
    session = MagicMock()
    session.post.return_value = _mock_response(200, {"messages": [{"id": "wamid.1"}]})

    result = send_text_message("5511999999999", "Oi!", "PHONE_ID", "TOKEN", session=session)

    assert result == {"messages": [{"id": "wamid.1"}]}
    call_args, kwargs = session.post.call_args
    assert call_args[0] == "https://graph.facebook.com/v21.0/PHONE_ID/messages"
    assert kwargs["headers"]["Authorization"] == "Bearer TOKEN"
    assert kwargs["json"] == {
        "messaging_product": "whatsapp",
        "to": "5511999999999",
        "type": "text",
        "text": {"body": "Oi!"},
    }


def test_send_text_message_raises_on_error_status():
    session = MagicMock()
    session.post.return_value = _mock_response(400, {"error": {"message": "bad token"}})

    with pytest.raises(WhatsAppError, match="bad token"):
        send_text_message("5511999999999", "Oi!", "PHONE_ID", "BAD_TOKEN", session=session)


def test_upload_media_sends_multipart_and_returns_media_id():
    session = MagicMock()
    session.post.return_value = _mock_response(200, {"id": "media-123"})

    with patch("builtins.open", mock_open(read_data=b"%PDF-fake")):
        media_id = upload_media("proposta.pdf", "application/pdf", "PHONE_ID", "TOKEN", session=session)

    assert media_id == "media-123"
    _, kwargs = session.post.call_args
    assert kwargs["data"] == {"messaging_product": "whatsapp"}
    assert "file" in kwargs["files"]


def test_send_document_message_requires_media_id_or_link():
    with pytest.raises(ValueError):
        send_document_message("5511999999999", "PHONE_ID", "TOKEN")


def test_send_document_message_with_media_id():
    session = MagicMock()
    session.post.return_value = _mock_response(200, {"messages": [{"id": "wamid.2"}]})

    send_document_message(
        "5511999999999",
        "PHONE_ID",
        "TOKEN",
        media_id="media-123",
        filename="proposta.pdf",
        caption="Segue a proposta",
        session=session,
    )

    _, kwargs = session.post.call_args
    assert kwargs["json"]["document"] == {
        "id": "media-123",
        "filename": "proposta.pdf",
        "caption": "Segue a proposta",
    }


def test_send_pdf_uploads_then_sends_document():
    session = MagicMock()

    with (
        patch("src.whatsapp.client.upload_media", return_value="media-123") as mock_upload,
        patch("src.whatsapp.client.send_document_message", return_value={"ok": True}) as mock_send,
    ):
        result = send_pdf("output/proposta.pdf", "5511999999999", "PHONE_ID", "TOKEN", session=session)

    assert result == {"ok": True}
    mock_upload.assert_called_once_with(
        "output/proposta.pdf", "application/pdf", "PHONE_ID", "TOKEN", session=session
    )
    mock_send.assert_called_once()
    _, call_kwargs = mock_send.call_args
    assert call_kwargs["media_id"] == "media-123"
    assert call_kwargs["filename"] == "proposta.pdf"

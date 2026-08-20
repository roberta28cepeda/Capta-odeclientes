"""Thin client for the official WhatsApp Cloud API (Meta)."""

from __future__ import annotations

import os

import requests

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class WhatsAppError(RuntimeError):
    """Raised when the Cloud API returns an error response."""


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def send_text_message(
    to: str,
    text: str,
    phone_number_id: str,
    access_token: str,
    session: requests.Session | None = None,
) -> dict:
    """Send a free-form text message.

    Only deliverable inside the 24h customer service window, or the Cloud
    API rejects it — outside that window you need an approved template.
    """
    session = session or requests.Session()
    url = f"{BASE_URL}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    response = session.post(url, headers=_headers(access_token), json=payload, timeout=10)
    data = response.json()
    if response.status_code >= 400:
        raise WhatsAppError(f"Falha ao enviar mensagem: {data}")
    return data


def upload_media(
    file_path: str,
    mime_type: str,
    phone_number_id: str,
    access_token: str,
    session: requests.Session | None = None,
) -> str:
    """Upload a local file to Meta's media endpoint, returning a media_id."""
    session = session or requests.Session()
    url = f"{BASE_URL}/{phone_number_id}/media"
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f, mime_type)}
        data = {"messaging_product": "whatsapp"}
        response = session.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            files=files,
            data=data,
            timeout=30,
        )
    payload = response.json()
    if response.status_code >= 400:
        raise WhatsAppError(f"Falha ao enviar arquivo: {payload}")
    return payload["id"]


def send_document_message(
    to: str,
    phone_number_id: str,
    access_token: str,
    *,
    media_id: str | None = None,
    link: str | None = None,
    filename: str | None = None,
    caption: str | None = None,
    session: requests.Session | None = None,
) -> dict:
    if not media_id and not link:
        raise ValueError("Informe media_id ou link.")

    document: dict[str, str] = {}
    if media_id:
        document["id"] = media_id
    if link:
        document["link"] = link
    if filename:
        document["filename"] = filename
    if caption:
        document["caption"] = caption

    session = session or requests.Session()
    url = f"{BASE_URL}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": document,
    }
    response = session.post(url, headers=_headers(access_token), json=payload, timeout=10)
    data = response.json()
    if response.status_code >= 400:
        raise WhatsAppError(f"Falha ao enviar documento: {data}")
    return data


def send_pdf(
    file_path: str,
    to: str,
    phone_number_id: str,
    access_token: str,
    caption: str | None = None,
    session: requests.Session | None = None,
) -> dict:
    """Upload a local PDF and send it as a document message in one step."""
    session = session or requests.Session()
    media_id = upload_media(file_path, "application/pdf", phone_number_id, access_token, session=session)
    return send_document_message(
        to,
        phone_number_id,
        access_token,
        media_id=media_id,
        filename=os.path.basename(file_path),
        caption=caption,
        session=session,
    )

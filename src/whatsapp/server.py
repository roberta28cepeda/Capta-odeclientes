"""Webhook receiver for the WhatsApp Cloud API: parse events, draft replies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anthropic
from flask import Flask, jsonify, request

from src.inbox.generator import generate_suggested_reply
from src.whatsapp.client import send_text_message


@dataclass
class IncomingMessage:
    from_number: str
    text: str
    message_id: str
    contact_name: str | None


def parse_incoming_messages(payload: dict) -> list[IncomingMessage]:
    """Extract text messages from a Cloud API webhook POST body.

    Non-text messages (image, audio, location, ...) are skipped in this MVP.
    """
    messages: list[IncomingMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names_by_wa_id = {
                contact.get("wa_id"): contact.get("profile", {}).get("name")
                for contact in value.get("contacts", [])
            }
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                messages.append(
                    IncomingMessage(
                        from_number=msg["from"],
                        text=msg.get("text", {}).get("body", ""),
                        message_id=msg["id"],
                        contact_name=names_by_wa_id.get(msg["from"]),
                    )
                )
    return messages


def create_app(
    profile: dict[str, Any],
    verify_token: str,
    phone_number_id: str,
    access_token: str,
    auto_reply: bool = False,
    client: anthropic.Anthropic | None = None,
) -> Flask:
    app = Flask(__name__)

    @app.get("/webhook")
    def verify():
        # Meta calls this once, at setup time, to confirm you control the endpoint.
        if (
            request.args.get("hub.mode") == "subscribe"
            and request.args.get("hub.verify_token") == verify_token
        ):
            return request.args.get("hub.challenge", ""), 200
        return "Forbidden", 403

    @app.post("/webhook")
    def receive():
        payload = request.get_json(force=True, silent=True) or {}
        for message in parse_incoming_messages(payload):
            reply = generate_suggested_reply(message.text, profile, client=client)
            print(f"[WhatsApp] {message.from_number} ({message.contact_name}): {message.text}")
            print(f"  Sugestão ({reply.category}/{reply.priority}): {reply.suggested_reply}")
            if auto_reply:
                send_text_message(message.from_number, reply.suggested_reply, phone_number_id, access_token)
        # Always 200 quickly — Meta retries aggressively on non-2xx or timeouts.
        return jsonify({"status": "received"}), 200

    return app

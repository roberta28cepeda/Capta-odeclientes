"""Minimal webhook receiver: POST an inbox message, get a suggested reply back."""

from __future__ import annotations

from typing import Any

import anthropic
from flask import Flask, jsonify, request

from src.inbox.generator import generate_suggested_reply


def create_app(profile: dict[str, Any], client: anthropic.Anthropic | None = None) -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/webhook")
    def webhook():
        payload = request.get_json(force=True, silent=True) or {}
        message = payload.get("message")
        if not message:
            return jsonify({"error": "campo 'message' é obrigatório"}), 400

        reply = generate_suggested_reply(
            message,
            profile,
            thread_history=payload.get("thread_history"),
            client=client,
        )
        return jsonify(reply.model_dump())

    return app

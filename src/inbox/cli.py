"""CLI: draft a reply for an inbox message, or run a webhook server that does it.

Usage:
    python -m src.inbox.cli --message-text "Oi, quanto custa um site?"
    python -m src.inbox.cli --message mensagem.txt --thread-history historico.txt
    python -m src.inbox.cli --serve --port 8000
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml
from dotenv import load_dotenv

from src.inbox.generator import generate_suggested_reply


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sugere resposta para mensagens da caixa de entrada, no seu tom."
    )
    parser.add_argument(
        "--profile",
        default="profiles/freelancer_profile.yaml",
        help="Caminho para o perfil do freelancer (.yaml)",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--message", help="Caminho para um .txt com a mensagem recebida")
    mode.add_argument("--message-text", help="Texto da mensagem recebida, direto na linha de comando")
    mode.add_argument("--serve", action="store_true", help="Sobe um servidor webhook local (POST /webhook)")

    parser.add_argument("--thread-history", help="Arquivo .txt com o histórico da conversa (opcional)")
    parser.add_argument("--host", default="127.0.0.1", help="Host do servidor webhook (--serve)")
    parser.add_argument("--port", type=int, default=8000, help="Porta do servidor webhook (--serve)")
    parser.add_argument("--model", default=None, help="Sobrescreve o modelo Claude usado")
    return parser.parse_args(argv)


def _load_profile(profile_path: str) -> dict:
    if not os.path.exists(profile_path):
        print(
            f"Perfil não encontrado: {profile_path}. "
            "Copie profiles/freelancer_profile.example.yaml e edite.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    with open(profile_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    profile = _load_profile(args.profile)

    if args.serve:
        from src.inbox.server import create_app

        app = create_app(profile)
        print(f"Servidor webhook em http://{args.host}:{args.port}/webhook (POST) — Ctrl+C para parar")
        app.run(host=args.host, port=args.port)
        return 0

    if args.message:
        if not os.path.exists(args.message):
            print(f"Mensagem não encontrada: {args.message}", file=sys.stderr)
            return 1
        with open(args.message, encoding="utf-8") as f:
            message = f.read()
    else:
        message = args.message_text

    thread_history = None
    if args.thread_history:
        if not os.path.exists(args.thread_history):
            print(f"Histórico não encontrado: {args.thread_history}", file=sys.stderr)
            return 1
        with open(args.thread_history, encoding="utf-8") as f:
            thread_history = f.read()

    kwargs = {}
    if args.model:
        kwargs["model"] = args.model

    reply = generate_suggested_reply(message, profile, thread_history=thread_history, **kwargs)

    print(f"Categoria: {reply.category}")
    print(f"Prioridade: {reply.priority}")
    print(f"\nResposta sugerida:\n{reply.suggested_reply}")
    print(f"\nPor quê: {reply.reasoning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

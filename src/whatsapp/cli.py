"""CLI: send WhatsApp messages/PDFs via the official Cloud API, or receive them.

Usage:
    python -m src.whatsapp.cli --to 5511999999999 --send-text "Oi! Tudo bem?"
    python -m src.whatsapp.cli --to 5511999999999 --send-pdf output/proposta.pdf --caption "Segue a proposta"
    python -m src.whatsapp.cli --serve --port 8080
    python -m src.whatsapp.cli --serve --auto-reply  # envia a resposta sugerida sem revisão humana

Requer WHATSAPP_ACCESS_TOKEN e WHATSAPP_PHONE_NUMBER_ID no .env (e
WHATSAPP_VERIFY_TOKEN para --serve). Veja README.md para como obter esses
valores no Meta for Developers.
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml
from dotenv import load_dotenv

from src.whatsapp.client import send_pdf, send_text_message


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Envia/recebe mensagens de WhatsApp via Cloud API oficial da Meta."
    )
    parser.add_argument("--to", help="Número do destinatário, formato internacional (ex: 5511999999999)")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--send-text", metavar="TEXTO", help="Envia uma mensagem de texto")
    mode.add_argument("--send-pdf", metavar="ARQUIVO", help="Envia um PDF (ex: a proposta gerada)")
    mode.add_argument("--serve", action="store_true", help="Sobe o servidor webhook para receber mensagens")

    parser.add_argument("--caption", help="Legenda opcional para --send-pdf")
    parser.add_argument(
        "--profile",
        default="profiles/freelancer_profile.yaml",
        help="Perfil do freelancer, usado em --serve para sugerir respostas",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host do servidor webhook (--serve)")
    parser.add_argument("--port", type=int, default=8080, help="Porta do servidor webhook (--serve)")
    parser.add_argument(
        "--auto-reply",
        action="store_true",
        help="Em --serve, envia a resposta sugerida automaticamente, sem revisão humana. Use com cautela.",
    )
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

    access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    if not access_token or not phone_number_id:
        print(
            "Defina WHATSAPP_ACCESS_TOKEN e WHATSAPP_PHONE_NUMBER_ID no .env.",
            file=sys.stderr,
        )
        return 1

    if args.serve:
        verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN")
        if not verify_token:
            print(
                "Defina WHATSAPP_VERIFY_TOKEN no .env (escolha um valor e configure "
                "o mesmo no painel de configuração do webhook no Meta for Developers).",
                file=sys.stderr,
            )
            return 1

        from src.whatsapp.server import create_app

        profile = _load_profile(args.profile)
        app = create_app(
            profile,
            verify_token,
            phone_number_id,
            access_token,
            auto_reply=args.auto_reply,
        )
        print(f"Webhook em http://{args.host}:{args.port}/webhook — Ctrl+C para parar")
        if args.auto_reply:
            print(
                "ATENÇÃO: --auto-reply está ativo — as respostas sugeridas serão "
                "enviadas automaticamente, sem revisão humana."
            )
        app.run(host=args.host, port=args.port)
        return 0

    if not args.to:
        print("--to é obrigatório para --send-text/--send-pdf.", file=sys.stderr)
        return 1

    if args.send_text:
        result = send_text_message(args.to, args.send_text, phone_number_id, access_token)
        print(f"Mensagem enviada: {result}")
        return 0

    if not os.path.exists(args.send_pdf):
        print(f"Arquivo não encontrado: {args.send_pdf}", file=sys.stderr)
        return 1

    result = send_pdf(args.send_pdf, args.to, phone_number_id, access_token, caption=args.caption)
    print(f"Documento enviado: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI: importa leads, busca e-mail via Google, roda o envio do dia e o
relatório semanal — pra rodar localmente/testar sem depender do cron do
Vercel. Em produção, `/cron/campanhas/rodar` (protegido por CRON_SECRET)
faz o mesmo que `--enviar-diario` + `--relatorio-semanal` (às segundas).

Uso:
    python -m src.campaigns.cli --import-leads --csv leads_pgfn.csv
    python -m src.campaigns.cli --buscar-emails
    python -m src.campaigns.cli --enviar-diario --base-url https://capta-fiscal-monitor.vercel.app
    python -m src.campaigns.cli --relatorio-semanal --destinatario contato@leactis.com.br
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

from dotenv import load_dotenv

from src.campaigns import engine, storage
from src.campaigns.email_finder import EmailFinderError, buscar_email_por_empresa


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Campanha de prospecção fria pra lista de devedores da PGFN.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--import-leads", action="store_true", help="Importa leads de um CSV (cnpj,razao_social,email)")
    mode.add_argument("--buscar-emails", action="store_true", help="Busca e-mail via Google pros leads sem e-mail")
    mode.add_argument("--enviar-diario", action="store_true", help="Roda o envio do dia (inicial/follow-up)")
    mode.add_argument("--relatorio-semanal", action="store_true", help="Envia o relatório de abertura/clique dos últimos 7 dias")

    parser.add_argument("--db-path", default=storage.DEFAULT_DB_PATH, help="Caminho do banco sqlite")
    parser.add_argument("--csv", help="Caminho do CSV, para --import-leads")
    parser.add_argument("--base-url", default="http://localhost:8090", help="URL pública do dashboard, pros links de rastreio")
    parser.add_argument("--destinatario", help="E-mail que recebe o relatório semanal")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    conn = storage.connect(args.db_path)

    if args.import_leads:
        if not args.csv:
            print("--csv é obrigatório para --import-leads.", file=sys.stderr)
            return 1
        count = 0
        with open(args.csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cnpj = (row.get("cnpj") or "").strip()
                if not cnpj:
                    continue
                storage.create_lead(
                    conn, cnpj, razao_social=(row.get("razao_social") or "").strip() or None,
                    email=(row.get("email") or "").strip() or None,
                )
                count += 1
        print(f"{count} lead(s) importado(s).")
        return 0

    if args.buscar_emails:
        api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
        if not api_key:
            print("Defina BRAVE_SEARCH_API_KEY no .env para --buscar-emails.", file=sys.stderr)
            return 1
        leads = storage.leads_sem_email(conn)
        encontrados = 0
        for lead in leads:
            try:
                email = buscar_email_por_empresa(lead.razao_social or lead.cnpj, api_key)
            except EmailFinderError as exc:
                print(f"Erro ao buscar e-mail de {lead.cnpj}: {exc}", file=sys.stderr)
                continue
            if email:
                storage.set_lead_email(conn, lead.id, email)
                encontrados += 1
        print(f"{encontrados}/{len(leads)} lead(s) com e-mail encontrado.")
        return 0

    if args.enviar_diario:
        smtp_host = os.environ.get("SMTP_HOST")
        smtp_port = os.environ.get("SMTP_PORT")
        smtp_username = os.environ.get("SMTP_USERNAME")
        smtp_password = os.environ.get("SMTP_PASSWORD")
        if not all([smtp_host, smtp_port, smtp_username, smtp_password]):
            print("Defina SMTP_HOST, SMTP_PORT, SMTP_USERNAME e SMTP_PASSWORD no .env.", file=sys.stderr)
            return 1
        resultado = engine.rodar_diario(
            conn, args.base_url, smtp_host, int(smtp_port), smtp_username, smtp_password,
            smtp_from=os.environ.get("SMTP_FROM"),
        )
        print(f"{resultado['enviados']}/{resultado['leads_verificados']} e-mail(s) enviado(s).")
        for erro in resultado["erros"]:
            print(f"  erro no lead {erro['cnpj']}: {erro['erro']}", file=sys.stderr)
        return 0

    if args.relatorio_semanal:
        smtp_host = os.environ.get("SMTP_HOST")
        smtp_port = os.environ.get("SMTP_PORT")
        smtp_username = os.environ.get("SMTP_USERNAME")
        smtp_password = os.environ.get("SMTP_PASSWORD")
        destinatario = args.destinatario or smtp_username
        if not all([smtp_host, smtp_port, smtp_username, smtp_password, destinatario]):
            print("Defina SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD e --destinatario.", file=sys.stderr)
            return 1
        engine.enviar_relatorio_semanal(
            conn, destinatario, smtp_host, int(smtp_port), smtp_username, smtp_password,
            smtp_from=os.environ.get("SMTP_FROM"),
        )
        print(f"Relatório semanal enviado para {destinatario}.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

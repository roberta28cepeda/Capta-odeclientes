"""CLI: cadastra escritórios (tenants) e suas carteiras de CNPJ, importa
achados fiscais via CSV, roda o motor de alertas e sobe o dashboard.

Este MVP não consulta o e-CAC/DCTFWeb ao vivo — os achados fiscais vêm de
um CSV (export manual do e-CAC, ou de um scraper que o escritório já use).
Veja README.md para o porquê e o que falta pra integração real.

Uso:
    python -m src.fiscal_monitor.cli --import-tenant --nome "Escritório X" --whatsapp 5511999999999
    python -m src.fiscal_monitor.cli --import-portfolio --tenant-id 1 --csv carteira.csv
    python -m src.fiscal_monitor.cli --import-snapshot --tenant-id 1 --csv snapshot_ecac.csv
    python -m src.fiscal_monitor.cli --check --tenant-id 1 --dias-alerta 5
    python -m src.fiscal_monitor.cli --check --tenant-id 1 --pdf --enviar-whatsapp
    python -m src.fiscal_monitor.cli --serve --port 8090
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

from dotenv import load_dotenv

from src.fiscal_monitor import alerts, monitor, storage
from src.fiscal_monitor.providers import ManualFiscalProvider


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitoramento fiscal de carteira de CNPJs (estilo Veri) — MVP com dados via CSV."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--import-tenant", action="store_true", help="Cadastra um novo escritório (tenant)")
    mode.add_argument("--import-portfolio", action="store_true", help="Importa carteira de CNPJs de um CSV")
    mode.add_argument("--import-snapshot", action="store_true", help="Importa achados fiscais de um CSV")
    mode.add_argument("--check", action="store_true", help="Roda o motor de alertas sobre o último snapshot")
    mode.add_argument("--serve", action="store_true", help="Sobe o dashboard web")

    parser.add_argument("--db-path", default=storage.DEFAULT_DB_PATH, help="Caminho do banco sqlite")
    parser.add_argument("--tenant-id", type=int, help="ID do tenant (obrigatório exceto em --import-tenant)")
    parser.add_argument("--nome", help="Nome do escritório, para --import-tenant")
    parser.add_argument("--whatsapp", help="Contato de WhatsApp do escritório, formato internacional")
    parser.add_argument("--plano", help="Plano/tier do tenant, para --import-tenant")
    parser.add_argument("--csv", help="Caminho do CSV, para --import-portfolio/--import-snapshot")
    parser.add_argument(
        "--dias-alerta",
        type=int,
        default=monitor.DEFAULT_DIAS_ALERTA,
        help="Janela de dias pra alertar DAS a vencer, em --check",
    )
    parser.add_argument("--pdf", action="store_true", help="Em --check, gera o relatório de carteira em PDF")
    parser.add_argument("--output-dir", default="output", help="Diretório de saída do PDF (--check --pdf)")
    parser.add_argument(
        "--enviar-whatsapp",
        action="store_true",
        help="Em --check, envia o resumo (ou o PDF, se --pdf) por WhatsApp ao contato do tenant",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host do dashboard (--serve)")
    parser.add_argument("--port", type=int, default=8090, help="Porta do dashboard (--serve)")
    return parser.parse_args(argv)


def _require(value, flag: str) -> bool:
    if value is None:
        print(f"{flag} é obrigatório para este modo.", file=sys.stderr)
        return False
    return True


def _get_tenant_or_fail(conn, tenant_id: int) -> storage.Tenant | None:
    tenant = storage.get_tenant(conn, tenant_id)
    if tenant is None:
        print(f"Tenant {tenant_id} não encontrado.", file=sys.stderr)
    return tenant


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)

    if args.import_tenant:
        if not _require(args.nome, "--nome"):
            return 1
        conn = storage.connect(args.db_path)
        tenant = storage.create_tenant(conn, args.nome, contato_whatsapp=args.whatsapp, plano=args.plano)
        conn.close()
        print(f"Tenant criado: id={tenant.id} nome={tenant.nome}")
        return 0

    if args.import_portfolio:
        if not _require(args.tenant_id, "--tenant-id") or not _require(args.csv, "--csv"):
            return 1
        conn = storage.connect(args.db_path)
        if _get_tenant_or_fail(conn, args.tenant_id) is None:
            conn.close()
            return 1

        count = 0
        with open(args.csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cnpj = (row.get("cnpj") or "").strip()
                if not cnpj:
                    continue
                storage.upsert_cnpj(
                    conn,
                    args.tenant_id,
                    cnpj,
                    razao_social=(row.get("razao_social") or "").strip() or None,
                    nome_fantasia=(row.get("nome_fantasia") or "").strip() or None,
                )
                count += 1
        conn.close()
        print(f"{count} CNPJ(s) importado(s) para o tenant {args.tenant_id}.")
        return 0

    if args.import_snapshot:
        if not _require(args.tenant_id, "--tenant-id") or not _require(args.csv, "--csv"):
            return 1
        conn = storage.connect(args.db_path)
        if _get_tenant_or_fail(conn, args.tenant_id) is None:
            conn.close()
            return 1

        try:
            findings_by_cnpj = ManualFiscalProvider(args.csv).fetch()
        except (OSError, ValueError) as exc:
            print(f"Erro ao ler {args.csv}: {exc}", file=sys.stderr)
            conn.close()
            return 1

        novos = 0
        for cnpj_numero, raw_findings in findings_by_cnpj.items():
            cnpj = storage.get_cnpj_by_number(conn, args.tenant_id, cnpj_numero)
            if cnpj is None:
                print(
                    f"Aviso: CNPJ {cnpj_numero} não está na carteira do tenant {args.tenant_id} — pulando. "
                    "Importe a carteira primeiro com --import-portfolio.",
                    file=sys.stderr,
                )
                continue
            saved = monitor.apply_snapshot(conn, cnpj, ManualFiscalProvider.name, raw_findings)
            novos += sum(1 for finding in saved if finding.status == monitor.STATUS_NOVA)
        conn.close()
        print(f"Snapshot importado. {novos} achado(s) novo(s) detectado(s).")
        return 0

    if args.check:
        if not _require(args.tenant_id, "--tenant-id"):
            return 1
        conn = storage.connect(args.db_path)
        tenant = _get_tenant_or_fail(conn, args.tenant_id)
        if tenant is None:
            conn.close()
            return 1

        alert_items = monitor.check_tenant(conn, args.tenant_id, dias_alerta=args.dias_alerta)
        print(alerts.format_alerts_summary(tenant, alert_items))

        pdf_path = None
        if args.pdf:
            from src.fiscal_monitor.pdf import render_portfolio_report

            os.makedirs(args.output_dir, exist_ok=True)
            findings_by_cnpj = storage.findings_by_cnpj_for_tenant(conn, args.tenant_id)
            pdf_path = os.path.join(args.output_dir, "relatorio_fiscal.pdf")
            render_portfolio_report(tenant, findings_by_cnpj, pdf_path)
            print(f"Relatório salvo em {pdf_path}")

        conn.close()

        if args.enviar_whatsapp:
            access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
            phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
            if not access_token or not phone_number_id:
                print(
                    "Defina WHATSAPP_ACCESS_TOKEN e WHATSAPP_PHONE_NUMBER_ID no .env para --enviar-whatsapp.",
                    file=sys.stderr,
                )
                return 1
            result = (
                alerts.send_whatsapp_report(tenant, pdf_path, phone_number_id, access_token)
                if pdf_path
                else alerts.send_whatsapp_alert(tenant, alert_items, phone_number_id, access_token)
            )
            if result is None:
                print("Nada enviado (tenant sem WhatsApp cadastrado, ou nenhum alerta novo).")
            else:
                print("Enviado por WhatsApp.")
        return 0

    if args.serve:
        from src.fiscal_monitor.server import create_app

        app = create_app(db_path=args.db_path)
        print(f"Dashboard em http://{args.host}:{args.port}/tenants — Ctrl+C para parar")
        app.run(host=args.host, port=args.port)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

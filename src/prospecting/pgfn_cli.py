"""CLI: turn a Lista de Devedores PGFN export into a tiered leads CSV.

Usage:
    python -m src.prospecting.pgfn_cli --csv devedores.csv --output leads_pgfn.csv
"""

from __future__ import annotations

import argparse
import csv
import sys

from src.prospecting.pgfn import (
    TIER_LABELS,
    enrich_with_public_contact,
    pareto_concentration,
    parse_pgfn_csv,
    summarize_by_tier,
)

CSV_FIELDS = [
    "cnpj",
    "razao_social",
    "nome_fantasia",
    "valor_selecionado",
    "valor_total",
    "tipo_registro",
    "tier",
    "telefone",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parseia um export da Lista de Devedores da PGFN em leads segmentados por tier."
    )
    parser.add_argument("--csv", required=True, help="Caminho para o CSV exportado da PGFN")
    parser.add_argument("--output", default="leads_pgfn.csv", help="Caminho do CSV de saída")
    parser.add_argument(
        "--encoding",
        default="latin-1",
        help="Encoding do arquivo de entrada (a PGFN exporta em ISO-8859-1/latin-1)",
    )
    parser.add_argument(
        "--enrich-contato",
        action="store_true",
        help="Busca o telefone público de cada CNPJ na BrasilAPI antes de salvar (mesma consulta da pré-análise fiscal)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        debtors = parse_pgfn_csv(args.csv, encoding=args.encoding)
    except (OSError, ValueError) as exc:
        print(f"Erro ao ler {args.csv}: {exc}", file=sys.stderr)
        return 1

    if not debtors:
        print("Nenhum devedor encontrado no arquivo.", file=sys.stderr)
        return 1

    if args.enrich_contato:
        print(f"Consultando telefone público de {len(debtors)} CNPJ(s) na BrasilAPI...")
        enrich_with_public_contact(debtors)
        com_telefone = sum(1 for d in debtors if d.telefone)
        print(f"{com_telefone}/{len(debtors)} encontrados com telefone público.\n")

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for debtor in debtors:
            writer.writerow(
                {
                    "cnpj": debtor.cnpj,
                    "razao_social": debtor.razao_social,
                    "nome_fantasia": debtor.nome_fantasia or "",
                    "valor_selecionado": f"{debtor.valor_selecionado:.2f}",
                    "valor_total": f"{debtor.valor_total:.2f}",
                    "tipo_registro": debtor.tipo_registro,
                    "tier": debtor.tier,
                    "telefone": debtor.telefone or "",
                }
            )

    print(f"{len(debtors)} devedores salvos em {args.output}\n")

    summary = summarize_by_tier(debtors)
    print("Resumo por tier:")
    for tier, label in TIER_LABELS.items():
        stats = summary[tier]
        print(f"  {tier} — {label}: {stats['count']} empresas, R$ {stats['total_valor']:,.2f}")

    pct_empresas, pct_valor = pareto_concentration(debtors, tier="A")
    if pct_empresas:
        print(
            f"\nTier A concentra {pct_empresas:.1f}% das empresas e "
            f"{pct_valor:.1f}% de toda a dívida selecionada — priorize por aí."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Parses a "Lista de Devedores da PGFN" export into tiered leads.

The PGFN (dívida ativa da União) export isn't a clean CSV: it has a
metadata preamble before the real header, ISO-8859-1 encoding, `;` as
separator, and numbers in Brazilian format. See the skill this was ported
from for the full field reference.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass

HEADER_MARKER = "CPF/CNPJ"

# (tier, minimum valor_selecionado to qualify) — first match wins, in order.
TIER_THRESHOLDS: list[tuple[str, float]] = [
    ("A", 500_000),
    ("B", 100_000),
    ("C", 20_000),
    ("D", 0),
]

TIER_LABELS: dict[str, str] = {
    "A": "Grande porte (>= R$500 mil)",
    "B": "Médio porte (R$100 mil a R$500 mil)",
    "C": "Pequeno relevante (R$20 mil a R$100 mil)",
    "D": "Volume baixo (< R$20 mil)",
}

_PF_EI_PATTERNS = [
    re.compile(r"\d{11}\s*$"),
    re.compile(r"^\d{2}\.?\d{3}\.?\d{3}\s"),
]


@dataclass
class PgfnDebtor:
    cnpj: str
    razao_social: str
    nome_fantasia: str | None
    valor_selecionado: float
    valor_total: float
    tipo_registro: str
    tier: str


def parse_brl_number(value: str) -> float:
    """Converts a Brazilian-formatted number string ("70.316.092,50") to float."""
    cleaned = value.strip()
    if not cleaned:
        return 0.0
    return float(cleaned.replace(".", "").replace(",", "."))


def assign_tier(valor_selecionado: float) -> str:
    for tier, threshold in TIER_THRESHOLDS:
        if valor_selecionado >= threshold:
            return tier
    return TIER_THRESHOLDS[-1][0]


def classify_registro(nome: str) -> str:
    """Heuristic: pessoa física/EI vs empresa constituída, based on the Nome field.

    Not a reliable size signal by itself — an EI-pattern name can still carry
    a large debt. Use tier (valor) as the actual prioritization criterion.
    """
    nome = nome.strip()
    for pattern in _PF_EI_PATTERNS:
        if pattern.search(nome):
            return "pessoa física/EI"
    return "empresa constituída"


def _find_header_index(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if line.startswith(HEADER_MARKER):
            return i
    raise ValueError(
        "Cabeçalho 'CPF/CNPJ' não encontrado — este arquivo não parece ser um "
        "export da Lista de Devedores da PGFN."
    )


def parse_pgfn_csv(path: str, encoding: str = "latin-1") -> list[PgfnDebtor]:
    with open(path, encoding=encoding) as f:
        lines = f.readlines()

    header_idx = _find_header_index(lines)
    reader = csv.DictReader(lines[header_idx:], delimiter=";")

    debtors = []
    for row in reader:
        cnpj = (row.get("CPF/CNPJ") or "").strip()
        if not cnpj:
            continue
        razao_social = (row.get("Nome") or "").strip()
        nome_fantasia = (row.get("Nome Fantasia") or "").strip() or None
        valor_selecionado = parse_brl_number(row.get("Valor da Dívida Selecionada", "0"))
        valor_total = parse_brl_number(row.get("Valor Total", "0"))

        debtors.append(
            PgfnDebtor(
                cnpj=cnpj,
                razao_social=razao_social,
                nome_fantasia=nome_fantasia,
                valor_selecionado=valor_selecionado,
                valor_total=valor_total,
                tipo_registro=classify_registro(razao_social),
                tier=assign_tier(valor_selecionado),
            )
        )
    return debtors


def summarize_by_tier(debtors: list[PgfnDebtor]) -> dict[str, dict]:
    summary = {tier: {"count": 0, "total_valor": 0.0} for tier, _ in TIER_THRESHOLDS}
    for debtor in debtors:
        summary[debtor.tier]["count"] += 1
        summary[debtor.tier]["total_valor"] += debtor.valor_selecionado
    return summary


def pareto_concentration(debtors: list[PgfnDebtor], tier: str = "A") -> tuple[float, float]:
    """Returns (% das empresas, % da dívida) concentrados no tier informado."""
    total_count = len(debtors)
    total_valor = sum(d.valor_selecionado for d in debtors)
    if total_count == 0 or total_valor == 0:
        return 0.0, 0.0

    tier_debtors = [d for d in debtors if d.tier == tier]
    pct_empresas = len(tier_debtors) / total_count * 100
    pct_valor = sum(d.valor_selecionado for d in tier_debtors) / total_valor * 100
    return pct_empresas, pct_valor

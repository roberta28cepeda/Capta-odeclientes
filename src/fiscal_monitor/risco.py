"""Score de risco (0-100) por CNPJ — adaptado do protótipo "Fiscalis"
(projeto Node/TypeScript enviado pelo usuário, nunca rodado em produção;
aqui reescrito em Python, usando o schema e storage que já existem no
Capta). Combina obrigação fiscal atrasada e situação das certidões por
órgão (federal sempre; SP/RJ conforme a UF do CNPJ).

Pontuação (igual ao protótipo original):
- Obrigação pendente em atraso: +35 cada, máximo 70.
- Certidão ausente: +10.
- Certidão vencendo (≤15 dias): +15.
- Certidão vencida: +30.
Urgência: Alto a partir de 70, Médio a partir de 30, Baixo abaixo disso.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.fiscal_monitor.models import Certidao, Obrigacao

ORGAOS_POR_UF = {"SP": ["federal", "sp"], "RJ": ["federal", "rj"]}
_ORGAOS_PADRAO = ["federal"]


def orgaos_exigidos(uf: str | None) -> list[str]:
    return ORGAOS_POR_UF.get((uf or "").upper(), _ORGAOS_PADRAO)


def certidao_status(valida_ate: str, hoje: date | None = None) -> str:
    hoje = hoje or date.today()
    dias = (date.fromisoformat(valida_ate) - hoje).days
    if dias < 0:
        return "vencida"
    if dias <= 15:
        return "vencendo"
    return "valida"


@dataclass
class ScoreRisco:
    score: int
    urgencia: str  # "Alto", "Médio" ou "Baixo"
    pendencias: list[str]


def calcular_score_risco(
    uf: str | None,
    obrigacoes: list[Obrigacao],
    certidoes_por_orgao: dict[str, Certidao],
    hoje: date | None = None,
) -> ScoreRisco:
    hoje = hoje or date.today()
    pendencias: list[str] = []

    atrasadas = [o for o in obrigacoes if o.status == "pendente" and date.fromisoformat(o.vencimento) < hoje]
    score = min(70, len(atrasadas) * 35)
    pendencias.extend(f"{o.tipo} em atraso" for o in atrasadas)

    for orgao in orgaos_exigidos(uf):
        certidao = certidoes_por_orgao.get(orgao)
        if certidao is None:
            score += 10
            pendencias.append(f"Certidão {orgao.upper()} ausente")
            continue
        status = certidao_status(certidao.valida_ate, hoje)
        if status == "vencida":
            score += 30
            pendencias.append(f"Certidão {orgao.upper()} vencida")
        elif status == "vencendo":
            score += 15
            pendencias.append(f"Certidão {orgao.upper()} vencendo")

    score = min(100, score)
    urgencia = "Alto" if score >= 70 else "Médio" if score >= 30 else "Baixo"
    return ScoreRisco(score=score, urgencia=urgencia, pendencias=pendencias or ["Sem pendências"])

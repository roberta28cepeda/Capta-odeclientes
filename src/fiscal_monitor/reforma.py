"""Simulador ILUSTRATIVO da Reforma Tributária (Simples Unificado ×
Híbrido) — adaptado do protótipo "Fiscalis" enviado pelo usuário.

As alíquotas abaixo são placeholders, não valores oficiais — substitua
pelas tabelas oficiais (LC 214/2025 e regulamentação do Simples) e valide
com um contador antes de usar com cliente de verdade. Esse aviso também
sai no resultado, pra nunca aparecer desacompanhado dele.
"""

from __future__ import annotations

from dataclasses import dataclass

UNIFICADO_PCT = 6.35
HIBRIDO_DAS_PCT = 5.85
HIBRIDO_IVA_PCT = 0.45

FATURAMENTO_MINIMO = 360_000.0
FATURAMENTO_MAXIMO = 4_800_000.0

AVISO = "Valores ilustrativos (placeholders), não use para cálculo real nem para orientar cliente sem validar com um contador."


@dataclass
class SimulacaoReforma:
    faturamento: float
    unificado: float
    hibrido: float
    melhor: str  # "unificado" ou "hibrido"
    diferenca: float
    aviso: str = AVISO


def simular(faturamento: float) -> SimulacaoReforma:
    unificado = faturamento * UNIFICADO_PCT / 100
    hibrido = faturamento * (HIBRIDO_DAS_PCT + HIBRIDO_IVA_PCT) / 100
    melhor = "hibrido" if hibrido < unificado else "unificado"
    return SimulacaoReforma(
        faturamento=faturamento, unificado=unificado, hibrido=hibrido, melhor=melhor,
        diferenca=abs(unificado - hibrido),
    )

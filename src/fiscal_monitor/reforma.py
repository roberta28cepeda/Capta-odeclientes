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
    # Campos abaixo só detalham os mesmos dois números acima (nenhuma conta
    # nova) — sem eles, a página só mostrava o total de cada regime, sem
    # explicar de onde vinha nem dar pra comparar num valor que faça
    # sentido no dia a dia de quem está decidindo (mensal, não anual).
    faturamento_mensal: float = 0.0
    unificado_mensal: float = 0.0
    hibrido_mensal: float = 0.0
    hibrido_das: float = 0.0
    hibrido_das_mensal: float = 0.0
    hibrido_iva: float = 0.0
    hibrido_iva_mensal: float = 0.0
    diferenca_mensal: float = 0.0
    diferenca_pct: float = 0.0


def simular(faturamento: float) -> SimulacaoReforma:
    unificado = faturamento * UNIFICADO_PCT / 100
    hibrido_das = faturamento * HIBRIDO_DAS_PCT / 100
    hibrido_iva = faturamento * HIBRIDO_IVA_PCT / 100
    hibrido = hibrido_das + hibrido_iva
    melhor = "hibrido" if hibrido < unificado else "unificado"
    diferenca = abs(unificado - hibrido)
    maior = max(unificado, hibrido)
    return SimulacaoReforma(
        faturamento=faturamento, unificado=unificado, hibrido=hibrido, melhor=melhor, diferenca=diferenca,
        faturamento_mensal=faturamento / 12, unificado_mensal=unificado / 12, hibrido_mensal=hibrido / 12,
        hibrido_das=hibrido_das, hibrido_das_mensal=hibrido_das / 12,
        hibrido_iva=hibrido_iva, hibrido_iva_mensal=hibrido_iva / 12,
        diferenca_mensal=diferenca / 12, diferenca_pct=(diferenca / maior * 100) if maior else 0.0,
    )

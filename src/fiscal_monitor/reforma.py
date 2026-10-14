"""Simulador ILUSTRATIVO da Reforma Tributária (Simples Unificado ×
Híbrido) — adaptado do protótipo "Fiscalis" enviado pelo usuário.

A alíquota do "Simples Unificado" (UNIFICADO_PCT) é placeholder — a
regulamentação final de como CBS/IBS entram no DAS unificado ainda está
em tramitação, não dá pra saber o número real hoje. Já a parte de DAS do
"Híbrido" usa a tabela REAL e vigente do Simples Nacional, Anexo III (LC
123/2006, com a redação da LC 155/2016) — não é placeholder, é a mesma
conta que vale hoje pra quem já está no Simples. A parte de CBS/IBS "por
fora" do Híbrido (HIBRIDO_IVA_PCT) continua placeholder, pelo mesmo
motivo do Unificado. Substitua o que for placeholder pelas tabelas
oficiais da reforma assim que saírem, e valide com um contador antes de
usar com cliente de verdade — esse aviso também sai no resultado, pra
nunca aparecer desacompanhado dele.
"""

from __future__ import annotations

from dataclasses import dataclass

UNIFICADO_PCT = 6.35
HIBRIDO_IVA_PCT = 0.45

# Simples Nacional, Anexo III (serviços em geral — locação de bens móveis e
# prestação de serviços não listados nos Anexos IV/V) — tabela vigente desde
# 2018 (LC 155/2016), por faixa de RBT12 (receita bruta dos últimos 12
# meses): (limite superior da faixa, alíquota nominal, valor a deduzir).
# Alíquota efetiva = (RBT12 × alíquota nominal − valor a deduzir) / RBT12.
# Usamos Anexo III como referência geral porque é o mais comum entre os
# tipos de negócio que a Leactis atende — uma empresa de comércio (Anexo I)
# ou que preste serviço dos Anexos IV/V paga por uma tabela diferente, mas
# isso exigiria saber a atividade de cada CNPJ, que este simulador não tem.
ANEXO_III_FAIXAS: list[tuple[float, float, float]] = [
    (180_000.00, 0.06, 0.00),
    (360_000.00, 0.112, 9_360.00),
    (720_000.00, 0.135, 17_640.00),
    (1_800_000.00, 0.16, 35_640.00),
    (3_600_000.00, 0.21, 125_640.00),
    (4_800_000.00, 0.33, 557_640.00),
]

FATURAMENTO_MINIMO = 360_000.0
FATURAMENTO_MAXIMO = 4_800_000.0

AVISO = (
    "A parte de DAS usa a tabela real do Simples Nacional (Anexo III); o restante "
    "(Simples Unificado e CBS/IBS do Híbrido) ainda é placeholder — a regulamentação final da "
    "reforma está em tramitação. Não use para cálculo real nem para orientar cliente sem validar "
    "com um contador."
)


def _aliquota_efetiva_simples(rbt12: float, faixas: list[tuple[float, float, float]]) -> float:
    """Fórmula oficial do Simples Nacional: acha a faixa pelo RBT12 (receita
    dos últimos 12 meses — aqui, o próprio faturamento anual informado) e
    aplica (RBT12 × alíquota nominal − valor a deduzir) / RBT12. Acima do
    limite máximo da última faixa, usa a própria última faixa (mesma regra
    oficial pra quem está no limite do Simples)."""
    if rbt12 <= 0:
        return 0.0
    for limite, aliquota_nominal, deducao in faixas:
        if rbt12 <= limite:
            return max(0.0, (rbt12 * aliquota_nominal - deducao) / rbt12)
    _, aliquota_nominal, deducao = faixas[-1]
    return max(0.0, (rbt12 * aliquota_nominal - deducao) / rbt12)


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
    # Alíquota efetiva do DAS pro faturamento informado (Anexo III) — varia
    # por faixa, diferente da UNIFICADO_PCT/HIBRIDO_IVA_PCT que são fixas.
    hibrido_das_aliquota_pct: float = 0.0


def simular(faturamento: float) -> SimulacaoReforma:
    unificado = faturamento * UNIFICADO_PCT / 100
    aliquota_das = _aliquota_efetiva_simples(faturamento, ANEXO_III_FAIXAS)
    hibrido_das = faturamento * aliquota_das
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
        hibrido_das_aliquota_pct=aliquota_das * 100,
    )

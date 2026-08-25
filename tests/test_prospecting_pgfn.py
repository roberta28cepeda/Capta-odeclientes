import os
import tempfile

import pytest

from src.prospecting.pgfn import (
    PgfnDebtor,
    assign_tier,
    classify_registro,
    pareto_concentration,
    parse_brl_number,
    parse_pgfn_csv,
    summarize_by_tier,
)

SAMPLE_CSV = """Lista de Devedores - PGFN


Filtros Utilizados:
"Estado: RJ"


Data da pesquisa: 24/08/2026 10:43


CPF/CNPJ;Nome;Nome Fantasia;Valor Total;Valor da Dívida Selecionada
"04.117.803/0001-81";"TRIUNFER TRANSPORTES LTDA";"Triunfer";"1.700.000,00";"800.000,00"
"11.222.333/0001-44";"CONTABIL EXEMPLO LTDA";"";"180.000,00";"150.000,00"
"55.666.777/0001-88";"POSTO BOA VIAGEM LTDA";"Posto Boa Viagem";"60.000,00";"45.000,00"
"98765432109";"JOAO DA SILVA 98765432109";"";"15.000,00";"12.000,00"
"""


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("70.316.092,50", 70316092.50),
        ("1.234", 1234.0),
        ("500,00", 500.0),
        ("0", 0.0),
        ("", 0.0),
        ("   ", 0.0),
    ],
)
def test_parse_brl_number(raw, expected):
    assert parse_brl_number(raw) == expected


@pytest.mark.parametrize(
    "valor,expected_tier",
    [
        (800_000, "A"),
        (500_000, "A"),
        (499_999.99, "B"),
        (100_000, "B"),
        (99_999.99, "C"),
        (20_000, "C"),
        (19_999.99, "D"),
        (0, "D"),
    ],
)
def test_assign_tier_boundaries(valor, expected_tier):
    assert assign_tier(valor) == expected_tier


@pytest.mark.parametrize(
    "nome,expected",
    [
        ("JOAO DA SILVA 98765432109", "pessoa física/EI"),
        ("12.345.678 MARIA OLIVEIRA", "pessoa física/EI"),
        ("TRIUNFER TRANSPORTES LTDA", "empresa constituída"),
        ("CONTABIL EXEMPLO LTDA", "empresa constituída"),
    ],
)
def test_classify_registro(nome, expected):
    assert classify_registro(nome) == expected


def test_parse_pgfn_csv_skips_preamble_and_parses_rows():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "devedores.csv")
        with open(path, "w", encoding="latin-1") as f:
            f.write(SAMPLE_CSV)

        debtors = parse_pgfn_csv(path)

    assert len(debtors) == 4
    triunfer = debtors[0]
    assert triunfer == PgfnDebtor(
        cnpj="04.117.803/0001-81",
        razao_social="TRIUNFER TRANSPORTES LTDA",
        nome_fantasia="Triunfer",
        valor_selecionado=800_000.0,
        valor_total=1_700_000.0,
        tipo_registro="empresa constituída",
        tier="A",
    )

    ei_row = debtors[3]
    assert ei_row.tipo_registro == "pessoa física/EI"
    assert ei_row.nome_fantasia is None
    assert ei_row.tier == "D"


def test_parse_pgfn_csv_raises_on_missing_header():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "not_pgfn.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("nome,idade\nfulano,30\n")

        with pytest.raises(ValueError, match="CPF/CNPJ"):
            parse_pgfn_csv(path)


def _sample_debtors() -> list[PgfnDebtor]:
    return [
        PgfnDebtor("1", "A LTDA", None, 800_000.0, 800_000.0, "empresa constituída", "A"),
        PgfnDebtor("2", "B LTDA", None, 150_000.0, 150_000.0, "empresa constituída", "B"),
        PgfnDebtor("3", "C LTDA", None, 45_000.0, 45_000.0, "empresa constituída", "C"),
        PgfnDebtor("4", "D LTDA", None, 12_000.0, 12_000.0, "empresa constituída", "D"),
    ]


def test_summarize_by_tier_counts_and_totals():
    summary = summarize_by_tier(_sample_debtors())

    assert summary["A"] == {"count": 1, "total_valor": 800_000.0}
    assert summary["D"] == {"count": 1, "total_valor": 12_000.0}


def test_pareto_concentration_for_tier_a():
    debtors = _sample_debtors()
    total_valor = 800_000.0 + 150_000.0 + 45_000.0 + 12_000.0

    pct_empresas, pct_valor = pareto_concentration(debtors, tier="A")

    assert pct_empresas == pytest.approx(25.0)
    assert pct_valor == pytest.approx(800_000.0 / total_valor * 100)


def test_pareto_concentration_handles_empty_list():
    assert pareto_concentration([], tier="A") == (0.0, 0.0)

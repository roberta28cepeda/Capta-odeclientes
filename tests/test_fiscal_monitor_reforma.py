from src.fiscal_monitor.reforma import simular


def test_simular_calculates_unificado_e_hibrido():
    resultado = simular(1_000_000.0)

    assert resultado.faturamento == 1_000_000.0
    assert round(resultado.unificado, 2) == 63_500.0
    assert round(resultado.hibrido, 2) == 63_000.0


def test_simular_picks_melhor_opcao():
    resultado = simular(1_000_000.0)
    assert resultado.melhor == "hibrido"  # 6.30% < 6.35%
    assert round(resultado.diferenca, 2) == round(abs(resultado.unificado - resultado.hibrido), 2)


def test_simular_includes_aviso_de_valores_ilustrativos():
    resultado = simular(500_000.0)
    assert "ilustrativos" in resultado.aviso.lower()
    assert "não use" in resultado.aviso.lower()


def test_simular_handles_zero_faturamento():
    resultado = simular(0.0)
    assert resultado.unificado == 0.0
    assert resultado.hibrido == 0.0
    assert resultado.diferenca == 0.0
    assert resultado.diferenca_pct == 0.0


def test_simular_includes_breakdown_mensal():
    resultado = simular(1_200_000.0)

    assert round(resultado.faturamento_mensal, 2) == 100_000.0
    assert round(resultado.unificado_mensal, 2) == round(resultado.unificado / 12, 2)
    assert round(resultado.hibrido_mensal, 2) == round(resultado.hibrido / 12, 2)
    assert round(resultado.diferenca_mensal, 2) == round(resultado.diferenca / 12, 2)


def test_simular_breaks_down_hibrido_em_das_e_iva():
    resultado = simular(1_000_000.0)

    assert round(resultado.hibrido_das, 2) == 58_500.0
    assert round(resultado.hibrido_iva, 2) == 4_500.0
    assert round(resultado.hibrido_das + resultado.hibrido_iva, 2) == round(resultado.hibrido, 2)


def test_simular_calcula_diferenca_pct():
    resultado = simular(1_000_000.0)

    maior = max(resultado.unificado, resultado.hibrido)
    assert round(resultado.diferenca_pct, 2) == round(resultado.diferenca / maior * 100, 2)

from src.fiscal_monitor.reforma import ANEXO_III_FAIXAS, _aliquota_efetiva_simples, simular


def test_simular_calculates_unificado_e_hibrido():
    resultado = simular(1_000_000.0)

    assert resultado.faturamento == 1_000_000.0
    assert round(resultado.unificado, 2) == 63_500.0
    # DAS (Anexo III, faixa 4: 16% - R$ 35.640,00) + CBS/IBS por fora (0,45%)
    assert round(resultado.hibrido, 2) == 128_860.0


def test_simular_picks_melhor_opcao():
    resultado = simular(1_000_000.0)
    # Nesse faturamento o DAS progressivo (Anexo III) já é mais caro que o
    # Unificado — diferente da versão antiga com DAS fixo em 5,85%, onde o
    # Híbrido ganhava sempre, não importava o faturamento.
    assert resultado.melhor == "unificado"
    assert round(resultado.diferenca, 2) == round(abs(resultado.unificado - resultado.hibrido), 2)


def test_simular_includes_aviso_de_placeholder():
    resultado = simular(500_000.0)
    assert "placeholder" in resultado.aviso.lower()
    assert "não use" in resultado.aviso.lower()


def test_simular_handles_zero_faturamento():
    resultado = simular(0.0)
    assert resultado.unificado == 0.0
    assert resultado.hibrido == 0.0
    assert resultado.diferenca == 0.0
    assert resultado.diferenca_pct == 0.0
    assert resultado.hibrido_das_aliquota_pct == 0.0


def test_simular_includes_breakdown_mensal():
    resultado = simular(1_200_000.0)

    assert round(resultado.faturamento_mensal, 2) == 100_000.0
    assert round(resultado.unificado_mensal, 2) == round(resultado.unificado / 12, 2)
    assert round(resultado.hibrido_mensal, 2) == round(resultado.hibrido / 12, 2)
    assert round(resultado.diferenca_mensal, 2) == round(resultado.diferenca / 12, 2)


def test_simular_breaks_down_hibrido_em_das_e_iva():
    resultado = simular(1_000_000.0)

    assert round(resultado.hibrido_das, 2) == 124_360.0
    assert round(resultado.hibrido_iva, 2) == 4_500.0
    assert round(resultado.hibrido_das + resultado.hibrido_iva, 2) == round(resultado.hibrido, 2)
    assert round(resultado.hibrido_das_aliquota_pct, 3) == 12.436


def test_simular_calcula_diferenca_pct():
    resultado = simular(1_000_000.0)

    maior = max(resultado.unificado, resultado.hibrido)
    assert round(resultado.diferenca_pct, 2) == round(resultado.diferenca / maior * 100, 2)


def test_simular_diferenca_varia_de_verdade_com_o_faturamento():
    """Antes, com o DAS fixo em 5,85%, a diferença entre os dois regimes era
    sempre ~0,79% do valor, não importava o faturamento — a "simulação" não
    simulava nada de verdade. Com o DAS progressivo (Anexo III), a diferença
    cresce de verdade conforme o faturamento sobe de faixa."""
    baixo = simular(150_000.0)
    alto = simular(1_000_000.0)

    assert round(baixo.hibrido_das_aliquota_pct, 2) == 6.0  # 1ª faixa, flat
    assert baixo.diferenca_pct < 5.0
    assert alto.diferenca_pct > 40.0
    assert alto.diferenca_pct > baixo.diferenca_pct * 5


def test_aliquota_efetiva_simples_eh_continua_nas_fronteiras_das_faixas():
    """Verificação clássica de tabela do Simples Nacional: a alíquota
    efetiva não pode "saltar" de uma faixa pra outra — tem que ser
    contínua no limite entre faixas (senão a tabela de dedução está errada).
    """
    for limite, _, _ in ANEXO_III_FAIXAS[:-1]:
        abaixo = _aliquota_efetiva_simples(limite, ANEXO_III_FAIXAS)
        acima = _aliquota_efetiva_simples(limite + 0.01, ANEXO_III_FAIXAS)
        assert abs(abaixo - acima) < 0.0001


def test_aliquota_efetiva_simples_usa_ultima_faixa_acima_do_limite_maximo():
    no_limite = _aliquota_efetiva_simples(4_800_000.0, ANEXO_III_FAIXAS)
    acima_do_limite = _aliquota_efetiva_simples(5_000_000.0, ANEXO_III_FAIXAS)
    assert round(acima_do_limite, 4) == round((5_000_000.0 * 0.33 - 557_640.0) / 5_000_000.0, 4)
    assert acima_do_limite > no_limite  # alíquota continua subindo acima do teto do Simples


def test_aliquota_efetiva_simples_handles_zero():
    assert _aliquota_efetiva_simples(0.0, ANEXO_III_FAIXAS) == 0.0

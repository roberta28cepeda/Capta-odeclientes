from datetime import date

from src.fiscal_monitor.models import Certidao, Obrigacao
from src.fiscal_monitor.risco import calcular_score_risco, certidao_status, orgaos_exigidos

HOJE = date(2026, 10, 1)


def _obrigacao(tipo="DAS", vencimento="2026-09-01", status="pendente"):
    return Obrigacao(id=1, cnpj_id=1, tipo=tipo, vencimento=vencimento, status=status)


def _certidao(orgao="federal", valida_ate="2027-01-01"):
    return Certidao(
        id=1, cnpj_id=1, orgao=orgao, numero=None, emitida_em="2026-01-01", valida_ate=valida_ate,
        arquivo_nome="x.pdf", criado_em="2026-01-01",
    )


def test_orgaos_exigidos_sp_includes_federal_and_sp():
    assert orgaos_exigidos("SP") == ["federal", "sp"]


def test_orgaos_exigidos_rj_includes_federal_and_rj():
    assert orgaos_exigidos("RJ") == ["federal", "rj"]


def test_orgaos_exigidos_outras_uf_only_federal():
    assert orgaos_exigidos("MG") == ["federal"]
    assert orgaos_exigidos(None) == ["federal"]


def test_certidao_status_vencida():
    assert certidao_status("2026-09-01", hoje=HOJE) == "vencida"


def test_certidao_status_vencendo_within_15_days():
    assert certidao_status("2026-10-10", hoje=HOJE) == "vencendo"


def test_certidao_status_valida_beyond_15_days():
    assert certidao_status("2027-01-01", hoje=HOJE) == "valida"


def test_calcular_score_risco_sem_pendencias_is_baixo():
    resultado = calcular_score_risco("MG", [], {"federal": _certidao()}, hoje=HOJE)
    assert resultado.score == 0
    assert resultado.urgencia == "Baixo"
    assert resultado.pendencias == ["Sem pendências"]


def test_calcular_score_risco_obrigacao_atrasada():
    obrigacoes = [_obrigacao(vencimento="2026-09-01")]
    resultado = calcular_score_risco("MG", obrigacoes, {"federal": _certidao()}, hoje=HOJE)
    assert resultado.score == 35
    assert "DAS em atraso" in resultado.pendencias


def test_calcular_score_risco_obrigacao_entregue_nao_conta():
    obrigacoes = [_obrigacao(vencimento="2026-09-01", status="entregue")]
    resultado = calcular_score_risco("MG", obrigacoes, {"federal": _certidao()}, hoje=HOJE)
    assert resultado.score == 0


def test_calcular_score_risco_obrigacao_futura_nao_conta():
    obrigacoes = [_obrigacao(vencimento="2026-12-01")]
    resultado = calcular_score_risco("MG", obrigacoes, {"federal": _certidao()}, hoje=HOJE)
    assert resultado.score == 0


def test_calcular_score_risco_limita_obrigacoes_em_70():
    obrigacoes = [_obrigacao(tipo=f"DAS{i}", vencimento="2026-09-01") for i in range(5)]
    resultado = calcular_score_risco("MG", obrigacoes, {"federal": _certidao()}, hoje=HOJE)
    assert resultado.score == 70


def test_calcular_score_risco_certidao_ausente():
    resultado = calcular_score_risco("SP", [], {}, hoje=HOJE)
    assert resultado.score == 20  # federal (10) + sp (10) ausentes
    assert "Certidão FEDERAL ausente" in resultado.pendencias
    assert "Certidão SP ausente" in resultado.pendencias


def test_calcular_score_risco_certidao_vencida():
    resultado = calcular_score_risco("MG", [], {"federal": _certidao(valida_ate="2026-09-01")}, hoje=HOJE)
    assert resultado.score == 30
    assert "Certidão FEDERAL vencida" in resultado.pendencias


def test_calcular_score_risco_certidao_vencendo():
    resultado = calcular_score_risco("MG", [], {"federal": _certidao(valida_ate="2026-10-10")}, hoje=HOJE)
    assert resultado.score == 15
    assert "Certidão FEDERAL vencendo" in resultado.pendencias


def test_calcular_score_risco_urgencia_alto_a_partir_de_70():
    obrigacoes = [_obrigacao(tipo=f"DAS{i}", vencimento="2026-09-01") for i in range(2)]
    resultado = calcular_score_risco("SP", obrigacoes, {}, hoje=HOJE)
    assert resultado.score == 90  # 70 (obrigações, limitado) + 10 + 10 (certidões ausentes)
    assert resultado.score == min(100, 90)
    assert resultado.urgencia == "Alto"


def test_calcular_score_risco_nunca_passa_de_100():
    obrigacoes = [_obrigacao(tipo=f"DAS{i}", vencimento="2026-09-01") for i in range(5)]
    certidoes = {"federal": _certidao(valida_ate="2026-09-01"), "sp": _certidao(orgao="sp", valida_ate="2026-09-01")}
    resultado = calcular_score_risco("SP", obrigacoes, certidoes, hoje=HOJE)
    assert resultado.score == 100

from unittest.mock import MagicMock

import pytest

from src.fiscal_monitor.preanalise import (
    ConsultaCnpjError,
    consultar_cnpj_publico,
    gerar_alertas,
    montar_pre_analise,
    only_digits,
)

SAMPLE_RESPONSE = {
    "cnpj": "11222333000144",
    "razao_social": "CONTABIL EXEMPLO LTDA",
    "nome_fantasia": "Contabil Exemplo",
    "descricao_situacao_cadastral": "ATIVA",
    "data_situacao_cadastral": "2010-01-01",
    "natureza_juridica": "206-2 - Sociedade Empresária Limitada",
    "cnae_fiscal_descricao": "Atividades de contabilidade",
    "descricao_porte": "ME",
    "uf": "SP",
    "municipio": "SAO PAULO",
    "data_inicio_atividade": "2010-01-01",
    "opcao_pelo_simples": True,
    "opcao_pelo_mei": False,
    "capital_social": 50000,
    "qsa": [{"nome_socio": "Fulano de Tal"}, {"nome_socio": "Ciclana da Silva"}],
}


def _mock_response(status_code=200, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    return response


def test_only_digits_strips_punctuation():
    assert only_digits("11.222.333/0001-44") == "11222333000144"


def test_consultar_cnpj_publico_returns_json():
    session = MagicMock()
    session.get.return_value = _mock_response(200, SAMPLE_RESPONSE)

    dados = consultar_cnpj_publico("11.222.333/0001-44", session=session)

    assert dados == SAMPLE_RESPONSE
    call_args, _ = session.get.call_args
    assert call_args[0] == "https://brasilapi.com.br/api/cnpj/v1/11222333000144"


def test_consultar_cnpj_publico_raises_on_404():
    session = MagicMock()
    session.get.return_value = _mock_response(404)

    with pytest.raises(ConsultaCnpjError, match="não encontrado"):
        consultar_cnpj_publico("00.000.000/0000-00", session=session)


def test_consultar_cnpj_publico_raises_on_server_error():
    session = MagicMock()
    session.get.return_value = _mock_response(500)

    with pytest.raises(ConsultaCnpjError, match="HTTP 500"):
        consultar_cnpj_publico("11.222.333/0001-44", session=session)


def test_montar_pre_analise_parses_fields_and_socios():
    analise = montar_pre_analise(SAMPLE_RESPONSE)

    assert analise.razao_social == "CONTABIL EXEMPLO LTDA"
    assert analise.situacao_cadastral == "ATIVA"
    assert analise.opcao_pelo_simples is True
    assert analise.opcao_pelo_mei is False
    assert analise.socios == ["Fulano de Tal", "Ciclana da Silva"]


def test_montar_pre_analise_tolerates_missing_fields():
    analise = montar_pre_analise({"cnpj": "123", "razao_social": "Vazio LTDA"})

    assert analise.situacao_cadastral is None
    assert analise.opcao_pelo_simples is None
    assert analise.socios == []


def test_gerar_alertas_flags_situacao_nao_ativa():
    analise = montar_pre_analise({**SAMPLE_RESPONSE, "descricao_situacao_cadastral": "SUSPENSA"})

    alertas = gerar_alertas(analise)

    assert any("SUSPENSA" in a for a in alertas)


def test_gerar_alertas_flags_me_fora_do_simples():
    analise = montar_pre_analise({**SAMPLE_RESPONSE, "opcao_pelo_simples": False})

    alertas = gerar_alertas(analise)

    assert any("Simples Nacional" in a for a in alertas)


def test_gerar_alertas_no_findings_when_ativa_and_optante():
    analise = montar_pre_analise(SAMPLE_RESPONSE)

    alertas = gerar_alertas(analise)

    assert alertas == ["Nenhum alerta cadastral identificado na pré-análise pública."]

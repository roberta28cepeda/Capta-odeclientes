from unittest.mock import MagicMock

import pytest
import requests

from src.fiscal_monitor.preanalise import (
    CartaoCnpjError,
    ConsultaCnpjError,
    buscar_cartao_cnpj_pdf,
    consultar_cnpj_cnpja,
    consultar_cnpj_publico,
    gerar_alertas,
    montar_pre_analise,
    montar_pre_analise_cnpja,
    only_digits,
    validar_cnpj,
)

SAMPLE_CNPJA_RESPONSE = {
    "taxId": "11222333000144",
    "alias": "Contabil Exemplo",
    "founded": "2010-01-01",
    "company": {
        "name": "CONTABIL EXEMPLO LTDA",
        "equity": 50000,
        "nature": {"text": "Sociedade Empresária Limitada"},
        "size": {"text": "ME"},
        "simples": {"optant": True},
        "simei": {"optant": False},
        "members": [
            {"person": {"name": "Fulano de Tal"}},
            {"person": {"name": "Ciclana da Silva"}},
        ],
    },
    "status": {"text": "Ativa"},
    "statusDate": "2010-01-01",
    "address": {"state": "SP", "city": "SAO PAULO"},
    "mainActivity": {"text": "Atividades de contabilidade"},
}

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


@pytest.mark.parametrize(
    "cnpj,esperado",
    [
        ("33.000.167/0001-01", True),  # Petrobras — CNPJ público real, dígitos válidos
        ("11.222.333/0001-81", True),
        ("11.111.111/1111-11", False),  # todos os dígitos iguais
        ("11.222.333/0001-99", False),  # dígito verificador errado
        ("00.000.000/0000-00", False),
        ("123", False),  # tamanho errado
    ],
)
def test_validar_cnpj(cnpj, esperado):
    assert validar_cnpj(cnpj) is esperado


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


def test_consultar_cnpj_publico_raises_on_connection_error():
    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError("sem rede")

    with pytest.raises(ConsultaCnpjError, match="Falha de conexão"):
        consultar_cnpj_publico("11.222.333/0001-44", session=session)


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


def test_consultar_cnpj_cnpja_sends_token_header_and_returns_json():
    session = MagicMock()
    session.get.return_value = _mock_response(200, SAMPLE_CNPJA_RESPONSE)

    dados = consultar_cnpj_cnpja("11.222.333/0001-44", "TOKEN123", session=session)

    assert dados == SAMPLE_CNPJA_RESPONSE
    call_args, call_kwargs = session.get.call_args
    assert call_args[0] == "https://api.cnpja.com/office/11222333000144"
    assert call_kwargs["headers"] == {"Authorization": "TOKEN123"}


def test_consultar_cnpj_cnpja_raises_on_404():
    session = MagicMock()
    session.get.return_value = _mock_response(404)

    with pytest.raises(ConsultaCnpjError, match="não encontrado na CNPJá"):
        consultar_cnpj_cnpja("00.000.000/0000-00", "TOKEN123", session=session)


def test_consultar_cnpj_cnpja_raises_on_connection_error():
    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError("sem rede")

    with pytest.raises(ConsultaCnpjError, match="Falha de conexão"):
        consultar_cnpj_cnpja("11.222.333/0001-44", "TOKEN123", session=session)


def test_montar_pre_analise_cnpja_parses_fields_and_socios():
    analise = montar_pre_analise_cnpja(SAMPLE_CNPJA_RESPONSE)

    assert analise.razao_social == "CONTABIL EXEMPLO LTDA"
    assert analise.situacao_cadastral == "Ativa"
    assert analise.opcao_pelo_simples is True
    assert analise.opcao_pelo_mei is False
    assert analise.socios == ["Fulano de Tal", "Ciclana da Silva"]
    assert analise.uf == "SP"


def test_montar_pre_analise_cnpja_tolerates_missing_fields():
    analise = montar_pre_analise_cnpja({"taxId": "123"})

    assert analise.razao_social == ""
    assert analise.situacao_cadastral is None
    assert analise.socios == []


def test_buscar_cartao_cnpj_pdf_returns_bytes_on_success():
    session = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.headers = {"Content-Type": "application/pdf"}
    response.content = b"%PDF-1.4 conteudo"
    session.get.return_value = response

    pdf_bytes = buscar_cartao_cnpj_pdf("11.222.333/0001-44", "TOKEN123", session=session)

    assert pdf_bytes == b"%PDF-1.4 conteudo"
    call_args, call_kwargs = session.get.call_args
    assert call_kwargs["params"] == {"taxId": "11222333000144"}
    assert call_kwargs["headers"]["Authorization"] == "TOKEN123"


def test_buscar_cartao_cnpj_pdf_raises_when_not_pdf():
    session = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.text = '{"error": "cota esgotada"}'
    session.get.return_value = response

    with pytest.raises(CartaoCnpjError, match="Não foi possível obter"):
        buscar_cartao_cnpj_pdf("11.222.333/0001-44", "TOKEN123", session=session)


def test_buscar_cartao_cnpj_pdf_raises_on_connection_error():
    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError("sem rede")

    with pytest.raises(CartaoCnpjError, match="Falha de conexão"):
        buscar_cartao_cnpj_pdf("11.222.333/0001-44", "TOKEN123", session=session)

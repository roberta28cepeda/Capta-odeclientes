from unittest.mock import MagicMock

import pytest
import requests

from src.fiscal_monitor.infosimples import (
    ConsultaDebitosError,
    consultar_cnd_federal,
    consultar_lista_devedores,
    gerar_alertas_fiscais,
    montar_divida_ativa,
    montar_situacao_fiscal,
)

SAMPLE_CND_RESPONSE = {
    "code": 200,
    "code_message": "A requisição foi processada com sucesso.",
    "errors": [],
    "header": {"service": "receita-federal/pgfn/nova"},
    "data_count": 1,
    "data": [
        {
            "certidao": "CERTIDÃO NEGATIVA DE DÉBITOS...",
            "cnpj": "11.222.333/0001-44",
            "conseguiu_emitir_certidao_negativa": True,
            "debitos_pgfn": False,
            "debitos_rfb": False,
            "mensagem": "CERTIDÃO NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E À DÍVIDA ATIVA DA UNIÃO",
            "tipo": "Negativa",
            "validade_data": "11/11/2026",
        }
    ],
}

SAMPLE_DEVEDORES_RESPONSE = {
    "code": 200,
    "code_message": "A requisição foi processada com sucesso.",
    "errors": [],
    "header": {"service": "receita-federal/pgfn/devedores"},
    "data_count": 1,
    "data": [
        {
            "cpf_cnpj": "11.222.333/0001-44",
            "nome": "Empresa Exemplo",
            "total_divida": 29544029.81,
            "total_tributario": 29535048.02,
            "total_nao_tributario": 8981.79,
            "naturezas_debitos": [
                {
                    "descricao": "FGTS",
                    "total": 29535048.02,
                    "debitos": [{"inscricao": "111111111111", "valor_divida": 16745.1}],
                },
            ],
        }
    ],
}

SAMPLE_DEVEDORES_NAO_ENCONTRADO = {
    "code": 200,
    "code_message": "A requisição foi processada com sucesso.",
    "errors": [],
    "header": {},
    "data_count": 0,
    "data": [],
}


def _mock_response(status_code=200, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    return response


def test_consultar_cnd_federal_sends_cnpj_and_token():
    session = MagicMock()
    session.post.return_value = _mock_response(200, SAMPLE_CND_RESPONSE)

    dados = consultar_cnd_federal("11.222.333/0001-44", "TOKEN123", session=session)

    assert dados["tipo"] == "Negativa"
    call_args, call_kwargs = session.post.call_args
    assert call_args[0] == "https://api.infosimples.com/api/v2/consultas/receita-federal/pgfn/nova"
    assert call_kwargs["data"]["cnpj"] == "11222333000144"
    assert call_kwargs["data"]["token"] == "TOKEN123"


def test_consultar_cnd_federal_raises_on_error_code():
    session = MagicMock()
    session.post.return_value = _mock_response(
        200, {"code": 611, "code_message": "CNPJ inválido.", "errors": ["CNPJ inválido."]}
    )

    with pytest.raises(ConsultaDebitosError, match="CNPJ inválido"):
        consultar_cnd_federal("00.000.000/0000-00", "TOKEN123", session=session)


def test_consultar_cnd_federal_raises_on_connection_error():
    session = MagicMock()
    session.post.side_effect = requests.exceptions.ConnectionError("sem rede")

    with pytest.raises(ConsultaDebitosError, match="Falha de conexão"):
        consultar_cnd_federal("11.222.333/0001-44", "TOKEN123", session=session)


def test_consultar_lista_devedores_returns_data_when_found():
    session = MagicMock()
    session.post.return_value = _mock_response(200, SAMPLE_DEVEDORES_RESPONSE)

    dados = consultar_lista_devedores("11.222.333/0001-44", "TOKEN123", session=session)

    assert dados["total_divida"] == 29544029.81


def test_consultar_lista_devedores_returns_none_when_not_found():
    session = MagicMock()
    session.post.return_value = _mock_response(200, SAMPLE_DEVEDORES_NAO_ENCONTRADO)

    dados = consultar_lista_devedores("11.222.333/0001-44", "TOKEN123", session=session)

    assert dados is None


def test_montar_situacao_fiscal_parses_fields():
    situacao = montar_situacao_fiscal(SAMPLE_CND_RESPONSE["data"][0])

    assert situacao.conseguiu_certidao_negativa is True
    assert situacao.debitos_pgfn is False
    assert situacao.debitos_rfb is False
    assert situacao.tipo_certidao == "Negativa"
    assert situacao.validade_data == "11/11/2026"


def test_montar_divida_ativa_parses_naturezas_e_debitos():
    divida = montar_divida_ativa(SAMPLE_DEVEDORES_RESPONSE["data"][0])

    assert divida.total_divida == 29544029.81
    assert divida.naturezas[0].descricao == "FGTS"
    assert divida.naturezas[0].debitos[0].inscricao == "111111111111"
    assert divida.naturezas[0].debitos[0].valor_divida == 16745.1


def test_montar_divida_ativa_returns_none_when_no_data():
    assert montar_divida_ativa(None) is None


def test_gerar_alertas_fiscais_flags_debitos_e_divida():
    situacao = montar_situacao_fiscal({"debitos_pgfn": True, "debitos_rfb": True, "tipo": "Positiva"})
    divida = montar_divida_ativa(SAMPLE_DEVEDORES_RESPONSE["data"][0])

    alertas = gerar_alertas_fiscais(situacao, divida)

    assert any("PGFN" in a for a in alertas)
    assert any("Receita Federal" in a for a in alertas)
    assert any("29.544.029,81" in a for a in alertas)


def test_gerar_alertas_fiscais_no_findings_when_clean():
    situacao = montar_situacao_fiscal(SAMPLE_CND_RESPONSE["data"][0])

    alertas = gerar_alertas_fiscais(situacao, None)

    assert alertas == []

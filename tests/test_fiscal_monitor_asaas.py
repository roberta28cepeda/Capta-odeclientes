from unittest.mock import MagicMock

import pytest
import requests

from src.fiscal_monitor.asaas import CobrancaError, consultar_cobranca, criar_cobranca, obter_ou_criar_cliente


def _mock_response(status_code=200, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body if json_body is not None else {}
    return response


def test_obter_ou_criar_cliente_reaproveita_cliente_existente():
    session = MagicMock()
    session.request.return_value = _mock_response(200, {"data": [{"id": "cus_123"}]})

    customer_id = obter_ou_criar_cliente(
        "Escritório A", "11.222.333/0001-44", "contato@escritorio.com.br", "APIKEY123", session=session
    )

    assert customer_id == "cus_123"
    session.request.assert_called_once()
    call_args = session.request.call_args
    assert call_args.args[0] == "GET"
    assert call_args.args[1] == "https://api.asaas.com/v3/customers"
    assert call_args.kwargs["params"] == {"cpfCnpj": "11222333000144"}
    assert call_args.kwargs["headers"] == {"access_token": "APIKEY123"}


def test_obter_ou_criar_cliente_cria_quando_nao_existe():
    session = MagicMock()
    session.request.side_effect = [
        _mock_response(200, {"data": []}),
        _mock_response(200, {"id": "cus_novo"}),
    ]

    customer_id = obter_ou_criar_cliente(
        "Escritório A", "11.222.333/0001-44", "contato@escritorio.com.br", "APIKEY123", session=session
    )

    assert customer_id == "cus_novo"
    assert session.request.call_count == 2
    segunda_chamada = session.request.call_args_list[1]
    assert segunda_chamada.args[0] == "POST"
    assert segunda_chamada.args[1] == "https://api.asaas.com/v3/customers"


def test_obter_ou_criar_cliente_raises_on_connection_error():
    session = MagicMock()
    session.request.side_effect = requests.exceptions.ConnectionError("sem rede")

    with pytest.raises(CobrancaError, match="Falha de conexão"):
        obter_ou_criar_cliente("Escritório A", "11.222.333/0001-44", None, "APIKEY123", session=session)


def test_criar_cobranca_envia_payload_correto():
    session = MagicMock()
    session.request.return_value = _mock_response(
        200, {"id": "pay_123", "invoiceUrl": "https://asaas.com/i/abc", "status": "PENDING"}
    )

    resultado = criar_cobranca("cus_123", 1500.0, "2026-11-05", "Honorário 2026-10", "APIKEY123", session=session)

    assert resultado["id"] == "pay_123"
    assert resultado["invoiceUrl"] == "https://asaas.com/i/abc"
    payload = session.request.call_args.kwargs["json"]
    assert payload["customer"] == "cus_123"
    assert payload["value"] == 1500.0
    assert payload["billingType"] == "UNDEFINED"


def test_criar_cobranca_raises_on_erro_http():
    session = MagicMock()
    session.request.return_value = _mock_response(
        400, {"errors": [{"description": "cliente inválido"}]}
    )

    with pytest.raises(CobrancaError, match="cliente inválido"):
        criar_cobranca("cus_123", 1500.0, "2026-11-05", "Honorário 2026-10", "APIKEY123", session=session)


def test_consultar_cobranca_retorna_dados():
    session = MagicMock()
    session.request.return_value = _mock_response(200, {"id": "pay_123", "status": "RECEIVED"})

    resultado = consultar_cobranca("pay_123", "APIKEY123", session=session)

    assert resultado["status"] == "RECEIVED"

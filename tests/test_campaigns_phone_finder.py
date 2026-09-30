from unittest.mock import MagicMock

import pytest
import requests

from src.campaigns.phone_finder import PhoneFinderError, buscar_telefone_por_cnpj


def _mock_response(status_code=200, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    return response


def test_buscar_telefone_por_cnpj_returns_first_phone():
    session = MagicMock()
    session.get.return_value = _mock_response(200, {"status": "OK", "telefone": "(11) 1234-5678 / (11) 8765-4321"})

    telefone = buscar_telefone_por_cnpj("11.222.333/0001-44", session=session)

    assert telefone == "(11) 1234-5678"
    call_args, _ = session.get.call_args
    assert call_args[0] == "https://www.receitaws.com.br/v1/cnpj/11222333000144"


def test_buscar_telefone_por_cnpj_returns_none_when_no_phone():
    session = MagicMock()
    session.get.return_value = _mock_response(200, {"status": "OK", "telefone": ""})

    assert buscar_telefone_por_cnpj("11.222.333/0001-44", session=session) is None


def test_buscar_telefone_por_cnpj_returns_none_when_not_found():
    session = MagicMock()
    session.get.return_value = _mock_response(200, {"status": "ERROR", "message": "CNPJ inválido"})

    assert buscar_telefone_por_cnpj("00.000.000/0000-00", session=session) is None


def test_buscar_telefone_por_cnpj_raises_on_rate_limit_status_code():
    session = MagicMock()
    session.get.return_value = _mock_response(429)

    with pytest.raises(PhoneFinderError, match="Limite de consultas"):
        buscar_telefone_por_cnpj("11.222.333/0001-44", session=session)


def test_buscar_telefone_por_cnpj_raises_on_rate_limit_in_body():
    session = MagicMock()
    session.get.return_value = _mock_response(
        200, {"status": "ERROR", "message": "Você atingiu o limite de 3 consultas por minuto"}
    )

    with pytest.raises(PhoneFinderError, match="Limite de consultas"):
        buscar_telefone_por_cnpj("11.222.333/0001-44", session=session)


def test_buscar_telefone_por_cnpj_raises_on_connection_error():
    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError("sem rede")

    with pytest.raises(PhoneFinderError, match="Falha de conexão"):
        buscar_telefone_por_cnpj("11.222.333/0001-44", session=session)

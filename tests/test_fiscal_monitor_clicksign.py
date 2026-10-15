from unittest.mock import MagicMock

import pytest
import requests

from src.fiscal_monitor.clicksign import (
    AssinaturaError,
    baixar_documento_assinado,
    consultar_solicitacao,
    criar_solicitacao,
)


def _mock_response(status_code=200, json_body=None, content=b""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body if json_body is not None else {}
    response.text = str(json_body or "")
    response.content = content
    return response


def test_criar_solicitacao_cria_envelope_documento_e_signatario():
    session = MagicMock()
    session.request.side_effect = [
        _mock_response(200, {"data": {"id": "env-123", "attributes": {}}}),  # criar envelope
        _mock_response(200, {"data": {"id": "doc-1"}}),  # adicionar documento
        _mock_response(200, {"data": {"id": "sig-1"}}),  # adicionar signatário
        _mock_response(200, {"data": {"id": "env-123", "attributes": {"status": "running"}}}),  # ativar
    ]

    resultado = criar_solicitacao(
        "contrato.pdf", b"conteudo-fake", "Fulano", "fulano@exemplo.com", "TOKEN123", session=session
    )

    assert resultado["envelope_id"] == "env-123"
    assert session.request.call_count == 4
    primeira_chamada = session.request.call_args_list[0]
    assert primeira_chamada.args[0] == "POST"
    assert primeira_chamada.args[1] == "https://api.clicksign.com/api/v3/envelopes"
    assert primeira_chamada.kwargs["params"] == {"access_token": "TOKEN123"}


def test_criar_solicitacao_raises_on_connection_error():
    session = MagicMock()
    session.request.side_effect = requests.exceptions.ConnectionError("sem rede")

    with pytest.raises(AssinaturaError, match="Falha de conexão"):
        criar_solicitacao("contrato.pdf", b"conteudo-fake", "Fulano", "fulano@exemplo.com", "TOKEN123", session=session)


def test_criar_solicitacao_raises_on_erro_http():
    session = MagicMock()
    session.request.return_value = _mock_response(422, {"errors": "token inválido"})

    with pytest.raises(AssinaturaError, match="422"):
        criar_solicitacao("contrato.pdf", b"conteudo-fake", "Fulano", "fulano@exemplo.com", "TOKEN123", session=session)


def test_consultar_solicitacao_retorna_atributos():
    session = MagicMock()
    session.request.return_value = _mock_response(
        200, {"data": {"id": "env-123", "attributes": {"status": "running"}}}
    )

    atributos = consultar_solicitacao("env-123", "TOKEN123", session=session)

    assert atributos["status"] == "running"


def test_baixar_documento_assinado_retorna_bytes():
    session = MagicMock()
    session.request.return_value = _mock_response(
        200,
        {"data": [{"attributes": {"downloads": {"signed_file_url": "https://clicksign.com/download/abc"}}}]},
    )
    session.get.return_value = _mock_response(200, content=b"pdf-assinado-fake")

    conteudo = baixar_documento_assinado("env-123", "TOKEN123", session=session)

    assert conteudo == b"pdf-assinado-fake"
    session.get.assert_called_once_with("https://clicksign.com/download/abc", timeout=30)


def test_baixar_documento_assinado_raises_sem_documento():
    session = MagicMock()
    session.request.return_value = _mock_response(200, {"data": []})

    with pytest.raises(AssinaturaError, match="não tem documento assinado"):
        baixar_documento_assinado("env-123", "TOKEN123", session=session)

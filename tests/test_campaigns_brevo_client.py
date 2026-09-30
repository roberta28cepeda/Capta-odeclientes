from unittest.mock import MagicMock

import pytest
import requests

from src.campaigns.brevo_client import BrevoSyncError, adicionar_contato_lista


def _mock_response(status_code=201):
    response = MagicMock()
    response.status_code = status_code
    response.text = ""
    return response


def test_adicionar_contato_lista_sends_email_and_list_id():
    session = MagicMock()
    session.post.return_value = _mock_response(201)

    adicionar_contato_lista("lead@exemplo.com", 5, "API_KEY", session=session)

    call_args, call_kwargs = session.post.call_args
    assert call_args[0] == "https://api.brevo.com/v3/contacts"
    assert call_kwargs["json"] == {"email": "lead@exemplo.com", "listIds": [5], "updateEnabled": True}
    assert call_kwargs["headers"]["api-key"] == "API_KEY"


def test_adicionar_contato_lista_raises_on_error_status():
    session = MagicMock()
    session.post.return_value = _mock_response(401)

    with pytest.raises(BrevoSyncError, match="HTTP 401"):
        adicionar_contato_lista("lead@exemplo.com", 5, "API_KEY_INVALIDA", session=session)


def test_adicionar_contato_lista_raises_on_connection_error():
    session = MagicMock()
    session.post.side_effect = requests.exceptions.ConnectionError("sem rede")

    with pytest.raises(BrevoSyncError, match="Falha de conexão"):
        adicionar_contato_lista("lead@exemplo.com", 5, "API_KEY", session=session)

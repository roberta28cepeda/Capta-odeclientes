from unittest.mock import MagicMock, patch

import pytest

from src.campaigns.email_finder import EmailFinderError, buscar_email_por_empresa


def _resposta(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def test_buscar_email_finds_email_in_search_snippet():
    session = MagicMock()
    session.get.return_value = _resposta(
        json_data={"web": {"results": [{"title": "Empresa X", "description": "Contato: contato@empresax.com.br"}]}}
    )

    email = buscar_email_por_empresa("Empresa X", "API_KEY", session=session)

    assert email == "contato@empresax.com.br"


def test_buscar_email_fetches_page_when_snippet_has_no_email():
    session = MagicMock()
    busca_resposta = _resposta(
        json_data={"web": {"results": [{"title": "Empresa X", "description": "Site oficial", "url": "https://empresax.com.br"}]}}
    )
    pagina_resposta = _resposta(text="<html>Fale conosco: contato@empresax.com.br</html>")
    session.get.side_effect = [busca_resposta, pagina_resposta]

    email = buscar_email_por_empresa("Empresa X", "API_KEY", session=session)

    assert email == "contato@empresax.com.br"


def test_buscar_email_returns_none_when_no_results():
    session = MagicMock()
    session.get.return_value = _resposta(json_data={"web": {"results": []}})

    assert buscar_email_por_empresa("Empresa Inexistente", "API_KEY", session=session) is None


def test_buscar_email_returns_none_when_no_email_found_anywhere():
    session = MagicMock()
    busca_resposta = _resposta(
        json_data={"web": {"results": [{"title": "Empresa X", "description": "Sem contato aqui", "url": "https://empresax.com.br"}]}}
    )
    session.get.side_effect = [busca_resposta, _resposta(text="<html>Nada aqui</html>")]

    assert buscar_email_por_empresa("Empresa X", "API_KEY", session=session) is None


def test_buscar_email_raises_on_quota_exceeded():
    session = MagicMock()
    session.get.return_value = _resposta(status_code=429)

    with pytest.raises(EmailFinderError, match="Cota mensal"):
        buscar_email_por_empresa("Empresa X", "API_KEY", session=session)


def test_buscar_email_raises_on_request_exception():
    import requests

    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError("falha de rede")

    with pytest.raises(EmailFinderError, match="Falha ao consultar"):
        buscar_email_por_empresa("Empresa X", "API_KEY", session=session)


def test_buscar_email_ignores_ignored_domains():
    session = MagicMock()
    session.get.return_value = _resposta(
        json_data={"web": {"results": [{"title": "Empresa X", "description": "erro@sentry.io e real@empresax.com.br"}]}}
    )

    email = buscar_email_por_empresa("Empresa X", "API_KEY", session=session)

    assert email == "real@empresax.com.br"


def test_buscar_email_sends_subscription_token_header():
    session = MagicMock()
    session.get.return_value = _resposta(json_data={"web": {"results": []}})

    buscar_email_por_empresa("Empresa X", "MINHA_CHAVE", session=session)

    _, kwargs = session.get.call_args
    assert kwargs["headers"]["X-Subscription-Token"] == "MINHA_CHAVE"

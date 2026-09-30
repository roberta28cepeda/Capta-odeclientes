from unittest.mock import MagicMock, patch

import pytest

from src.campaigns.email_finder import EmailFinderError, buscar_email_por_empresa


def _resposta(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def test_buscar_email_finds_email_in_search_text():
    session = MagicMock()
    session.post.return_value = _resposta(
        json_data={"results": [{"title": "Empresa X", "text": "Contato: contato@empresax.com.br"}]}
    )

    email = buscar_email_por_empresa("Empresa X", "API_KEY", session=session)

    assert email == "contato@empresax.com.br"


def test_buscar_email_fetches_page_when_text_has_no_email():
    session = MagicMock()
    busca_resposta = _resposta(
        json_data={"results": [{"title": "Empresa X", "text": "Site oficial", "url": "https://empresax.com.br"}]}
    )
    pagina_resposta = _resposta(text="<html>Fale conosco: contato@empresax.com.br</html>")
    session.post.return_value = busca_resposta
    session.get.return_value = pagina_resposta

    email = buscar_email_por_empresa("Empresa X", "API_KEY", session=session)

    assert email == "contato@empresax.com.br"


def test_buscar_email_returns_none_when_no_results():
    session = MagicMock()
    session.post.return_value = _resposta(json_data={"results": []})

    assert buscar_email_por_empresa("Empresa Inexistente", "API_KEY", session=session) is None


def test_buscar_email_returns_none_when_no_email_found_anywhere():
    session = MagicMock()
    session.post.return_value = _resposta(
        json_data={"results": [{"title": "Empresa X", "text": "Sem contato aqui", "url": "https://empresax.com.br"}]}
    )
    session.get.return_value = _resposta(text="<html>Nada aqui</html>")

    assert buscar_email_por_empresa("Empresa X", "API_KEY", session=session) is None


def test_buscar_email_raises_on_invalid_key():
    session = MagicMock()
    session.post.return_value = _resposta(status_code=401)

    with pytest.raises(EmailFinderError, match="inválida"):
        buscar_email_por_empresa("Empresa X", "API_KEY", session=session)


def test_buscar_email_raises_on_credit_exhausted():
    session = MagicMock()
    session.post.return_value = _resposta(status_code=429)

    with pytest.raises(EmailFinderError, match="esgotado"):
        buscar_email_por_empresa("Empresa X", "API_KEY", session=session)


def test_buscar_email_raises_on_request_exception():
    import requests

    session = MagicMock()
    session.post.side_effect = requests.exceptions.ConnectionError("falha de rede")

    with pytest.raises(EmailFinderError, match="Falha ao consultar"):
        buscar_email_por_empresa("Empresa X", "API_KEY", session=session)


def test_buscar_email_ignores_ignored_domains():
    session = MagicMock()
    session.post.return_value = _resposta(
        json_data={"results": [{"title": "Empresa X", "text": "erro@sentry.io e real@empresax.com.br"}]}
    )

    email = buscar_email_por_empresa("Empresa X", "API_KEY", session=session)

    assert email == "real@empresax.com.br"


def test_buscar_email_sends_api_key_header():
    session = MagicMock()
    session.post.return_value = _resposta(json_data={"results": []})

    buscar_email_por_empresa("Empresa X", "MINHA_CHAVE", session=session)

    _, kwargs = session.post.call_args
    assert kwargs["headers"]["x-api-key"] == "MINHA_CHAVE"

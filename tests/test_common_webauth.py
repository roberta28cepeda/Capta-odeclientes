from unittest.mock import patch

from flask import Flask

from src.common.webauth import admin_authenticated

app = Flask(__name__)


def _com_auth(username: str, password: str):
    import base64

    credenciais = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {credenciais}"}


def test_admin_authenticated_aceita_senha_com_acento():
    with patch.dict("os.environ", {"ADMIN_PASSWORD": "sénha-com-açento"}):
        with app.test_request_context(headers=_com_auth("admin", "sénha-com-açento")):
            assert admin_authenticated() is True


def test_admin_authenticated_rejeita_senha_errada_com_acento_sem_quebrar():
    with patch.dict("os.environ", {"ADMIN_PASSWORD": "sénha-com-açento"}):
        with app.test_request_context(headers=_com_auth("admin", "outra-sénha")):
            assert admin_authenticated() is False


def test_admin_authenticated_rejeita_sem_header():
    with app.test_request_context():
        assert admin_authenticated() is False

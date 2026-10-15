import os
import tempfile
from unittest.mock import patch

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from src.common.webauth import admin_authenticated, current_papel, require_papel
from src.fiscal_monitor import storage

app = Flask(__name__)


def _com_auth(username: str, password: str):
    import base64

    credenciais = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {credenciais}"}


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "fiscal_monitor.db")


@pytest.fixture
def app_com_db(db_path):
    application = Flask(__name__)
    application.config["DB_PATH"] = db_path
    return application


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


def test_current_papel_retorna_mestre_para_login_via_env_var():
    with patch.dict("os.environ", {"ADMIN_PASSWORD": "sénha-com-açento"}):
        with app.test_request_context(headers=_com_auth("admin", "sénha-com-açento")):
            assert current_papel() == "mestre"


def test_current_papel_retorna_none_sem_header():
    with app.test_request_context():
        assert current_papel() is None


def test_current_papel_retorna_papel_do_admin_user(app_com_db, db_path):
    conn = storage.connect(db_path)
    storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"), papel="gestor")
    conn.close()

    with app_com_db.test_request_context(headers=_com_auth("maria", "senha-da-maria")):
        assert current_papel() == "gestor"


def test_current_papel_retorna_none_para_senha_errada(app_com_db, db_path):
    conn = storage.connect(db_path)
    storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"), papel="gestor")
    conn.close()

    with app_com_db.test_request_context(headers=_com_auth("maria", "senha-errada")):
        assert current_papel() is None


def test_current_papel_retorna_none_para_usuario_inativo(app_com_db, db_path):
    conn = storage.connect(db_path)
    usuario = storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"), papel="gestor")
    storage.set_admin_user_ativo(conn, usuario.id, False)
    conn.close()

    with app_com_db.test_request_context(headers=_com_auth("maria", "senha-da-maria")):
        assert current_papel() is None


def test_require_papel_401_sem_autenticacao():
    with app.test_request_context():
        resposta = require_papel("leitor")
        assert resposta is not None
        assert resposta.status_code == 401
        assert "WWW-Authenticate" in resposta.headers


def test_require_papel_403_papel_insuficiente(app_com_db, db_path):
    conn = storage.connect(db_path)
    storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"), papel="leitor")
    conn.close()

    with app_com_db.test_request_context(headers=_com_auth("maria", "senha-da-maria")):
        resposta = require_papel("gestor")
        assert resposta is not None
        assert resposta.status_code == 403
        assert "WWW-Authenticate" not in resposta.headers


def test_require_papel_none_quando_papel_suficiente(app_com_db, db_path):
    conn = storage.connect(db_path)
    storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"), papel="gestor")
    conn.close()

    with app_com_db.test_request_context(headers=_com_auth("maria", "senha-da-maria")):
        assert require_papel("leitor") is None
        assert require_papel("operador") is None
        assert require_papel("gestor") is None


def test_require_papel_mestre_sempre_passa():
    with patch.dict("os.environ", {"ADMIN_PASSWORD": "sénha-com-açento"}):
        with app.test_request_context(headers=_com_auth("admin", "sénha-com-açento")):
            assert require_papel("gestor") is None

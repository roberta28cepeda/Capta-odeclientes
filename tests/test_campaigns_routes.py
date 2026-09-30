import base64
import io
import os
import tempfile
from unittest.mock import patch

import pytest

from src.campaigns import storage as campaigns_storage
from src.fiscal_monitor.server import create_app

TESE = "transportadoras_pgfn"


def _basic_auth_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def campaigns_db_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "campaigns.db")


@pytest.fixture
def app(campaigns_db_path):
    with tempfile.TemporaryDirectory() as tmp:
        fiscal_db = os.path.join(tmp, "fiscal_monitor.db")
        yield create_app(db_path=fiscal_db, campaigns_db_path=campaigns_db_path)


def test_listar_leads_requires_admin(app):
    response = app.test_client().get("/admin/campanhas/leads")
    assert response.status_code == 401


def test_importar_leads_form_renders_with_admin_auth(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get("/admin/campanhas/leads/importar", headers=_basic_auth_header("admin", "senha-secreta"))
    assert response.status_code == 200


def test_importar_leads_post_imports_csv(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    csv_content = b"cnpj,razao_social,email,valor_divida\n11.222.333/0001-44,Empresa X,x@exemplo.com,1500.00\n"

    response = app.test_client().post(
        "/admin/campanhas/leads/importar",
        data={"tese": TESE, "csv": (io.BytesIO(csv_content), "leads.csv")},
        content_type="multipart/form-data",
        headers=_basic_auth_header("admin", "senha-secreta"),
    )

    assert response.status_code == 200
    assert b"1 lead(s) importado(s) na tese" in response.data
    assert TESE.encode() in response.data


def test_importar_leads_requires_tese(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    csv_content = b"cnpj,razao_social\n11.222.333/0001-44,Empresa X\n"

    response = app.test_client().post(
        "/admin/campanhas/leads/importar",
        data={"csv": (io.BytesIO(csv_content), "leads.csv")},
        content_type="multipart/form-data",
        headers=_basic_auth_header("admin", "senha-secreta"),
    )
    assert response.status_code == 400


def test_listar_leads_shows_imported_lead(app, monkeypatch, campaigns_db_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    conn = campaigns_storage.connect(campaigns_db_path)
    campaigns_storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com")

    response = app.test_client().get("/admin/campanhas/leads", headers=_basic_auth_header("admin", "senha-secreta"))

    assert response.status_code == 200
    assert b"Empresa X" in response.data


def test_listar_leads_filters_by_tese_query_param(app, monkeypatch, campaigns_db_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    conn = campaigns_storage.connect(campaigns_db_path)
    campaigns_storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")
    campaigns_storage.create_lead(conn, "22.333.444/0001-55", "contadores_certificado", razao_social="Escritório Y")

    response = app.test_client().get(
        f"/admin/campanhas/leads?tese={TESE}", headers=_basic_auth_header("admin", "senha-secreta")
    )

    assert response.status_code == 200
    assert b"Empresa X" in response.data
    assert b"Escrit\xc3\xb3rio Y" not in response.data


def test_listar_templates_requires_admin(app):
    response = app.test_client().get("/admin/campanhas/templates")
    assert response.status_code == 401


def test_listar_templates_shows_default_templates_for_first_tese(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get("/admin/campanhas/templates", headers=_basic_auth_header("admin", "senha-secreta"))
    assert response.status_code == 200
    assert b"inicial" in response.data


def test_listar_templates_for_specific_tese(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get(
        f"/admin/campanhas/templates?tese={TESE}", headers=_basic_auth_header("admin", "senha-secreta")
    )
    assert response.status_code == 200
    assert "PGFN".encode() in response.data


def test_salvar_template_updates_and_redirects(app, monkeypatch, campaigns_db_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().post(
        f"/admin/campanhas/templates/{TESE}/inicial",
        data={
            "assunto": "Novo assunto", "tag": "TAG", "headline": "Título", "paragrafo1": "P1", "paragrafo2": "P2",
            "checklist": "Item 1\nItem 2", "italico": "Urgente", "cta_texto": "CLIQUE",
            "link_cta": "https://wa.me/5500000000000", "rodape_nota": "nota",
        },
        headers=_basic_auth_header("admin", "senha-secreta"),
    )

    assert response.status_code == 302
    conn = campaigns_storage.connect(campaigns_db_path)
    template = campaigns_storage.get_template(conn, TESE, "inicial")
    assert template.assunto == "Novo assunto"
    assert template.checklist == ["Item 1", "Item 2"]


def test_salvar_template_rejects_invalid_tipo(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().post(
        f"/admin/campanhas/templates/{TESE}/tipo-invalido",
        data={"assunto": "x"},
        headers=_basic_auth_header("admin", "senha-secreta"),
    )
    assert response.status_code == 404


def test_track_open_records_event_and_returns_gif(app, campaigns_db_path):
    conn = campaigns_storage.connect(campaigns_db_path)
    lead = campaigns_storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    envio = campaigns_storage.create_envio(conn, lead.id, "inicial")

    response = app.test_client().get(f"/track/open/{envio.tracking_token}.gif")

    assert response.status_code == 200
    assert response.mimetype == "image/gif"
    eventos = campaigns_storage.eventos_do_envio(conn, envio.id)
    assert len(eventos) == 1
    assert eventos[0].tipo == "open"


def test_track_open_with_unknown_token_still_returns_gif(app):
    response = app.test_client().get("/track/open/token-inexistente.gif")
    assert response.status_code == 200
    assert response.mimetype == "image/gif"


def test_track_click_records_event_and_redirects(app, campaigns_db_path):
    conn = campaigns_storage.connect(campaigns_db_path)
    lead = campaigns_storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    envio = campaigns_storage.create_envio(conn, lead.id, "inicial")

    response = app.test_client().get(
        f"/track/click/{envio.tracking_token}", query_string={"url": "https://wa.me/5521986956773"}
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "https://wa.me/5521986956773"
    eventos = campaigns_storage.eventos_do_envio(conn, envio.id)
    assert eventos[0].tipo == "click"
    assert eventos[0].url == "https://wa.me/5521986956773"


def test_cron_campanhas_requires_secret(app):
    response = app.test_client().get("/cron/campanhas/rodar")
    assert response.status_code == 401


def test_cron_campanhas_requires_smtp_config(app, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "segredo")
    response = app.test_client().get("/cron/campanhas/rodar?secret=segredo")
    assert response.status_code == 500


def test_cron_campanhas_runs_and_sends_pending_leads(app, monkeypatch, campaigns_db_path):
    monkeypatch.setenv("CRON_SECRET", "segredo")
    monkeypatch.setenv("SMTP_HOST", "smtp.host")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")

    conn = campaigns_storage.connect(campaigns_db_path)
    campaigns_storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com")

    with patch("src.campaigns.engine.send_email_html") as mock_send:
        response = app.test_client().get("/cron/campanhas/rodar?secret=segredo")

    assert response.status_code == 200
    data = response.get_json()
    assert data["enviados"] == 1
    assert data["busca_email"] is None
    mock_send.assert_called_once()


def test_cron_campanhas_runs_email_search_when_exa_key_configured(app, monkeypatch, campaigns_db_path):
    monkeypatch.setenv("CRON_SECRET", "segredo")
    monkeypatch.setenv("SMTP_HOST", "smtp.host")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setenv("EXA_API_KEY", "EXA_KEY")

    conn = campaigns_storage.connect(campaigns_db_path)
    campaigns_storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")

    with patch("src.campaigns.engine.buscar_email_por_empresa", return_value="achado@empresax.com.br") as mock_busca, patch(
        "src.campaigns.engine.send_email_html"
    ) as mock_send:
        response = app.test_client().get("/cron/campanhas/rodar?secret=segredo")

    assert response.status_code == 200
    data = response.get_json()
    assert data["busca_email"] == {"leads_verificados": 1, "encontrados": 1, "erros": []}
    mock_busca.assert_called_once_with("Empresa X", "EXA_KEY")
    mock_send.assert_called_once()  # já achou o e-mail nessa mesma rodada, então já manda hoje

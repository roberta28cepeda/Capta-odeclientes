import base64
import io
import os
import tempfile
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

from src.fiscal_monitor import storage
from src.fiscal_monitor.infosimples import ConsultaDebitosError
from src.fiscal_monitor.preanalise import CartaoCnpjError, ConsultaCnpjError
from src.fiscal_monitor.server import create_app

SAMPLE_CNPJ_RESPONSE = {
    "cnpj": "33000167000101",
    "razao_social": "PETROBRAS",
    "descricao_situacao_cadastral": "ATIVA",
    "descricao_porte": "DEMAIS",
    "uf": "RJ",
    "municipio": "RIO DE JANEIRO",
    "opcao_pelo_simples": False,
    "opcao_pelo_mei": False,
}


def _basic_auth_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "fiscal_monitor.db")


@pytest.fixture
def app(db_path):
    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório A", contato_whatsapp="5511999999999")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44", razao_social="Contábil Exemplo")
    snapshot_id = storage.create_snapshot(conn, cnpj.id, "manual_csv")
    storage.add_finding(conn, snapshot_id, "federal", "das", "DAS 08/2026", 412.5, "2026-09-25", False, "nova")
    conn.close()

    application = create_app(db_path=db_path)
    application.config["_tenant_id"] = tenant.id
    application.config["_tenant_token"] = tenant.acesso_token
    application.config["_cnpj_id"] = cnpj.id
    return application


def _tenant_url(app, path: str = "") -> str:
    tenant_id = app.config["_tenant_id"]
    token = app.config["_tenant_token"]
    return f"/tenants/{tenant_id}{path}?token={token}"


def test_health_returns_ok(app):
    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_novo_tenant_requires_admin_auth(app):
    response = app.test_client().get("/admin/tenants/novo")
    assert response.status_code == 401


def test_novo_tenant_form_renders_with_admin_auth(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get("/admin/tenants/novo", headers=_basic_auth_header("admin", "senha-secreta"))
    assert response.status_code == 200
    assert b"Cadastrar novo escrit\xc3\xb3rio" in response.data


def test_novo_tenant_post_creates_tenant_and_returns_access_link(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().post(
        "/admin/tenants/novo",
        data={"nome": "Escritório Novo", "whatsapp": "5511988887777"},
        headers=_basic_auth_header("admin", "senha-secreta"),
    )

    assert response.status_code == 200
    assert "Escritório Novo".encode() in response.data
    assert b"?token=" in response.data


def test_novo_tenant_post_rejects_missing_nome(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().post(
        "/admin/tenants/novo", data={}, headers=_basic_auth_header("admin", "senha-secreta")
    )
    assert response.status_code == 400


def test_novo_tenant_post_with_portfolio_csv_imports_cnpjs(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    csv_content = b"cnpj,razao_social,nome_fantasia,regime_tributario\n11.222.333/0001-44,Contabil Exemplo,,simples\n"

    response = app.test_client().post(
        "/admin/tenants/novo",
        data={
            "nome": "Escritório Com Carteira",
            "carteira": (io.BytesIO(csv_content), "carteira.csv"),
        },
        content_type="multipart/form-data",
        headers=_basic_auth_header("admin", "senha-secreta"),
    )

    assert response.status_code == 200
    assert b"1 CNPJ(s) importado(s)." in response.data


def test_privacidade_page_is_public_and_shows_controller_and_contact(app):
    response = app.test_client().get("/privacidade")
    assert response.status_code == 200
    assert b"LEAO CONSULTORIA ESTRATEGICA LTDA" in response.data
    assert b"63.586.147/0001-25" in response.data
    assert b"contato@leactis.com.br" in response.data


def test_tenants_list_requires_admin_auth_by_default(app):
    response = app.test_client().get("/tenants")
    assert response.status_code == 401


def test_tenants_list_shows_tenant_and_cnpj_count_with_admin_auth(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get("/tenants", headers=_basic_auth_header("admin", "senha-secreta"))
    assert response.status_code == 200
    assert b"Escrit\xc3\xb3rio A" in response.data or "Escritório A".encode() in response.data


def test_tenants_list_rejects_wrong_admin_password(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get("/tenants", headers=_basic_auth_header("admin", "errada"))
    assert response.status_code == 401


def test_tenant_detail_returns_404_for_missing_tenant(app):
    response = app.test_client().get("/tenants/999?token=qualquer")
    assert response.status_code == 404


def test_tenant_detail_requires_token_or_admin(app):
    tenant_id = app.config["_tenant_id"]
    response = app.test_client().get(f"/tenants/{tenant_id}")
    assert response.status_code == 403


def test_tenant_detail_rejects_wrong_token(app):
    tenant_id = app.config["_tenant_id"]
    response = app.test_client().get(f"/tenants/{tenant_id}?token=token-errado")
    assert response.status_code == 403


def test_tenant_detail_accessible_with_correct_token(app):
    response = app.test_client().get(_tenant_url(app))
    assert response.status_code == 200
    assert "DAS 08/2026".encode() in response.data


def test_tenant_detail_accessible_with_admin_auth_without_token(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    tenant_id = app.config["_tenant_id"]
    response = app.test_client().get(
        f"/tenants/{tenant_id}", headers=_basic_auth_header("admin", "senha-secreta")
    )
    assert response.status_code == 200


def test_tenant_findings_json_returns_open_findings(app):
    response = app.test_client().get(_tenant_url(app, "/findings.json"))
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    assert data[0]["cnpj"] == "11.222.333/0001-44"
    assert data[0]["tipo"] == "das"
    assert data[0]["status"] == "nova"


def test_tenant_findings_json_requires_token(app):
    tenant_id = app.config["_tenant_id"]
    response = app.test_client().get(f"/tenants/{tenant_id}/findings.json")
    assert response.status_code == 403


def test_tenant_findings_json_returns_404_for_missing_tenant(app):
    response = app.test_client().get("/tenants/999/findings.json?token=qualquer")
    assert response.status_code == 404


def test_tenant_detail_shows_portfolio_and_regime(app):
    response = app.test_client().get(_tenant_url(app))
    assert response.status_code == 200
    assert "11.222.333/0001-44".encode() in response.data


def test_cnpj_history_returns_all_snapshots(db_path):
    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório B")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "22.333.444/0001-55")
    snap1 = storage.create_snapshot(conn, cnpj.id, "manual_csv")
    storage.add_finding(conn, snap1, "federal", "multa", "Multa X", 100.0, None, False, "nova")
    snap2 = storage.create_snapshot(conn, cnpj.id, "manual_csv")
    storage.add_finding(conn, snap2, "federal", "multa", "Multa X", None, None, False, "resolvida")
    conn.close()

    application = create_app(db_path=db_path)
    response = application.test_client().get(
        f"/tenants/{tenant.id}/cnpjs/{cnpj.id}/historico?token={tenant.acesso_token}"
    )

    assert response.status_code == 200
    assert b"Multa X" in response.data


def test_cnpj_history_requires_token(db_path):
    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório B")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "22.333.444/0001-55")
    conn.close()

    application = create_app(db_path=db_path)
    response = application.test_client().get(f"/tenants/{tenant.id}/cnpjs/{cnpj.id}/historico")

    assert response.status_code == 403


def test_tenant_detail_shows_sublimite_alert_for_simples_cnpj(db_path):
    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório C")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "33.444.555/0001-66", regime_tributario="simples")
    for mes in range(1, 13):
        storage.record_faturamento(conn, cnpj.id, f"2026-{mes:02d}", 310_000.0)
    conn.close()

    application = create_app(db_path=db_path)
    response = application.test_client().get(
        f"/tenants/{tenant.id}", query_string={"referencia": "2026-12", "token": tenant.acesso_token}
    )

    assert response.status_code == 200
    assert b"sublimite_estourado" in response.data


def test_pre_analise_requires_admin_auth(app):
    response = app.test_client().get("/pre-analise")
    assert response.status_code == 401


def test_pre_analise_form_renders_on_get(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get("/pre-analise", headers=_basic_auth_header("admin", "senha-secreta"))
    assert response.status_code == 200
    assert b"Pr\xc3\xa9-An\xc3\xa1lise Fiscal" in response.data


def test_pre_analise_post_rejects_invalid_cnpj(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().post(
        "/pre-analise", data={"cnpj": "00.000.000/0000-00"}, headers=_basic_auth_header("admin", "senha-secreta")
    )
    assert response.status_code == 400
    assert "CNPJ inválido".encode() in response.data


def test_pre_analise_post_returns_pdf_for_valid_cnpj(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    with patch("src.fiscal_monitor.server.consultar_cnpj_publico", return_value=SAMPLE_CNPJ_RESPONSE):
        response = app.test_client().post(
            "/pre-analise",
            data={"cnpj": "33.000.167/0001-01", "escritorio_nome": "Escritório X"},
            headers=_basic_auth_header("admin", "senha-secreta"),
        )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data[:4] == b"%PDF"


def test_pre_analise_post_shows_error_when_consulta_falha(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    with patch(
        "src.fiscal_monitor.server.consultar_cnpj_publico",
        side_effect=ConsultaCnpjError("CNPJ 33.000.167/0001-01 não encontrado."),
    ):
        response = app.test_client().post(
            "/pre-analise", data={"cnpj": "33.000.167/0001-01"}, headers=_basic_auth_header("admin", "senha-secreta")
        )

    assert response.status_code == 400
    assert "não encontrado".encode() in response.data


def test_pre_analise_form_shows_cartao_cnpj_button_when_cnpja_configured(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("CNPJA_API_TOKEN", "TOKEN123")
    response = app.test_client().get("/pre-analise", headers=_basic_auth_header("admin", "senha-secreta"))
    assert b"Cart\xc3\xa3o CNPJ" in response.data


def test_pre_analise_form_hides_cartao_cnpj_button_without_cnpja_token(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get("/pre-analise", headers=_basic_auth_header("admin", "senha-secreta"))
    assert b"Cart\xc3\xa3o CNPJ" not in response.data


def test_pre_analise_post_uses_cnpja_when_token_configured(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("CNPJA_API_TOKEN", "TOKEN123")
    cnpja_response = {
        "taxId": "33000167000101",
        "company": {"name": "PETROBRAS", "nature": {}, "size": {}, "simples": {}, "simei": {}, "members": []},
        "status": {"text": "Ativa"},
        "address": {"state": "RJ", "city": "RIO DE JANEIRO"},
        "mainActivity": {},
    }
    with patch("src.fiscal_monitor.server.consultar_cnpj_cnpja", return_value=cnpja_response) as mock_cnpja, patch(
        "src.fiscal_monitor.server.consultar_cnpj_publico"
    ) as mock_brasilapi:
        response = app.test_client().post(
            "/pre-analise", data={"cnpj": "33.000.167/0001-01"}, headers=_basic_auth_header("admin", "senha-secreta")
        )

    assert response.status_code == 200
    mock_cnpja.assert_called_once_with("33.000.167/0001-01", "TOKEN123")
    mock_brasilapi.assert_not_called()


def test_cartao_cnpj_requires_admin_auth(app):
    response = app.test_client().get("/pre-analise/cartao-cnpj?cnpj=33.000.167/0001-01")
    assert response.status_code == 401


def test_cartao_cnpj_returns_500_without_token(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get(
        "/pre-analise/cartao-cnpj?cnpj=33.000.167/0001-01", headers=_basic_auth_header("admin", "senha-secreta")
    )
    assert response.status_code == 500


def test_cartao_cnpj_rejects_invalid_cnpj(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("CNPJA_API_TOKEN", "TOKEN123")
    response = app.test_client().get(
        "/pre-analise/cartao-cnpj?cnpj=00.000.000/0000-00", headers=_basic_auth_header("admin", "senha-secreta")
    )
    assert response.status_code == 400


def test_cartao_cnpj_returns_pdf_on_success(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("CNPJA_API_TOKEN", "TOKEN123")
    with patch("src.fiscal_monitor.server.buscar_cartao_cnpj_pdf", return_value=b"%PDF-1.4 conteudo") as mock_busca:
        response = app.test_client().get(
            "/pre-analise/cartao-cnpj?cnpj=33.000.167/0001-01", headers=_basic_auth_header("admin", "senha-secreta")
        )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    mock_busca.assert_called_once_with("33.000.167/0001-01", "TOKEN123")


def test_cartao_cnpj_returns_502_on_provider_error(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("CNPJA_API_TOKEN", "TOKEN123")
    with patch(
        "src.fiscal_monitor.server.buscar_cartao_cnpj_pdf",
        side_effect=CartaoCnpjError("cota esgotada"),
    ):
        response = app.test_client().get(
            "/pre-analise/cartao-cnpj?cnpj=33.000.167/0001-01", headers=_basic_auth_header("admin", "senha-secreta")
        )

    assert response.status_code == 502


def test_pre_analise_skips_infosimples_when_token_not_configured(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    with patch("src.fiscal_monitor.server.consultar_cnpj_publico", return_value=SAMPLE_CNPJ_RESPONSE), patch(
        "src.fiscal_monitor.server.consultar_cnd_federal"
    ) as mock_cnd:
        response = app.test_client().post(
            "/pre-analise", data={"cnpj": "33.000.167/0001-01"}, headers=_basic_auth_header("admin", "senha-secreta")
        )

    assert response.status_code == 200
    mock_cnd.assert_not_called()


def test_pre_analise_includes_situacao_fiscal_when_infosimples_configured(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")
    with patch("src.fiscal_monitor.server.consultar_cnpj_publico", return_value=SAMPLE_CNPJ_RESPONSE), patch(
        "src.fiscal_monitor.server.consultar_cnd_federal",
        return_value={"debitos_pgfn": True, "debitos_rfb": False, "tipo": "Positiva"},
    ) as mock_cnd, patch(
        "src.fiscal_monitor.server.consultar_lista_devedores", return_value=None
    ) as mock_devedores, patch(
        "src.fiscal_monitor.server.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}
    ), patch("src.fiscal_monitor.server.consultar_cndt_trabalhista", return_value={"consta": False}):
        response = app.test_client().post(
            "/pre-analise", data={"cnpj": "33.000.167/0001-01"}, headers=_basic_auth_header("admin", "senha-secreta")
        )

    assert response.status_code == 200
    mock_cnd.assert_called_once_with("33.000.167/0001-01", "TOKEN123")
    mock_devedores.assert_called_once_with("33.000.167/0001-01", "TOKEN123")


def test_pre_analise_still_generates_pdf_when_infosimples_falha(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")
    with patch("src.fiscal_monitor.server.consultar_cnpj_publico", return_value=SAMPLE_CNPJ_RESPONSE), patch(
        "src.fiscal_monitor.server.consultar_cnd_federal",
        side_effect=ConsultaDebitosError("saldo insuficiente"),
    ), patch(
        "src.fiscal_monitor.server.consultar_lista_devedores",
        side_effect=ConsultaDebitosError("saldo insuficiente"),
    ), patch(
        "src.fiscal_monitor.server.consultar_regularidade_fgts",
        side_effect=ConsultaDebitosError("saldo insuficiente"),
    ), patch(
        "src.fiscal_monitor.server.consultar_cndt_trabalhista",
        side_effect=ConsultaDebitosError("saldo insuficiente"),
    ):
        response = app.test_client().post(
            "/pre-analise", data={"cnpj": "33.000.167/0001-01"}, headers=_basic_auth_header("admin", "senha-secreta")
        )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"


def test_pre_analise_lista_devedores_still_runs_when_cnd_federal_falha(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")
    devedores_response = {
        "total_divida": 7359.68,
        "total_tributario": 0.0,
        "total_nao_tributario": 7359.68,
        "naturezas_debitos": [
            {"descricao": "FGTS", "total": 7359.68, "debitos": [{"inscricao": "FGAL1", "valor_divida": 7359.68}]}
        ],
    }
    with patch("src.fiscal_monitor.server.consultar_cnpj_publico", return_value=SAMPLE_CNPJ_RESPONSE), patch(
        "src.fiscal_monitor.server.consultar_cnd_federal",
        side_effect=ConsultaDebitosError("código 611: dados incompletos na origem"),
    ), patch(
        "src.fiscal_monitor.server.consultar_lista_devedores", return_value=devedores_response
    ) as mock_devedores, patch(
        "src.fiscal_monitor.server.enriquecer_com_dados_abertos", wraps=lambda conn, divida: divida
    ), patch(
        "src.fiscal_monitor.server.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}
    ), patch("src.fiscal_monitor.server.consultar_cndt_trabalhista", return_value={"consta": False}):
        response = app.test_client().post(
            "/pre-analise", data={"cnpj": "33.000.167/0001-01"}, headers=_basic_auth_header("admin", "senha-secreta")
        )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    mock_devedores.assert_called_once_with("33.000.167/0001-01", "TOKEN123")


def test_pre_analise_enriquece_divida_ativa_com_dados_abertos(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")
    devedores_response = {
        "total_divida": 7359.68,
        "total_tributario": 0.0,
        "total_nao_tributario": 7359.68,
        "naturezas_debitos": [
            {"descricao": "FGTS", "total": 7359.68, "debitos": [{"inscricao": "FGAL1", "valor_divida": 7359.68}]}
        ],
    }
    with patch("src.fiscal_monitor.server.consultar_cnpj_publico", return_value=SAMPLE_CNPJ_RESPONSE), patch(
        "src.fiscal_monitor.server.consultar_cnd_federal", return_value={}
    ), patch("src.fiscal_monitor.server.consultar_lista_devedores", return_value=devedores_response), patch(
        "src.fiscal_monitor.server.enriquecer_com_dados_abertos", wraps=lambda conn, divida: divida
    ) as mock_enriquecer, patch(
        "src.fiscal_monitor.server.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}
    ), patch("src.fiscal_monitor.server.consultar_cndt_trabalhista", return_value={"consta": False}):
        response = app.test_client().post(
            "/pre-analise", data={"cnpj": "33.000.167/0001-01"}, headers=_basic_auth_header("admin", "senha-secreta")
        )

    assert response.status_code == 200
    mock_enriquecer.assert_called_once()


def test_cnpj_history_returns_404_for_cnpj_of_another_tenant(app, db_path):
    conn = storage.connect(db_path)
    outro_tenant = storage.create_tenant(conn, "Escritório B")
    outro_cnpj = storage.upsert_cnpj(conn, outro_tenant.id, "22.333.444/0001-55")
    conn.close()

    tenant_id = app.config["_tenant_id"]
    token = app.config["_tenant_token"]
    response = app.test_client().get(f"/tenants/{tenant_id}/cnpjs/{outro_cnpj.id}/historico?token={token}")

    assert response.status_code == 404


def test_cron_check_all_requires_secret(app):
    response = app.test_client().get("/cron/check-all")
    assert response.status_code == 401


def test_cron_check_all_rejects_wrong_secret(app, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "segredo-certo")
    response = app.test_client().get("/cron/check-all?secret=errado")
    assert response.status_code == 401


def test_cron_check_all_accepts_query_secret(app, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "segredo-certo")
    response = app.test_client().get("/cron/check-all?secret=segredo-certo")
    assert response.status_code == 200
    data = response.get_json()
    assert data["tenants_verificados"] == 1
    assert data["resultados"][0]["alertas"] == 1


def test_cron_check_all_accepts_bearer_header(app, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "segredo-certo")
    response = app.test_client().get(
        "/cron/check-all", headers={"Authorization": "Bearer segredo-certo"}
    )
    assert response.status_code == 200


def test_cron_check_all_skips_infosimples_without_token(app, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "segredo-certo")
    monkeypatch.delenv("INFOSIMPLES_API_TOKEN", raising=False)
    response = app.test_client().get("/cron/check-all?secret=segredo-certo")
    assert response.status_code == 200
    assert response.get_json()["infosimples_semanal_rodou"] is False


def test_cron_check_all_runs_infosimples_on_monday(app, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "segredo-certo")
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")
    import datetime

    with patch("src.fiscal_monitor.server.date") as mock_date, patch(
        "src.fiscal_monitor.server.run_infosimples_semanal", return_value=[{"cnpj": "x", "achados": 0, "erro": None}]
    ) as mock_run:
        mock_date.today.return_value = datetime.date(2026, 10, 5)  # segunda-feira
        response = app.test_client().get("/cron/check-all?secret=segredo-certo")

    assert response.status_code == 200
    data = response.get_json()
    assert data["infosimples_semanal_rodou"] is True
    mock_run.assert_called_once()


def test_cron_check_all_skips_infosimples_on_non_monday(app, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "segredo-certo")
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")
    import datetime

    with patch("src.fiscal_monitor.server.date") as mock_date, patch(
        "src.fiscal_monitor.server.run_infosimples_semanal"
    ) as mock_run:
        mock_date.today.return_value = datetime.date(2026, 10, 6)  # terça-feira
        response = app.test_client().get("/cron/check-all?secret=segredo-certo")

    assert response.status_code == 200
    assert response.get_json()["infosimples_semanal_rodou"] is False
    mock_run.assert_not_called()


def test_check_all_rodar_agora_requires_admin(app):
    response = app.test_client().get("/admin/check-all/rodar-agora")
    assert response.status_code == 401


def test_check_all_rodar_agora_post_runs_and_shows_result(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.delenv("INFOSIMPLES_API_TOKEN", raising=False)
    response = app.test_client().post(
        "/admin/check-all/rodar-agora", headers=_basic_auth_header("admin", "senha-secreta")
    )
    assert response.status_code == 200
    assert b"Escrit\xc3\xb3rios verificados" in response.data


def test_check_all_rodar_agora_can_force_infosimples_outside_monday(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")
    import datetime

    with patch("src.fiscal_monitor.server.date") as mock_date, patch(
        "src.fiscal_monitor.server.run_infosimples_semanal", return_value=[]
    ) as mock_run:
        mock_date.today.return_value = datetime.date(2026, 10, 6)  # terça-feira
        response = app.test_client().post(
            "/admin/check-all/rodar-agora",
            data={"forcar_infosimples": "on"},
            headers=_basic_auth_header("admin", "senha-secreta"),
        )

    assert response.status_code == 200
    mock_run.assert_called_once()


def test_tenant_cannot_access_another_tenants_data_with_own_token(db_path):
    conn = storage.connect(db_path)
    tenant_a = storage.create_tenant(conn, "Escritório A")
    tenant_b = storage.create_tenant(conn, "Escritório B")
    conn.close()

    application = create_app(db_path=db_path)
    response = application.test_client().get(f"/tenants/{tenant_b.id}?token={tenant_a.acesso_token}")

    assert response.status_code == 403


def test_individual_admin_user_can_authenticate(app, monkeypatch, db_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-mestre")
    conn = storage.connect(db_path)
    storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"), nome="Maria")
    conn.close()

    response = app.test_client().get("/tenants", headers=_basic_auth_header("maria", "senha-da-maria"))

    assert response.status_code == 200


def test_individual_admin_user_wrong_password_rejected(app, monkeypatch, db_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-mestre")
    conn = storage.connect(db_path)
    storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"))
    conn.close()

    response = app.test_client().get("/tenants", headers=_basic_auth_header("maria", "senha-errada"))

    assert response.status_code == 401


def test_deactivated_admin_user_cannot_authenticate(app, monkeypatch, db_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-mestre")
    conn = storage.connect(db_path)
    usuario = storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"))
    storage.set_admin_user_ativo(conn, usuario.id, False)
    conn.close()

    response = app.test_client().get("/tenants", headers=_basic_auth_header("maria", "senha-da-maria"))

    assert response.status_code == 401


def test_master_admin_still_works_alongside_individual_users(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-mestre")
    response = app.test_client().get("/tenants", headers=_basic_auth_header("admin", "senha-mestre"))
    assert response.status_code == 200


def test_admin_usuarios_requires_admin(app):
    response = app.test_client().get("/admin/usuarios")
    assert response.status_code == 401


def test_admin_usuarios_lists_existing_users(app, monkeypatch, db_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-mestre")
    conn = storage.connect(db_path)
    storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"), nome="Maria")
    conn.close()

    response = app.test_client().get("/admin/usuarios", headers=_basic_auth_header("admin", "senha-mestre"))

    assert response.status_code == 200
    assert b"maria" in response.data


def test_admin_usuarios_post_creates_new_user(app, monkeypatch, db_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-mestre")

    response = app.test_client().post(
        "/admin/usuarios",
        data={"username": "joao", "password": "senha-do-joao", "nome": "João"},
        headers=_basic_auth_header("admin", "senha-mestre"),
    )

    assert response.status_code == 200
    conn = storage.connect(db_path)
    usuario = storage.get_admin_user_by_username(conn, "joao")
    assert usuario is not None
    assert usuario.nome == "João"


def test_admin_usuarios_post_rejects_short_password(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-mestre")

    response = app.test_client().post(
        "/admin/usuarios",
        data={"username": "joao", "password": "123"},
        headers=_basic_auth_header("admin", "senha-mestre"),
    )

    assert response.status_code == 400


def test_admin_usuarios_post_rejects_duplicate_username(app, monkeypatch, db_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-mestre")
    conn = storage.connect(db_path)
    storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"))
    conn.close()

    response = app.test_client().post(
        "/admin/usuarios",
        data={"username": "maria", "password": "outra-senha"},
        headers=_basic_auth_header("admin", "senha-mestre"),
    )

    assert response.status_code == 400


def test_alternar_ativo_usuario_toggles_status(app, monkeypatch, db_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-mestre")
    conn = storage.connect(db_path)
    usuario = storage.create_admin_user(conn, "maria", generate_password_hash("senha-da-maria"))
    conn.close()

    response = app.test_client().post(
        f"/admin/usuarios/{usuario.id}/alternar-ativo", headers=_basic_auth_header("admin", "senha-mestre")
    )

    assert response.status_code == 200
    conn = storage.connect(db_path)
    assert storage.get_admin_user_by_username(conn, "maria").ativo is False


def _cnpj_url(app, path: str = "") -> str:
    tenant_id = app.config["_tenant_id"]
    cnpj_id = app.config["_cnpj_id"]
    token = app.config["_tenant_token"]
    return f"/tenants/{tenant_id}/cnpjs/{cnpj_id}{path}?token={token}"


def test_tenant_detail_shows_risk_score(app):
    response = app.test_client().get(_tenant_url(app))
    assert response.status_code == 200
    assert b"Baixo" in response.data  # sem obrigação/certidão cadastrada, risco baixo


def test_obrigacoes_requires_tenant_auth(app):
    tenant_id = app.config["_tenant_id"]
    cnpj_id = app.config["_cnpj_id"]
    response = app.test_client().get(f"/tenants/{tenant_id}/cnpjs/{cnpj_id}/obrigacoes")
    assert response.status_code == 403


def test_obrigacoes_post_creates_and_lists(app):
    response = app.test_client().post(
        _cnpj_url(app, "/obrigacoes"), data={"tipo": "DAS", "vencimento": "2026-10-20"}
    )
    assert response.status_code == 200
    assert b"DAS" in response.data
    assert b"2026-10-20" in response.data


def test_marcar_obrigacao_entregue_route_updates_status(app, db_path):
    conn = storage.connect(db_path)
    cnpj_id = app.config["_cnpj_id"]
    obrigacao = storage.create_obrigacao(conn, cnpj_id, "DAS", "2026-10-20")
    conn.close()

    response = app.test_client().post(_cnpj_url(app, f"/obrigacoes/{obrigacao.id}/entregue"))

    assert response.status_code == 302
    conn = storage.connect(db_path)
    assert storage.get_obrigacao(conn, obrigacao.id).status == "entregue"


def test_certidoes_requires_tenant_auth(app):
    tenant_id = app.config["_tenant_id"]
    cnpj_id = app.config["_cnpj_id"]
    response = app.test_client().get(f"/tenants/{tenant_id}/cnpjs/{cnpj_id}/certidoes")
    assert response.status_code == 403


def test_certidoes_lists_federal_as_required_without_uf(app):
    response = app.test_client().get(_cnpj_url(app, "/certidoes"))
    assert response.status_code == 200
    assert b"FEDERAL" in response.data
    assert b"sem certid" in response.data


def test_certidoes_post_uploads_pdf(app, db_path):
    response = app.test_client().post(
        _cnpj_url(app, "/certidoes"),
        data={
            "orgao": "federal", "numero": "123ABC", "emitida_em": "2026-09-01", "valida_ate": "2027-03-01",
            "arquivo": (io.BytesIO(b"%PDF-1.4 conteudo"), "certidao.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert b"valida" in response.data

    conn = storage.connect(db_path)
    cnpj_id = app.config["_cnpj_id"]
    atuais = storage.latest_certidoes_by_orgao(conn, cnpj_id)
    assert atuais["federal"].numero == "123ABC"


def test_baixar_certidao_returns_pdf(app, db_path):
    conn = storage.connect(db_path)
    cnpj_id = app.config["_cnpj_id"]
    certidao = storage.create_certidao(
        conn, cnpj_id, "federal", None, "2026-09-01", "2027-03-01", "certidao.pdf", b"%PDF-1.4 conteudo"
    )
    conn.close()

    response = app.test_client().get(_cnpj_url(app, f"/certidoes/{certidao.id}/baixar"))

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data == b"%PDF-1.4 conteudo"


def _pdf_valido_minimo() -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    c.drawString(10, 10, "certidao de teste")
    c.save()
    return buffer.getvalue()


def test_baixar_certidoes_unificado_merges_pdfs(app, db_path):
    conn = storage.connect(db_path)
    cnpj_id = app.config["_cnpj_id"]
    storage.create_certidao(
        conn, cnpj_id, "federal", None, "2026-09-01", "2027-03-01", "federal.pdf", _pdf_valido_minimo()
    )
    conn.close()

    response = app.test_client().get(_cnpj_url(app, "/certidoes/unificado.pdf"))

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"


def test_baixar_certidoes_unificado_404_without_certidoes(app):
    response = app.test_client().get(_cnpj_url(app, "/certidoes/unificado.pdf"))
    assert response.status_code == 404


def test_dossie_fiscal_automatico_requires_tenant_auth(app):
    tenant_id = app.config["_tenant_id"]
    cnpj_id = app.config["_cnpj_id"]
    response = app.test_client().get(f"/tenants/{tenant_id}/cnpjs/{cnpj_id}/certidoes/dossie-fiscal.pdf")
    assert response.status_code == 403


def test_dossie_fiscal_automatico_requires_infosimples_token(app):
    response = app.test_client().get(_cnpj_url(app, "/certidoes/dossie-fiscal.pdf"))
    assert response.status_code == 400
    assert b"INFOSIMPLES_API_TOKEN" in response.data


def test_dossie_fiscal_automatico_calls_all_four_consultas_and_returns_pdf(app, monkeypatch):
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")

    with patch(
        "src.fiscal_monitor.server.consultar_cnd_federal",
        return_value={"tipo": "Negativa", "debitos_pgfn": False, "debitos_rfb": False},
    ) as mock_cnd, patch(
        "src.fiscal_monitor.server.consultar_lista_devedores", return_value=None
    ) as mock_devedores, patch(
        "src.fiscal_monitor.server.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}
    ) as mock_fgts, patch(
        "src.fiscal_monitor.server.consultar_cndt_trabalhista", return_value={"consta": False}
    ) as mock_cndt:
        response = app.test_client().get(_cnpj_url(app, "/certidoes/dossie-fiscal.pdf"))

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    mock_cnd.assert_called_once_with("11.222.333/0001-44", "TOKEN123")
    mock_devedores.assert_called_once_with("11.222.333/0001-44", "TOKEN123")
    mock_fgts.assert_called_once_with("11.222.333/0001-44", "TOKEN123")
    mock_cndt.assert_called_once_with("11.222.333/0001-44", "TOKEN123")


def test_dossie_fiscal_automatico_cnd_falha_nao_bloqueia_as_demais(app, monkeypatch):
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")
    devedores_response = {
        "total_divida": 7359.68,
        "total_tributario": 0.0,
        "total_nao_tributario": 7359.68,
        "naturezas_debitos": [
            {"descricao": "FGTS", "total": 7359.68, "debitos": [{"inscricao": "FGAL1", "valor_divida": 7359.68}]}
        ],
    }
    with patch(
        "src.fiscal_monitor.server.consultar_cnd_federal",
        side_effect=ConsultaDebitosError("código 611: dados incompletos na origem"),
    ), patch(
        "src.fiscal_monitor.server.consultar_lista_devedores", return_value=devedores_response
    ) as mock_devedores, patch(
        "src.fiscal_monitor.server.enriquecer_com_dados_abertos", wraps=lambda conn, divida: divida
    ), patch(
        "src.fiscal_monitor.server.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}
    ), patch("src.fiscal_monitor.server.consultar_cndt_trabalhista", return_value={"consta": False}):
        response = app.test_client().get(_cnpj_url(app, "/certidoes/dossie-fiscal.pdf"))

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    mock_devedores.assert_called_once_with("11.222.333/0001-44", "TOKEN123")


def test_reforma_tributaria_requires_admin(app):
    response = app.test_client().get("/reforma-tributaria")
    assert response.status_code == 401


def test_reforma_tributaria_renders_form_without_faturamento(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get("/reforma-tributaria", headers=_basic_auth_header("admin", "senha-secreta"))
    assert response.status_code == 200


def test_reforma_tributaria_simulates_with_faturamento(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get(
        "/reforma-tributaria?faturamento=1000000", headers=_basic_auth_header("admin", "senha-secreta")
    )
    assert response.status_code == 200
    assert "Híbrido".encode() in response.data


def _xlsx_dados_abertos_bytes(numero_inscricao="FGAL1") -> bytes:
    import openpyxl
    from datetime import date

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "CPF_CNPJ", "TIPO_PESSOA", "TIPO_DEVEDOR", "NOME_DEVEDOR", "UF_DEVEDOR", "UNIDADE_RESPONSAVEL",
            "ENTIDADE_RESPONSAVEL", "UNIDADE_INSCRICAO", "NUMERO_INSCRICAO", "TIPO_SITUACAO_INSCRICAO",
            "SITUACAO_INSCRICAO", "RECEITA_PRINCIPAL", "DATA_INSCRICAO", "INDICADOR_AJUIZADO", "VALOR_CONSOLIDADO",
        ]
    )
    sheet.append(
        [
            "08.612.624/0001-71", "Pessoa jurídica", "Principal", "EMPRESA EXEMPLO", "AL", "ALAGOAS", "PGFN",
            "ALAGOAS", numero_inscricao, "Em cobrança", "INSCRITA", "Contribuições FGTS", date(2025, 1, 8),
            "NAO", "7359.68",
        ]
    )
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_pgfn_dados_abertos_requires_admin(app):
    response = app.test_client().get("/admin/pgfn-dados-abertos")
    assert response.status_code == 401


def test_pgfn_dados_abertos_renders_form(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get(
        "/admin/pgfn-dados-abertos", headers=_basic_auth_header("admin", "senha-secreta")
    )
    assert response.status_code == 200


def test_pgfn_dados_abertos_post_importa_xlsx(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().post(
        "/admin/pgfn-dados-abertos",
        data={
            "base_referencia": "2026-03",
            "arquivo": (io.BytesIO(_xlsx_dados_abertos_bytes()), "arquivo_lai_FGTS_5_202603.xlsx"),
        },
        content_type="multipart/form-data",
        headers=_basic_auth_header("admin", "senha-secreta"),
    )
    assert response.status_code == 200
    assert "1 inscri".encode() in response.data


def test_pgfn_dados_abertos_post_rejeita_arquivo_com_colunas_erradas(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["CPF/CNPJ", "Nome", "Valor Total"])
    sheet.append(["11.222.333/0001-44", "Empresa X", "1.000,00"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    response = app.test_client().post(
        "/admin/pgfn-dados-abertos",
        data={
            "base_referencia": "2026-03",
            "arquivo": (io.BytesIO(buffer.getvalue()), "lista_devedores.xlsx"),
        },
        content_type="multipart/form-data",
        headers=_basic_auth_header("admin", "senha-secreta"),
    )
    assert response.status_code == 400
    assert "Colunas esperadas".encode() in response.data


def test_diagnostico_infosimples_requires_admin(app):
    response = app.test_client().get("/admin/diagnostico/infosimples?cnpj=33.000.167/0001-01")
    assert response.status_code == 401


def test_diagnostico_infosimples_reports_token_not_configured(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    response = app.test_client().get(
        "/admin/diagnostico/infosimples?cnpj=33.000.167/0001-01", headers=_basic_auth_header("admin", "senha-secreta")
    )
    assert response.status_code == 200
    assert response.get_json() == {"cnpj": "33.000.167/0001-01", "infosimples_token_configurado": False}


def test_diagnostico_infosimples_calls_real_functions_and_returns_raw_response(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")

    with patch(
        "src.fiscal_monitor.server.consultar_cnd_federal",
        return_value={"tipo": "Negativa", "debitos_pgfn": False, "debitos_rfb": False},
    ) as mock_cnd, patch(
        "src.fiscal_monitor.server.consultar_lista_devedores", return_value=None
    ) as mock_devedores, patch(
        "src.fiscal_monitor.server.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}
    ) as mock_fgts, patch(
        "src.fiscal_monitor.server.consultar_cndt_trabalhista", return_value={"consta": False}
    ) as mock_cndt:
        response = app.test_client().get(
            "/admin/diagnostico/infosimples?cnpj=33.000.167/0001-01",
            headers=_basic_auth_header("admin", "senha-secreta"),
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data["infosimples_token_configurado"] is True
    assert data["cnd_federal"]["tipo"] == "Negativa"
    assert data["lista_devedores"] is None
    assert data["regularidade_fgts"]["situacao"] == "REGULAR"
    assert data["cndt_trabalhista"]["consta"] is False
    mock_cnd.assert_called_once_with("33.000.167/0001-01", "TOKEN123")
    mock_devedores.assert_called_once_with("33.000.167/0001-01", "TOKEN123")
    mock_fgts.assert_called_once_with("33.000.167/0001-01", "TOKEN123")
    mock_cndt.assert_called_once_with("33.000.167/0001-01", "TOKEN123")


def test_diagnostico_infosimples_surfaces_consulta_error(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-secreta")
    monkeypatch.setenv("INFOSIMPLES_API_TOKEN", "TOKEN123")

    with patch(
        "src.fiscal_monitor.server.consultar_cnd_federal", side_effect=ConsultaDebitosError("saldo insuficiente")
    ), patch(
        "src.fiscal_monitor.server.consultar_lista_devedores", side_effect=ConsultaDebitosError("saldo insuficiente")
    ), patch(
        "src.fiscal_monitor.server.consultar_regularidade_fgts", side_effect=ConsultaDebitosError("saldo insuficiente")
    ), patch(
        "src.fiscal_monitor.server.consultar_cndt_trabalhista", side_effect=ConsultaDebitosError("saldo insuficiente")
    ):
        response = app.test_client().get(
            "/admin/diagnostico/infosimples?cnpj=33.000.167/0001-01",
            headers=_basic_auth_header("admin", "senha-secreta"),
        )

    assert response.status_code == 200
    data = response.get_json()
    assert "saldo insuficiente" in data["cnd_federal_erro"]
    assert "saldo insuficiente" in data["lista_devedores_erro"]
    assert "saldo insuficiente" in data["regularidade_fgts_erro"]
    assert "saldo insuficiente" in data["cndt_trabalhista_erro"]

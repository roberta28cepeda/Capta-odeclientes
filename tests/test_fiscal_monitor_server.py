import os
import tempfile
from unittest.mock import patch

import pytest

from src.fiscal_monitor import storage
from src.fiscal_monitor.preanalise import ConsultaCnpjError
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
    return application


def test_health_returns_ok(app):
    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_tenants_list_shows_tenant_and_cnpj_count(app):
    response = app.test_client().get("/tenants")
    assert response.status_code == 200
    assert b"Escrit\xc3\xb3rio A" in response.data or "Escritório A".encode() in response.data


def test_tenant_detail_returns_404_for_missing_tenant(app):
    response = app.test_client().get("/tenants/999")
    assert response.status_code == 404


def test_tenant_detail_shows_open_finding(app):
    tenant_id = app.config["_tenant_id"]
    response = app.test_client().get(f"/tenants/{tenant_id}")
    assert response.status_code == 200
    assert "DAS 08/2026".encode() in response.data


def test_tenant_findings_json_returns_open_findings(app):
    tenant_id = app.config["_tenant_id"]
    response = app.test_client().get(f"/tenants/{tenant_id}/findings.json")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    assert data[0]["cnpj"] == "11.222.333/0001-44"
    assert data[0]["tipo"] == "das"
    assert data[0]["status"] == "nova"


def test_tenant_findings_json_returns_404_for_missing_tenant(app):
    response = app.test_client().get("/tenants/999/findings.json")
    assert response.status_code == 404


def test_tenant_detail_shows_portfolio_and_regime(app):
    tenant_id = app.config["_tenant_id"]
    response = app.test_client().get(f"/tenants/{tenant_id}")
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
    response = application.test_client().get(f"/tenants/{tenant.id}/cnpjs/{cnpj.id}/historico")

    assert response.status_code == 200
    assert b"Multa X" in response.data


def test_tenant_detail_shows_sublimite_alert_for_simples_cnpj(db_path):
    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório C")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "33.444.555/0001-66", regime_tributario="simples")
    for mes in range(1, 13):
        storage.record_faturamento(conn, cnpj.id, f"2026-{mes:02d}", 310_000.0)
    conn.close()

    application = create_app(db_path=db_path)
    response = application.test_client().get(f"/tenants/{tenant.id}", query_string={"referencia": "2026-12"})

    assert response.status_code == 200
    assert b"sublimite_estourado" in response.data


def test_pre_analise_form_renders_on_get(app):
    response = app.test_client().get("/pre-analise")
    assert response.status_code == 200
    assert b"Pr\xc3\xa9-An\xc3\xa1lise Fiscal" in response.data


def test_pre_analise_post_rejects_invalid_cnpj(app):
    response = app.test_client().post("/pre-analise", data={"cnpj": "00.000.000/0000-00"})
    assert response.status_code == 400
    assert "CNPJ inválido".encode() in response.data


def test_pre_analise_post_returns_pdf_for_valid_cnpj(app):
    with patch("src.fiscal_monitor.server.consultar_cnpj_publico", return_value=SAMPLE_CNPJ_RESPONSE):
        response = app.test_client().post(
            "/pre-analise", data={"cnpj": "33.000.167/0001-01", "escritorio_nome": "Escritório X"}
        )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data[:4] == b"%PDF"


def test_pre_analise_post_shows_error_when_consulta_falha(app):
    with patch(
        "src.fiscal_monitor.server.consultar_cnpj_publico",
        side_effect=ConsultaCnpjError("CNPJ 33.000.167/0001-01 não encontrado."),
    ):
        response = app.test_client().post("/pre-analise", data={"cnpj": "33.000.167/0001-01"})

    assert response.status_code == 400
    assert "não encontrado".encode() in response.data


def test_cnpj_history_returns_404_for_cnpj_of_another_tenant(app, db_path):
    conn = storage.connect(db_path)
    outro_tenant = storage.create_tenant(conn, "Escritório B")
    outro_cnpj = storage.upsert_cnpj(conn, outro_tenant.id, "22.333.444/0001-55")
    conn.close()

    tenant_id = app.config["_tenant_id"]
    response = app.test_client().get(f"/tenants/{tenant_id}/cnpjs/{outro_cnpj.id}/historico")

    assert response.status_code == 404

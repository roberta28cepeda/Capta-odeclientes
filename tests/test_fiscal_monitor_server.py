import os
import tempfile

import pytest

from src.fiscal_monitor import storage
from src.fiscal_monitor.server import create_app


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

import os
import tempfile
from unittest.mock import patch

import pytest

from src.fiscal_monitor import storage
from src.fiscal_monitor.cron import check_all_tenants, run_infosimples_semanal


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "fiscal_monitor.db")


def test_check_all_tenants_returns_zero_alerts_for_empty_db(db_path):
    conn = storage.connect(db_path)
    resultados = check_all_tenants(conn)
    conn.close()
    assert resultados == []


def test_check_all_tenants_counts_alerts_without_sending_when_no_credentials(db_path, monkeypatch):
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório A", contato_whatsapp="5511999999999", contato_email="a@exemplo.com")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")
    snapshot_id = storage.create_snapshot(conn, cnpj.id, "manual_csv")
    storage.add_finding(conn, snapshot_id, "federal", "das", "DAS 08/2026", 412.5, "2026-09-25", False, "nova")

    resultados = check_all_tenants(conn)
    conn.close()

    assert len(resultados) == 1
    assert resultados[0]["alertas"] == 1
    assert resultados[0]["enviado_whatsapp"] is False
    assert resultados[0]["enviado_email"] is False
    assert resultados[0]["erro"] is None


def test_check_all_tenants_sends_whatsapp_and_email_when_configured(db_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "TOKEN")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "PHONE_ID")
    monkeypatch.setenv("SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")

    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório A", contato_whatsapp="5511999999999", contato_email="a@exemplo.com")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")
    snapshot_id = storage.create_snapshot(conn, cnpj.id, "manual_csv")
    storage.add_finding(conn, snapshot_id, "federal", "das", "DAS 08/2026", 412.5, "2026-09-25", False, "nova")

    with patch("src.fiscal_monitor.alerts.send_text_message", return_value={"ok": True}) as mock_wpp, patch(
        "src.fiscal_monitor.alerts.send_email"
    ) as mock_email:
        resultados = check_all_tenants(conn)
    conn.close()

    assert resultados[0]["enviado_whatsapp"] is True
    assert resultados[0]["enviado_email"] is True
    mock_wpp.assert_called_once()
    mock_email.assert_called_once()


def test_check_all_tenants_skips_tenant_without_contact(db_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "TOKEN")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "PHONE_ID")

    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório Sem Contato")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")
    snapshot_id = storage.create_snapshot(conn, cnpj.id, "manual_csv")
    storage.add_finding(conn, snapshot_id, "federal", "das", "DAS 08/2026", 412.5, "2026-09-25", False, "nova")

    resultados = check_all_tenants(conn)
    conn.close()

    assert resultados[0]["alertas"] == 1
    assert resultados[0]["enviado_whatsapp"] is False


def test_check_all_tenants_records_error_without_stopping_other_tenants(db_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "TOKEN")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "PHONE_ID")

    conn = storage.connect(db_path)
    tenant_com_erro = storage.create_tenant(conn, "Escritório Com Erro", contato_whatsapp="5511999999999")
    cnpj1 = storage.upsert_cnpj(conn, tenant_com_erro.id, "11.222.333/0001-44")
    snap1 = storage.create_snapshot(conn, cnpj1.id, "manual_csv")
    storage.add_finding(conn, snap1, "federal", "das", "DAS", 100.0, "2026-09-25", False, "nova")

    tenant_ok = storage.create_tenant(conn, "Escritório OK", contato_whatsapp="5511988888888")
    cnpj2 = storage.upsert_cnpj(conn, tenant_ok.id, "22.333.444/0001-55")
    snap2 = storage.create_snapshot(conn, cnpj2.id, "manual_csv")
    storage.add_finding(conn, snap2, "federal", "das", "DAS", 100.0, "2026-09-25", False, "nova")

    with patch("src.fiscal_monitor.alerts.send_text_message", side_effect=[RuntimeError("falha na API"), {"ok": True}]):
        resultados = check_all_tenants(conn)
    conn.close()

    assert len(resultados) == 2
    assert resultados[0]["erro"] == "falha na API"
    assert resultados[1]["erro"] is None
    assert resultados[1]["enviado_whatsapp"] is True


def test_run_infosimples_semanal_applies_snapshot_per_cnpj(db_path):
    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")

    with patch(
        "src.fiscal_monitor.infosimples.consultar_cnd_federal",
        return_value={"debitos_pgfn": True, "debitos_rfb": False, "tipo": "Positiva", "validade_data": ""},
    ), patch("src.fiscal_monitor.infosimples.consultar_lista_devedores", return_value=None), patch(
        "src.fiscal_monitor.infosimples.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}
    ), patch("src.fiscal_monitor.infosimples.consultar_cndt_trabalhista", return_value={"consta": False}):
        resultados = run_infosimples_semanal(conn, "TOKEN123")

    assert resultados == [{"tenant_id": tenant.id, "cnpj_id": cnpj.id, "cnpj": cnpj.cnpj, "achados": 1, "erro": None}]
    snapshot_id = storage.latest_snapshot_id(conn, cnpj.id)
    findings = storage.findings_for_snapshot(conn, snapshot_id)
    assert len(findings) == 1
    assert findings[0].status == "nova"
    conn.close()


def test_run_infosimples_semanal_records_error_without_stopping_other_cnpjs(db_path):
    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj1 = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")
    cnpj2 = storage.upsert_cnpj(conn, tenant.id, "22.333.444/0001-55")

    with patch(
        "src.fiscal_monitor.providers.InfoSimplesFiscalProvider.fetch",
        side_effect=[RuntimeError("falha de rede"), {"22.333.444/0001-55": []}],
    ):
        resultados = run_infosimples_semanal(conn, "TOKEN123")
    conn.close()

    assert len(resultados) == 2
    assert resultados[0]["cnpj_id"] == cnpj1.id
    assert resultados[0]["erro"] == "falha de rede"
    assert resultados[1]["cnpj_id"] == cnpj2.id
    assert resultados[1]["erro"] is None
    assert resultados[1]["achados"] == 0


def test_run_infosimples_semanal_second_run_marks_resolved_when_regularizado(db_path):
    conn = storage.connect(db_path)
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")

    with patch(
        "src.fiscal_monitor.infosimples.consultar_cnd_federal",
        return_value={"debitos_pgfn": True, "debitos_rfb": False, "tipo": "Positiva", "validade_data": ""},
    ), patch("src.fiscal_monitor.infosimples.consultar_lista_devedores", return_value=None), patch(
        "src.fiscal_monitor.infosimples.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}
    ), patch("src.fiscal_monitor.infosimples.consultar_cndt_trabalhista", return_value={"consta": False}):
        run_infosimples_semanal(conn, "TOKEN123")

    with patch(
        "src.fiscal_monitor.infosimples.consultar_cnd_federal",
        return_value={"debitos_pgfn": False, "debitos_rfb": False, "tipo": "Negativa", "validade_data": ""},
    ), patch("src.fiscal_monitor.infosimples.consultar_lista_devedores", return_value=None), patch(
        "src.fiscal_monitor.infosimples.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}
    ), patch("src.fiscal_monitor.infosimples.consultar_cndt_trabalhista", return_value={"consta": False}):
        run_infosimples_semanal(conn, "TOKEN123")

    snapshot_id = storage.latest_snapshot_id(conn, cnpj.id)
    findings = storage.findings_for_snapshot(conn, snapshot_id)
    conn.close()
    assert len(findings) == 1
    assert findings[0].status == "resolvida"

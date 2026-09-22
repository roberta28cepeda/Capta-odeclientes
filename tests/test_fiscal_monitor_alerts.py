from unittest.mock import patch

from src.fiscal_monitor import alerts, monitor, storage

TENANT_COM_WHATSAPP = storage.Tenant(id=1, nome="Escritório A", contato_whatsapp="5511999999999", plano=None, criado_em="")
TENANT_SEM_WHATSAPP = storage.Tenant(id=2, nome="Escritório B", contato_whatsapp=None, plano=None, criado_em="")

CNPJ = storage.Cnpj(id=1, tenant_id=1, cnpj="11.222.333/0001-44", razao_social="Contábil Exemplo", nome_fantasia=None, ativo=True)
FINDING = storage.Finding(1, 1, "federal", "das", "DAS 08/2026", 412.5, "2026-09-25", False, "nova")
ALERT = monitor.AlertItem(cnpj=CNPJ, finding=FINDING, motivo="das_vencendo")


def test_format_alert_text_includes_valor_and_vencimento():
    text = alerts.format_alert_text(ALERT)

    assert "Contábil Exemplo" in text
    assert "DAS 08/2026" in text
    assert "R$ 412.50" in text or "R$ 412,50" in text
    assert "2026-09-25" in text


def test_format_alerts_summary_handles_empty_list():
    summary = alerts.format_alerts_summary(TENANT_COM_WHATSAPP, [])
    assert "Nenhum alerta" in summary


def test_format_alerts_summary_counts_items():
    summary = alerts.format_alerts_summary(TENANT_COM_WHATSAPP, [ALERT])
    assert summary.startswith("1 alerta(s)")


def test_send_whatsapp_alert_returns_none_without_contact():
    assert alerts.send_whatsapp_alert(TENANT_SEM_WHATSAPP, [ALERT], "PHONE_ID", "TOKEN") is None


def test_send_whatsapp_alert_returns_none_without_alerts():
    assert alerts.send_whatsapp_alert(TENANT_COM_WHATSAPP, [], "PHONE_ID", "TOKEN") is None


def test_send_whatsapp_alert_sends_text_when_contact_and_alerts_exist():
    with patch("src.fiscal_monitor.alerts.send_text_message", return_value={"ok": True}) as mock_send:
        result = alerts.send_whatsapp_alert(TENANT_COM_WHATSAPP, [ALERT], "PHONE_ID", "TOKEN")

    assert result == {"ok": True}
    mock_send.assert_called_once()
    call_args = mock_send.call_args[0]
    assert call_args[0] == "5511999999999"
    assert call_args[2] == "PHONE_ID"
    assert call_args[3] == "TOKEN"


def test_send_whatsapp_report_returns_none_without_contact():
    assert alerts.send_whatsapp_report(TENANT_SEM_WHATSAPP, "output/relatorio.pdf", "PHONE_ID", "TOKEN") is None


def test_send_whatsapp_report_sends_pdf_when_contact_exists():
    with patch("src.fiscal_monitor.alerts.send_pdf", return_value={"ok": True}) as mock_send:
        result = alerts.send_whatsapp_report(TENANT_COM_WHATSAPP, "output/relatorio.pdf", "PHONE_ID", "TOKEN")

    assert result == {"ok": True}
    mock_send.assert_called_once_with(
        "output/relatorio.pdf", "5511999999999", "PHONE_ID", "TOKEN", caption="Relatório fiscal — Escritório A"
    )


CNPJ_SIMPLES = storage.Cnpj(id=2, tenant_id=1, cnpj="99.888.777/0001-11", razao_social="Simples LTDA", nome_fantasia=None, ativo=True, regime_tributario="simples")
SUBLIMITE_ITEM = monitor.SublimiteAlertItem(cnpj=CNPJ_SIMPLES, faturamento_12m=3_700_000.0, label="sublimite_estourado")


def test_format_sublimite_alert_includes_label_and_faturamento():
    text = alerts.format_sublimite_alert(SUBLIMITE_ITEM)

    assert "Simples LTDA" in text
    assert "Sublimite do Simples ultrapassado" in text
    assert "3.700.000,00" in text or "3,700,000.00" in text


def test_format_sublimite_summary_handles_empty_list():
    summary = alerts.format_sublimite_summary(TENANT_COM_WHATSAPP, [])
    assert "Nenhum CNPJ" in summary


def test_format_sublimite_summary_counts_items():
    summary = alerts.format_sublimite_summary(TENANT_COM_WHATSAPP, [SUBLIMITE_ITEM])
    assert summary.startswith("1 CNPJ(s)")

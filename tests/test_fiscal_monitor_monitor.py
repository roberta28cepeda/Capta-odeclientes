from datetime import date

import pytest

from src.fiscal_monitor import monitor, storage
from src.fiscal_monitor.providers import RawFinding


def _conn_with_cnpj():
    conn = storage.connect(":memory:")
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")
    return conn, tenant, cnpj


def _raw(esfera="federal", tipo="multa", descricao="Multa X", valor=100.0, vencimento=None, pago=False):
    return RawFinding(
        cnpj="11.222.333/0001-44", esfera=esfera, tipo=tipo, descricao=descricao, valor=valor,
        vencimento=vencimento, pago=pago,
    )


def test_apply_snapshot_first_import_marks_everything_nova():
    conn, _tenant, cnpj = _conn_with_cnpj()

    saved = monitor.apply_snapshot(conn, cnpj, "manual_csv", [_raw()])

    assert len(saved) == 1
    assert saved[0].status == monitor.STATUS_NOVA


def test_apply_snapshot_repeated_finding_becomes_recorrente():
    conn, _tenant, cnpj = _conn_with_cnpj()
    monitor.apply_snapshot(conn, cnpj, "manual_csv", [_raw()])

    saved = monitor.apply_snapshot(conn, cnpj, "manual_csv", [_raw()])

    assert len(saved) == 1
    assert saved[0].status == monitor.STATUS_RECORRENTE


def test_apply_snapshot_missing_finding_becomes_resolvida():
    conn, _tenant, cnpj = _conn_with_cnpj()
    monitor.apply_snapshot(conn, cnpj, "manual_csv", [_raw(descricao="Multa X")])

    saved = monitor.apply_snapshot(conn, cnpj, "manual_csv", [])

    assert len(saved) == 1
    assert saved[0].status == monitor.STATUS_RESOLVIDA


def test_apply_snapshot_resolved_finding_reappearing_is_nova_again():
    conn, _tenant, cnpj = _conn_with_cnpj()
    monitor.apply_snapshot(conn, cnpj, "manual_csv", [_raw(descricao="Multa X")])
    monitor.apply_snapshot(conn, cnpj, "manual_csv", [])  # resolvida

    saved = monitor.apply_snapshot(conn, cnpj, "manual_csv", [_raw(descricao="Multa X")])

    assert saved[0].status == monitor.STATUS_NOVA


def test_days_until_computes_difference():
    assert monitor.days_until("2026-09-25", today=date(2026, 9, 20)) == 5
    assert monitor.days_until("2026-09-15", today=date(2026, 9, 20)) == -5


def test_days_until_returns_none_for_missing_or_invalid():
    assert monitor.days_until(None) is None
    assert monitor.days_until("data-invalida") is None


def test_findings_needing_alert_flags_nova_and_das_proximo_do_vencimento():
    cnpj = storage.Cnpj(id=1, tenant_id=1, cnpj="11.222.333/0001-44", razao_social=None, nome_fantasia=None, ativo=True)
    findings = [
        storage.Finding(1, 1, "federal", "multa", "Multa nova", 100.0, None, False, monitor.STATUS_NOVA),
        storage.Finding(2, 1, "federal", "das", "DAS 08/2026", 400.0, "2026-09-25", False, monitor.STATUS_RECORRENTE),
        storage.Finding(3, 1, "federal", "das", "DAS pago", 400.0, "2026-09-25", True, monitor.STATUS_RECORRENTE),
        storage.Finding(4, 1, "federal", "das", "DAS longe", 400.0, "2026-12-25", False, monitor.STATUS_RECORRENTE),
    ]

    alerts = monitor.findings_needing_alert(cnpj, findings, dias_alerta=5, today=date(2026, 9, 20))

    motivos = {(a.finding.descricao, a.motivo) for a in alerts}
    assert motivos == {("Multa nova", "novo_achado"), ("DAS 08/2026", "das_vencendo")}


def test_findings_needing_alert_flags_cnd_vencendo_regardless_of_pago():
    cnpj = storage.Cnpj(id=1, tenant_id=1, cnpj="11.222.333/0001-44", razao_social=None, nome_fantasia=None, ativo=True)
    findings = [
        storage.Finding(1, 1, "federal", "cnd", "CND Federal", None, "2026-09-24", False, monitor.STATUS_RECORRENTE),
    ]

    alerts = monitor.findings_needing_alert(cnpj, findings, dias_alerta=5, today=date(2026, 9, 20))

    assert len(alerts) == 1
    assert alerts[0].motivo == "cnd_vencendo"


def test_findings_needing_alert_flags_parcelamento_vencendo_when_nao_pago():
    cnpj = storage.Cnpj(id=1, tenant_id=1, cnpj="11.222.333/0001-44", razao_social=None, nome_fantasia=None, ativo=True)
    findings = [
        storage.Finding(1, 1, "federal", "parcelamento", "Parcela 4/60", 620.0, "2026-09-30", False, monitor.STATUS_RECORRENTE),
        storage.Finding(2, 1, "federal", "parcelamento", "Parcela paga", 620.0, "2026-09-30", True, monitor.STATUS_RECORRENTE),
    ]

    alerts = monitor.findings_needing_alert(cnpj, findings, dias_alerta=15, today=date(2026, 9, 20))

    assert len(alerts) == 1
    assert alerts[0].finding.descricao == "Parcela 4/60"
    assert alerts[0].motivo == "parcelamento_vencendo"


def test_findings_needing_alert_ignores_caixa_postal_when_recorrente():
    cnpj = storage.Cnpj(id=1, tenant_id=1, cnpj="11.222.333/0001-44", razao_social=None, nome_fantasia=None, ativo=True)
    findings = [
        storage.Finding(1, 1, "federal", "caixa_postal", "Mensagem antiga", None, None, False, monitor.STATUS_RECORRENTE),
    ]

    assert monitor.findings_needing_alert(cnpj, findings, today=date(2026, 9, 20)) == []


@pytest.mark.parametrize(
    "faturamento,expected_label",
    [
        (2_000_000.0, None),
        (2_900_000.0, "proximo_sublimite"),
        (3_700_000.0, "sublimite_estourado"),
        (3_900_000.0, "proximo_teto"),
        (4_900_000.0, "teto_estourado"),
    ],
)
def test_sublimite_label_thresholds(faturamento, expected_label):
    assert monitor._sublimite_label(faturamento) == expected_label


def test_check_sublimite_simples_only_considers_regime_simples():
    conn = storage.connect(":memory:")
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj_simples = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44", regime_tributario="simples")
    cnpj_presumido = storage.upsert_cnpj(conn, tenant.id, "55.666.777/0001-88", regime_tributario="presumido")

    for cnpj in (cnpj_simples, cnpj_presumido):
        for mes in range(1, 13):
            storage.record_faturamento(conn, cnpj.id, f"2026-{mes:02d}", 310_000.0)

    alerts = monitor.check_sublimite_simples(conn, tenant.id, "2026-12")

    assert len(alerts) == 1
    assert alerts[0].cnpj.cnpj == "11.222.333/0001-44"
    assert alerts[0].label == "sublimite_estourado"


def test_check_tenant_uses_latest_snapshot_per_cnpj():
    conn, tenant, cnpj = _conn_with_cnpj()
    monitor.apply_snapshot(conn, cnpj, "manual_csv", [_raw(tipo="das", vencimento="2026-09-25")])

    alerts = monitor.check_tenant(conn, tenant.id, dias_alerta=5, today=date(2026, 9, 20))

    assert len(alerts) == 1
    assert alerts[0].motivo == "novo_achado"


def test_check_tenant_skips_cnpjs_without_snapshot():
    conn, tenant, _cnpj = _conn_with_cnpj()
    storage.upsert_cnpj(conn, tenant.id, "55.666.777/0001-88")

    alerts = monitor.check_tenant(conn, tenant.id)

    assert alerts == []

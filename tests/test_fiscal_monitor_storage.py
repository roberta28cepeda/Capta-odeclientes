from src.fiscal_monitor import storage


def _conn():
    return storage.connect(":memory:")


def test_create_and_list_tenants():
    conn = _conn()
    storage.create_tenant(conn, "Escritório A", contato_whatsapp="5511999999999", plano="starter")
    storage.create_tenant(conn, "Escritório B")

    tenants = storage.list_tenants(conn)

    assert [t.nome for t in tenants] == ["Escritório A", "Escritório B"]
    assert tenants[0].contato_whatsapp == "5511999999999"
    assert tenants[0].plano == "starter"


def test_get_tenant_returns_none_when_missing():
    conn = _conn()
    assert storage.get_tenant(conn, 999) is None


def test_upsert_cnpj_inserts_then_updates_on_conflict():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")

    storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44", razao_social="Nome Antigo")
    storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44", razao_social="Nome Novo", nome_fantasia="Fantasia")

    cnpjs = storage.list_cnpjs(conn, tenant.id)

    assert len(cnpjs) == 1
    assert cnpjs[0].razao_social == "Nome Novo"
    assert cnpjs[0].nome_fantasia == "Fantasia"


def test_get_cnpj_by_number_returns_none_when_not_in_portfolio():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    assert storage.get_cnpj_by_number(conn, tenant.id, "00.000.000/0001-00") is None


def test_snapshot_and_findings_roundtrip():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")

    assert storage.latest_snapshot_id(conn, cnpj.id) is None

    snapshot_id = storage.create_snapshot(conn, cnpj.id, "manual_csv")
    storage.add_finding(conn, snapshot_id, "federal", "multa", "Multa X", 100.0, None, False, "nova")

    assert storage.latest_snapshot_id(conn, cnpj.id) == snapshot_id
    findings = storage.findings_for_snapshot(conn, snapshot_id)
    assert len(findings) == 1
    assert findings[0].descricao == "Multa X"
    assert findings[0].status == "nova"
    assert findings[0].pago is False


def test_findings_by_cnpj_for_tenant_includes_cnpjs_without_findings_and_excludes_resolvidas():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj_com_achado = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")
    cnpj_sem_achado = storage.upsert_cnpj(conn, tenant.id, "55.666.777/0001-88")

    snapshot_id = storage.create_snapshot(conn, cnpj_com_achado.id, "manual_csv")
    storage.add_finding(conn, snapshot_id, "federal", "das", "DAS 08/2026", 400.0, "2026-09-25", False, "nova")
    storage.add_finding(conn, snapshot_id, "federal", "multa", "Multa antiga", 50.0, None, False, "resolvida")

    result = storage.findings_by_cnpj_for_tenant(conn, tenant.id)

    by_cnpj_id = {cnpj.id: findings for cnpj, findings in result}
    assert len(by_cnpj_id[cnpj_com_achado.id]) == 1
    assert by_cnpj_id[cnpj_com_achado.id][0].descricao == "DAS 08/2026"
    assert by_cnpj_id[cnpj_sem_achado.id] == []

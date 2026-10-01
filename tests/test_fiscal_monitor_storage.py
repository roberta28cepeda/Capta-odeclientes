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


def test_create_tenant_generates_unique_acesso_token():
    conn = _conn()
    tenant_a = storage.create_tenant(conn, "Escritório A")
    tenant_b = storage.create_tenant(conn, "Escritório B")

    assert tenant_a.acesso_token
    assert tenant_b.acesso_token
    assert tenant_a.acesso_token != tenant_b.acesso_token
    assert storage.get_tenant(conn, tenant_a.id).acesso_token == tenant_a.acesso_token


def test_upsert_cnpj_inserts_then_updates_on_conflict():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")

    storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44", razao_social="Nome Antigo")
    storage.upsert_cnpj(
        conn,
        tenant.id,
        "11.222.333/0001-44",
        razao_social="Nome Novo",
        nome_fantasia="Fantasia",
        regime_tributario="simples",
    )

    cnpjs = storage.list_cnpjs(conn, tenant.id)

    assert len(cnpjs) == 1
    assert cnpjs[0].razao_social == "Nome Novo"
    assert cnpjs[0].nome_fantasia == "Fantasia"
    assert cnpjs[0].regime_tributario == "simples"


def test_get_cnpj_returns_by_id():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")

    assert storage.get_cnpj(conn, cnpj.id) == cnpj
    assert storage.get_cnpj(conn, 999) is None


def test_connect_is_idempotent_across_reopens(tmp_path):
    db_path = str(tmp_path / "fm.db")
    conn1 = storage.connect(db_path)
    tenant = storage.create_tenant(conn1, "Escritório A")
    storage.upsert_cnpj(conn1, tenant.id, "11.222.333/0001-44", regime_tributario="mei")
    conn1.close()

    # Reabrir simula uma versão anterior do schema recebendo a migração de novo.
    conn2 = storage.connect(db_path)
    cnpjs = storage.list_cnpjs(conn2, tenant.id)

    assert cnpjs[0].regime_tributario == "mei"


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


def test_record_faturamento_upserts_by_competencia():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")

    storage.record_faturamento(conn, cnpj.id, "2026-09", 100_000.0)
    storage.record_faturamento(conn, cnpj.id, "2026-09", 150_000.0)  # sobrescreve

    assert storage.faturamento_acumulado_12m(conn, cnpj.id, "2026-09") == 150_000.0


def test_faturamento_acumulado_12m_sums_last_12_months_only():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")

    storage.record_faturamento(conn, cnpj.id, "2025-08", 999_999.0)  # fora da janela de 12m
    for mes in range(10, 13):
        storage.record_faturamento(conn, cnpj.id, f"2025-{mes:02d}", 100_000.0)
    for mes in range(1, 10):
        storage.record_faturamento(conn, cnpj.id, f"2026-{mes:02d}", 100_000.0)

    total = storage.faturamento_acumulado_12m(conn, cnpj.id, "2026-09")

    assert total == 1_200_000.0  # 12 meses de 100k, sem contar o de 2025-08


def test_all_findings_for_cnpj_includes_resolvidas_most_recent_first():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")

    snap1 = storage.create_snapshot(conn, cnpj.id, "manual_csv")
    storage.add_finding(conn, snap1, "federal", "multa", "Multa X", 100.0, None, False, "nova")
    snap2 = storage.create_snapshot(conn, cnpj.id, "manual_csv")
    storage.add_finding(conn, snap2, "federal", "multa", "Multa X", None, None, False, "resolvida")

    historico = storage.all_findings_for_cnpj(conn, cnpj.id)

    assert len(historico) == 2
    assert historico[0][2].status == "resolvida"  # mais recente primeiro
    assert historico[1][2].status == "nova"


def test_create_and_get_admin_user_by_username():
    conn = _conn()
    storage.create_admin_user(conn, "maria", "hash-fake", nome="Maria")

    usuario = storage.get_admin_user_by_username(conn, "maria")

    assert usuario is not None
    assert usuario.nome == "Maria"
    assert usuario.password_hash == "hash-fake"
    assert usuario.ativo is True


def test_get_admin_user_by_username_returns_none_when_missing():
    conn = _conn()
    assert storage.get_admin_user_by_username(conn, "ninguem") is None


def test_list_admin_users_returns_all_in_order():
    conn = _conn()
    storage.create_admin_user(conn, "maria", "hash-a")
    storage.create_admin_user(conn, "joao", "hash-b")

    usuarios = storage.list_admin_users(conn)

    assert [u.username for u in usuarios] == ["maria", "joao"]


def test_set_admin_user_ativo_toggles_flag():
    conn = _conn()
    usuario = storage.create_admin_user(conn, "maria", "hash-a")

    storage.set_admin_user_ativo(conn, usuario.id, False)

    assert storage.get_admin_user_by_username(conn, "maria").ativo is False


def test_upsert_cnpj_stores_and_preserves_uf():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44", uf="SP")

    cnpj = storage.get_cnpj_by_number(conn, tenant.id, "11.222.333/0001-44")
    assert cnpj.uf == "SP"

    # upsert sem uf não apaga o uf já salvo
    storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44", razao_social="Novo Nome")
    assert storage.get_cnpj_by_number(conn, tenant.id, "11.222.333/0001-44").uf == "SP"


def test_create_and_list_obrigacoes():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")

    storage.create_obrigacao(conn, cnpj.id, "DAS", "2026-10-20")
    storage.create_obrigacao(conn, cnpj.id, "DCTFWeb", "2026-10-15")

    obrigacoes = storage.list_obrigacoes(conn, cnpj.id)

    assert [o.tipo for o in obrigacoes] == ["DCTFWeb", "DAS"]  # ordenado por vencimento
    assert all(o.status == "pendente" for o in obrigacoes)


def test_marcar_obrigacao_entregue():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")
    obrigacao = storage.create_obrigacao(conn, cnpj.id, "DAS", "2026-10-20")

    storage.marcar_obrigacao_entregue(conn, obrigacao.id)

    assert storage.get_obrigacao(conn, obrigacao.id).status == "entregue"


def test_create_and_get_certidao_with_arquivo():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")

    certidao = storage.create_certidao(
        conn, cnpj.id, "federal", "123ABC", "2026-09-01", "2027-03-01", "certidao.pdf", b"%PDF-1.4 conteudo"
    )

    assert certidao.orgao == "federal"
    assert storage.get_certidao(conn, certidao.id).numero == "123ABC"
    assert storage.get_certidao_arquivo(conn, certidao.id) == b"%PDF-1.4 conteudo"


def test_latest_certidoes_by_orgao_returns_most_recent_per_orgao():
    conn = _conn()
    tenant = storage.create_tenant(conn, "Escritório A")
    cnpj = storage.upsert_cnpj(conn, tenant.id, "11.222.333/0001-44")

    storage.create_certidao(conn, cnpj.id, "federal", None, "2026-01-01", "2026-06-01", "antiga.pdf", b"antiga")
    storage.create_certidao(conn, cnpj.id, "federal", None, "2026-09-01", "2027-03-01", "nova.pdf", b"nova")
    storage.create_certidao(conn, cnpj.id, "sp", None, "2026-09-01", "2026-10-01", "sp.pdf", b"sp")

    atuais = storage.latest_certidoes_by_orgao(conn, cnpj.id)

    assert set(atuais.keys()) == {"federal", "sp"}
    assert atuais["federal"].arquivo_nome == "nova.pdf"


def test_get_certidao_arquivo_returns_none_when_missing():
    conn = _conn()
    assert storage.get_certidao_arquivo(conn, 999) is None

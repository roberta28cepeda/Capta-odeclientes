from src.campaigns import storage
from src.campaigns.models import TIPO_INICIAL

TESE = "transportadoras_pgfn"
OUTRA_TESE = "contadores_certificado"


def _conn():
    return storage.connect(":memory:")


def test_create_lead_and_get_by_cnpj():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com")

    assert lead.cnpj == "11.222.333/0001-44"
    assert lead.tese == TESE
    assert lead.status == "ativo"
    assert storage.get_lead_by_cnpj(conn, "11.222.333/0001-44", TESE).id == lead.id


def test_create_lead_upserts_on_conflict_keeping_existing_email():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Nome Antigo", email="antigo@exemplo.com")
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Nome Novo", email="novo@exemplo.com")

    assert lead.razao_social == "Nome Novo"
    assert lead.email == "antigo@exemplo.com"  # não sobrescreve e-mail já preenchido


def test_same_cnpj_can_exist_in_two_different_teses():
    conn = _conn()
    lead_a = storage.create_lead(conn, "11.222.333/0001-44", TESE)
    lead_b = storage.create_lead(conn, "11.222.333/0001-44", OUTRA_TESE)

    assert lead_a.id != lead_b.id
    assert lead_a.tese == TESE
    assert lead_b.tese == OUTRA_TESE


def test_bulk_create_leads_inserts_many_at_once():
    conn = _conn()
    leads = [
        {"cnpj": "11.222.333/0001-44", "razao_social": "Empresa X", "email": None, "valor_divida": 1000.0},
        {"cnpj": "22.333.444/0001-55", "razao_social": "Empresa Y", "email": "y@exemplo.com", "valor_divida": 2000.0},
    ]

    count = storage.bulk_create_leads(conn, TESE, leads)

    assert count == 2
    assert len(storage.list_leads(conn, tese=TESE)) == 2
    assert storage.get_lead_by_cnpj(conn, "22.333.444/0001-55", TESE).valor_divida == 2000.0


def test_bulk_create_leads_upserts_on_conflict():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Nome Antigo", email="antigo@exemplo.com")

    storage.bulk_create_leads(
        conn, TESE, [{"cnpj": "11.222.333/0001-44", "razao_social": "Nome Novo", "email": None, "valor_divida": 500.0}]
    )

    lead = storage.get_lead_by_cnpj(conn, "11.222.333/0001-44", TESE)
    assert lead.razao_social == "Nome Novo"
    assert lead.email == "antigo@exemplo.com"  # não sobrescreve e-mail já preenchido
    assert lead.valor_divida == 500.0


def test_bulk_create_leads_handles_empty_list():
    conn = _conn()
    assert storage.bulk_create_leads(conn, TESE, []) == 0


def test_aparar_leads_por_tese_keeps_highest_valor_divida():
    conn = _conn()
    storage.bulk_create_leads(
        conn,
        TESE,
        [
            {"cnpj": "11.111.111/0001-11", "razao_social": "Baixa", "email": None, "valor_divida": 100.0},
            {"cnpj": "22.222.222/0001-22", "razao_social": "Alta", "email": None, "valor_divida": 9000.0},
            {"cnpj": "33.333.333/0001-33", "razao_social": "Media", "email": None, "valor_divida": 500.0},
        ],
    )

    apagados = storage.aparar_leads_por_tese(conn, TESE, 2)

    assert apagados == 1
    restantes = {lead.cnpj for lead in storage.list_leads(conn, tese=TESE)}
    assert restantes == {"22.222.222/0001-22", "33.333.333/0001-33"}


def test_aparar_leads_por_tese_treats_null_valor_divida_as_lowest():
    conn = _conn()
    storage.bulk_create_leads(
        conn,
        TESE,
        [
            {"cnpj": "11.111.111/0001-11", "razao_social": "Sem valor", "email": None, "valor_divida": None},
            {"cnpj": "22.222.222/0001-22", "razao_social": "Com valor", "email": None, "valor_divida": 50.0},
        ],
    )

    apagados = storage.aparar_leads_por_tese(conn, TESE, 1)

    assert apagados == 1
    restante = storage.list_leads(conn, tese=TESE)
    assert restante[0].cnpj == "22.222.222/0001-22"


def test_aparar_leads_por_tese_never_removes_lead_with_envio():
    conn = _conn()
    lead_baixo = storage.create_lead(conn, "11.111.111/0001-11", TESE, email="x@exemplo.com")
    storage.bulk_create_leads(
        conn, TESE, [{"cnpj": "11.111.111/0001-11", "razao_social": None, "email": None, "valor_divida": 10.0}]
    )
    storage.bulk_create_leads(
        conn, TESE, [{"cnpj": "22.222.222/0001-22", "razao_social": None, "email": None, "valor_divida": 9000.0}]
    )
    storage.create_envio(conn, lead_baixo.id, TIPO_INICIAL)

    apagados = storage.aparar_leads_por_tese(conn, TESE, 0)

    assert apagados == 1  # só apaga o de maior valor, sem envio; o que já foi contatado fica
    restantes = {lead.cnpj for lead in storage.list_leads(conn, tese=TESE)}
    assert restantes == {"11.111.111/0001-11"}


def test_aparar_leads_por_tese_only_affects_given_tese():
    conn = _conn()
    storage.create_lead(conn, "11.111.111/0001-11", TESE, valor_divida=10.0)
    storage.create_lead(conn, "22.222.222/0001-22", OUTRA_TESE, valor_divida=10.0)

    storage.aparar_leads_por_tese(conn, TESE, 0)

    assert storage.list_leads(conn, tese=TESE) == []
    assert len(storage.list_leads(conn, tese=OUTRA_TESE)) == 1


def test_create_lead_stores_valor_divida():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, valor_divida=1234.56)
    assert storage.get_lead(conn, lead.id).valor_divida == 1234.56


def test_list_leads_filters_by_tese():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE)
    storage.create_lead(conn, "22.333.444/0001-55", OUTRA_TESE)

    assert len(storage.list_leads(conn)) == 2
    assert len(storage.list_leads(conn, tese=TESE)) == 1
    assert storage.list_leads(conn, tese=TESE)[0].tese == TESE


def test_leads_sem_email_only_returns_active_leads_without_email():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, email="tem@exemplo.com")
    sem_email = storage.create_lead(conn, "22.333.444/0001-55", TESE)

    resultado = storage.leads_sem_email(conn)

    assert [lead.id for lead in resultado] == [sem_email.id]


def test_leads_sem_email_filters_by_tese():
    conn = _conn()
    sem_email_a = storage.create_lead(conn, "11.222.333/0001-44", TESE)
    storage.create_lead(conn, "22.333.444/0001-55", OUTRA_TESE)

    resultado = storage.leads_sem_email(conn, tese=TESE)
    assert [lead.id for lead in resultado] == [sem_email_a.id]


def test_set_lead_email_updates_email():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE)
    storage.set_lead_email(conn, lead.id, "novo@exemplo.com")

    assert storage.get_lead(conn, lead.id).email == "novo@exemplo.com"


def test_list_teses_returns_distinct_teses_from_leads():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE)
    storage.create_lead(conn, "22.333.444/0001-55", OUTRA_TESE)
    storage.create_lead(conn, "33.444.555/0001-66", TESE)

    assert storage.list_teses(conn) == sorted([TESE, OUTRA_TESE])


def test_create_envio_generates_unique_tracking_token():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE)
    envio_a = storage.create_envio(conn, lead.id, TIPO_INICIAL)
    envio_b = storage.create_envio(conn, lead.id, "followup_1")

    assert envio_a.tracking_token != envio_b.tracking_token
    assert [e.tipo for e in storage.envios_do_lead(conn, lead.id)] == [TIPO_INICIAL, "followup_1"]


def test_get_envio_by_token_roundtrip():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE)
    envio = storage.create_envio(conn, lead.id, TIPO_INICIAL)

    assert storage.get_envio_by_token(conn, envio.tracking_token).id == envio.id
    assert storage.get_envio_by_token(conn, "token-inexistente") is None


def test_envios_de_hoje_por_tese_counts_only_matching_tese():
    conn = _conn()
    lead_a = storage.create_lead(conn, "11.222.333/0001-44", TESE)
    lead_b = storage.create_lead(conn, "22.333.444/0001-55", OUTRA_TESE)
    storage.create_envio(conn, lead_a.id, TIPO_INICIAL)
    storage.create_envio(conn, lead_b.id, TIPO_INICIAL)

    desde = "1970-01-01T00:00:00+00:00"
    assert storage.envios_de_hoje_por_tese(conn, TESE, desde) == 1
    assert storage.envios_de_hoje_por_tese(conn, OUTRA_TESE, desde) == 1
    assert storage.envios_de_hoje_por_tese(conn, "tese-sem-envios", desde) == 0


def test_add_evento_and_eventos_do_envio():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE)
    envio = storage.create_envio(conn, lead.id, TIPO_INICIAL)

    storage.add_evento(conn, envio.id, "open")
    storage.add_evento(conn, envio.id, "click", url="https://wa.me/5521986956773")

    eventos = storage.eventos_do_envio(conn, envio.id)
    assert [e.tipo for e in eventos] == ["open", "click"]
    assert eventos[1].url == "https://wa.me/5521986956773"


def test_default_templates_are_seeded_for_every_known_tese():
    conn = _conn()
    templates = storage.list_templates(conn, tese=TESE)

    assert {t.tipo for t in templates} == {"inicial", "followup_1"}
    inicial = storage.get_template(conn, TESE, TIPO_INICIAL)
    assert inicial.tag == "CONSULTA PÚBLICA, PGFN"
    assert len(inicial.checklist) == 4
    assert inicial.link_cta.startswith("https://wa.me/")


def test_list_template_teses_includes_all_seeded_teses():
    conn = _conn()
    teses = storage.list_template_teses(conn)
    assert "transportadoras_pgfn" in teses
    assert "mei_regularizacao" in teses
    assert "industria_tributaria_geral" in teses


def test_set_template_overrides_default_and_preserves_checklist():
    conn = _conn()
    storage.set_template(
        conn, TESE, TIPO_INICIAL, assunto="Novo assunto", tag="NOVA TAG", headline="Novo título",
        paragrafo1="P1", paragrafo2="P2", checklist=["A", "B"], italico="Urgente", cta_texto="CLIQUE",
        link_cta="https://wa.me/5500000000000", rodape_nota="nota",
    )

    template = storage.get_template(conn, TESE, TIPO_INICIAL)
    assert template.assunto == "Novo assunto"
    assert template.checklist == ["A", "B"]
    assert template.link_cta == "https://wa.me/5500000000000"


def test_set_template_for_new_tese_not_in_defaults():
    conn = _conn()
    storage.set_template(
        conn, "tese_nova", TIPO_INICIAL, assunto="A", tag="B", headline="C", paragrafo1="D", paragrafo2="E",
        checklist=["F"], italico="G", cta_texto="H", link_cta="I", rodape_nota="J",
    )
    assert storage.get_template(conn, "tese_nova", TIPO_INICIAL).assunto == "A"
    assert "tese_nova" in storage.list_template_teses(conn)


def test_leads_sem_telefone_excludes_lead_with_telefone():
    conn = _conn()
    sem_telefone = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")
    com_telefone = storage.create_lead(conn, "22.333.444/0001-55", TESE, razao_social="Empresa Y")
    storage.set_lead_telefone(conn, com_telefone.id, "11912345678")

    pendentes = storage.leads_sem_telefone(conn)

    assert [lead.id for lead in pendentes] == [sem_telefone.id]


def test_set_lead_telefone_updates_field():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")

    storage.set_lead_telefone(conn, lead.id, "11912345678")

    assert storage.get_lead(conn, lead.id).telefone == "11912345678"


def test_leads_pendentes_whatsapp_only_includes_leads_with_telefone_not_contatados():
    conn = _conn()
    sem_telefone = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")
    com_telefone = storage.create_lead(conn, "22.333.444/0001-55", TESE, razao_social="Empresa Y")
    ja_contatado = storage.create_lead(conn, "33.444.555/0001-66", TESE, razao_social="Empresa Z")
    storage.set_lead_telefone(conn, com_telefone.id, "11912345678")
    storage.set_lead_telefone(conn, ja_contatado.id, "11955556666")
    storage.set_lead_whatsapp_contatado(conn, ja_contatado.id)

    pendentes = storage.leads_pendentes_whatsapp(conn)

    assert [lead.id for lead in pendentes] == [com_telefone.id]


def test_set_lead_whatsapp_contatado_removes_from_pendentes():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")
    storage.set_lead_telefone(conn, lead.id, "11912345678")
    assert len(storage.leads_pendentes_whatsapp(conn)) == 1

    storage.set_lead_whatsapp_contatado(conn, lead.id)

    assert storage.leads_pendentes_whatsapp(conn) == []
    assert storage.get_lead(conn, lead.id).whatsapp_contatado_em is not None

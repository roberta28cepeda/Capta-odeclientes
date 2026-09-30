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

    assert {t.tipo for t in templates} == {"inicial", "followup_1", "followup_2", "followup_3"}
    inicial = storage.get_template(conn, TESE, TIPO_INICIAL)
    assert inicial.tag == "CONSULTA PÚBLICA, PGFN"
    assert len(inicial.checklist) == 4
    assert inicial.link_cta.startswith("https://wa.me/")


def test_list_template_teses_includes_all_seeded_teses():
    conn = _conn()
    teses = storage.list_template_teses(conn)
    assert "transportadoras_pgfn" in teses
    assert "mei_regularizacao" in teses


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

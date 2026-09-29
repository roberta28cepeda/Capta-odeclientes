from src.campaigns import storage
from src.campaigns.models import TIPO_INICIAL


def _conn():
    return storage.connect(":memory:")


def test_create_lead_and_get_by_cnpj():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", razao_social="Empresa X", email="x@exemplo.com")

    assert lead.cnpj == "11.222.333/0001-44"
    assert lead.status == "ativo"
    assert storage.get_lead_by_cnpj(conn, "11.222.333/0001-44").id == lead.id


def test_create_lead_upserts_on_conflict_keeping_existing_email():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", razao_social="Nome Antigo", email="antigo@exemplo.com")
    lead = storage.create_lead(conn, "11.222.333/0001-44", razao_social="Nome Novo", email="novo@exemplo.com")

    assert lead.razao_social == "Nome Novo"
    assert lead.email == "antigo@exemplo.com"  # não sobrescreve e-mail já preenchido


def test_leads_sem_email_only_returns_active_leads_without_email():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", email="tem@exemplo.com")
    sem_email = storage.create_lead(conn, "22.333.444/0001-55")

    resultado = storage.leads_sem_email(conn)

    assert [lead.id for lead in resultado] == [sem_email.id]


def test_set_lead_email_updates_email():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44")
    storage.set_lead_email(conn, lead.id, "novo@exemplo.com")

    assert storage.get_lead(conn, lead.id).email == "novo@exemplo.com"


def test_create_envio_generates_unique_tracking_token():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44")
    envio_a = storage.create_envio(conn, lead.id, TIPO_INICIAL)
    envio_b = storage.create_envio(conn, lead.id, "followup_1")

    assert envio_a.tracking_token != envio_b.tracking_token
    assert [e.tipo for e in storage.envios_do_lead(conn, lead.id)] == [TIPO_INICIAL, "followup_1"]


def test_get_envio_by_token_roundtrip():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44")
    envio = storage.create_envio(conn, lead.id, TIPO_INICIAL)

    assert storage.get_envio_by_token(conn, envio.tracking_token).id == envio.id
    assert storage.get_envio_by_token(conn, "token-inexistente") is None


def test_add_evento_and_eventos_do_envio():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44")
    envio = storage.create_envio(conn, lead.id, TIPO_INICIAL)

    storage.add_evento(conn, envio.id, "open")
    storage.add_evento(conn, envio.id, "click", url="https://leactis.com.br")

    eventos = storage.eventos_do_envio(conn, envio.id)
    assert [e.tipo for e in eventos] == ["open", "click"]
    assert eventos[1].url == "https://leactis.com.br"


def test_default_templates_are_seeded():
    conn = _conn()
    templates = storage.list_templates(conn)

    assert {t.tipo for t in templates} == {"inicial", "followup_1", "followup_2", "followup_3"}
    assert all(t.link_cta for t in templates)


def test_set_template_overrides_default():
    conn = _conn()
    storage.set_template(conn, TIPO_INICIAL, "Novo assunto", "Novo corpo", link_cta="https://exemplo.com")

    template = storage.get_template(conn, TIPO_INICIAL)
    assert template.assunto == "Novo assunto"
    assert template.corpo == "Novo corpo"
    assert template.link_cta == "https://exemplo.com"

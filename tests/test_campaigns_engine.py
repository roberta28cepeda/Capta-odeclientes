from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from src.campaigns import storage
from src.campaigns import engine
from src.campaigns.email_finder import EmailFinderError
from src.campaigns.models import TIPO_INICIAL, LIMITE_ENVIOS_POR_TESE_POR_DIA

TESE = "transportadoras_pgfn"
OUTRA_TESE = "contadores_certificado"


def _conn():
    return storage.connect(":memory:")


def _envelhecer_envio(conn, envio, dias):
    old_date = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    conn.execute("UPDATE campanha_envios SET enviado_em = ? WHERE id = ?", (old_date, envio.id))
    conn.commit()


def test_leads_para_enviar_hoje_includes_new_lead_with_email():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com")

    resultado = engine.leads_para_enviar_hoje(conn)

    assert len(resultado) == 1
    assert resultado[0][1] == TIPO_INICIAL


def test_leads_para_enviar_hoje_excludes_lead_without_email():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")

    assert engine.leads_para_enviar_hoje(conn) == []


def test_leads_para_enviar_hoje_excludes_lead_sent_recently():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    storage.create_envio(conn, lead.id, TIPO_INICIAL)

    assert engine.leads_para_enviar_hoje(conn) == []


def test_leads_para_enviar_hoje_includes_followup_after_3_days():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    envio = storage.create_envio(conn, lead.id, TIPO_INICIAL)
    _envelhecer_envio(conn, envio, 4)

    resultado = engine.leads_para_enviar_hoje(conn)
    assert resultado == [(lead, "followup_1")]


def test_leads_para_enviar_hoje_excludes_lead_after_last_followup():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    for tipo in [TIPO_INICIAL, "followup_1", "followup_2", "followup_3"]:
        envio = storage.create_envio(conn, lead.id, tipo)
        _envelhecer_envio(conn, envio, 10)

    assert engine.leads_para_enviar_hoje(conn) == []


def test_leads_para_enviar_hoje_applies_daily_limit_per_tese():
    conn = _conn()
    for i in range(LIMITE_ENVIOS_POR_TESE_POR_DIA + 5):
        storage.create_lead(conn, f"11.222.{i:03d}/0001-44", TESE, email=f"x{i}@exemplo.com")

    resultado = engine.leads_para_enviar_hoje(conn)
    assert len(resultado) == LIMITE_ENVIOS_POR_TESE_POR_DIA


def test_leads_para_enviar_hoje_limit_is_independent_per_tese():
    conn = _conn()
    for i in range(LIMITE_ENVIOS_POR_TESE_POR_DIA + 2):
        storage.create_lead(conn, f"11.222.{i:03d}/0001-44", TESE, email=f"x{i}@exemplo.com")
    for i in range(3):
        storage.create_lead(conn, f"22.333.{i:03d}/0001-55", OUTRA_TESE, email=f"y{i}@exemplo.com")

    resultado = engine.leads_para_enviar_hoje(conn)
    teses = [lead.tese for lead, _ in resultado]
    assert teses.count(TESE) == LIMITE_ENVIOS_POR_TESE_POR_DIA
    assert teses.count(OUTRA_TESE) == 3


def test_leads_para_enviar_hoje_counts_already_sent_today_against_limit():
    conn = _conn()
    for i in range(LIMITE_ENVIOS_POR_TESE_POR_DIA - 1):
        lead = storage.create_lead(conn, f"11.222.{i:03d}/0001-44", TESE, email=f"x{i}@exemplo.com")
        storage.create_envio(conn, lead.id, TIPO_INICIAL)  # já enviado hoje, conta pro limite

    novo_lead_a = storage.create_lead(conn, "99.999.000/0001-11", TESE, email="a@exemplo.com")
    novo_lead_b = storage.create_lead(conn, "99.999.001/0001-22", TESE, email="b@exemplo.com")

    resultado = engine.leads_para_enviar_hoje(conn)
    # só sobra 1 vaga (9 já enviados hoje, limite 10)
    assert len(resultado) == 1
    assert resultado[0][0].id == novo_lead_a.id


def test_enviar_para_lead_creates_envio_and_sends_html_email():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com", valor_divida=1234.5)

    with patch("src.campaigns.engine.send_email_html") as mock_send:
        engine.enviar_para_lead(conn, lead, TIPO_INICIAL, "https://exemplo.com", "smtp.host", 587, "user", "pass")

    assert len(storage.envios_do_lead(conn, lead.id)) == 1
    mock_send.assert_called_once()
    to, subject, plain_body, html_body = mock_send.call_args[0][:4]
    assert to == "x@exemplo.com"
    assert "Empresa X" in subject
    assert "Empresa X" in plain_body
    assert "1.234,50" in html_body
    assert "<img" in html_body
    assert "wa.me" in html_body


def test_enviar_para_lead_uses_tese_specific_template():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", OUTRA_TESE, razao_social="Escritório Y", email="y@exemplo.com")

    with patch("src.campaigns.engine.send_email_html") as mock_send:
        engine.enviar_para_lead(conn, lead, TIPO_INICIAL, "https://exemplo.com", "smtp.host", 587, "user", "pass")

    _, subject, _, html_body = mock_send.call_args[0][:4]
    assert "dinheiro na mesa" in html_body
    assert "certificado" in subject.lower()


def test_rodar_diario_sends_to_all_pending_leads_and_tracks_errors():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com")
    storage.create_lead(conn, "22.333.444/0001-55", TESE, razao_social="Empresa Y", email="y@exemplo.com")

    with patch("src.campaigns.engine.send_email_html", side_effect=[None, RuntimeError("smtp caiu")]):
        resultado = engine.rodar_diario(conn, "https://exemplo.com", "smtp.host", 587, "user", "pass")

    assert resultado["leads_verificados"] == 2
    assert resultado["enviados"] == 1
    assert len(resultado["erros"]) == 1


def test_buscar_emails_pendentes_sets_email_for_leads_without_one():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")
    storage.create_lead(conn, "22.333.444/0001-55", TESE, razao_social="Empresa Y", email="ja-tem@exemplo.com")

    with patch("src.campaigns.engine.buscar_email_por_empresa", return_value="achado@empresax.com.br") as mock_busca:
        resultado = engine.buscar_emails_pendentes(conn, "API_KEY")

    mock_busca.assert_called_once_with("Empresa X", "API_KEY")
    assert resultado == {"leads_verificados": 1, "encontrados": 1, "erros": []}
    assert storage.get_lead(conn, lead.id).email == "achado@empresax.com.br"


def test_buscar_emails_pendentes_records_error_without_stopping_others():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")
    storage.create_lead(conn, "22.333.444/0001-55", TESE, razao_social="Empresa Y")

    with patch(
        "src.campaigns.engine.buscar_email_por_empresa",
        side_effect=[EmailFinderError("cota esgotada"), "achado@empresay.com.br"],
    ):
        resultado = engine.buscar_emails_pendentes(conn, "API_KEY")

    assert resultado["leads_verificados"] == 2
    assert resultado["encontrados"] == 1
    assert len(resultado["erros"]) == 1


def test_buscar_emails_pendentes_handles_no_email_found():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")

    with patch("src.campaigns.engine.buscar_email_por_empresa", return_value=None):
        resultado = engine.buscar_emails_pendentes(conn, "API_KEY")

    assert resultado == {"leads_verificados": 1, "encontrados": 0, "erros": []}


def test_gerar_relatorio_semanal_reports_sends_and_events_by_tese():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    envio = storage.create_envio(conn, lead.id, TIPO_INICIAL)
    storage.add_evento(conn, envio.id, "open")
    storage.add_evento(conn, envio.id, "click")

    relatorio = engine.gerar_relatorio_semanal(conn, date.today() - timedelta(days=7), date.today())

    assert "E-mails enviados: 1" in relatorio
    assert "Aberturas (únicas por envio): 1" in relatorio
    assert "Cliques (únicos por envio): 1" in relatorio
    assert TESE in relatorio


def test_gerar_relatorio_semanal_handles_no_sends():
    conn = _conn()
    relatorio = engine.gerar_relatorio_semanal(conn, date.today() - timedelta(days=7), date.today())
    assert "Nenhum envio" in relatorio


def test_enviar_relatorio_semanal_sends_email_with_report_body():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    storage.create_envio(conn, lead.id, TIPO_INICIAL)

    with patch("src.campaigns.engine.send_email") as mock_send:
        engine.enviar_relatorio_semanal(conn, "admin@exemplo.com", "smtp.host", 587, "user", "pass")

    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == "admin@exemplo.com"

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from src.campaigns import engine, storage
from src.campaigns.email_finder import EmailFinderError
from src.campaigns.models import TIPO_INICIAL


def _conn():
    return storage.connect(":memory:")


def test_leads_para_enviar_hoje_includes_new_lead_with_email():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", razao_social="Empresa X", email="x@exemplo.com")

    resultado = engine.leads_para_enviar_hoje(conn)

    assert len(resultado) == 1
    assert resultado[0][1] == TIPO_INICIAL


def test_leads_para_enviar_hoje_excludes_lead_without_email():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", razao_social="Empresa X")

    assert engine.leads_para_enviar_hoje(conn) == []


def test_leads_para_enviar_hoje_excludes_lead_sent_recently():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", email="x@exemplo.com")
    storage.create_envio(conn, lead.id, TIPO_INICIAL)

    assert engine.leads_para_enviar_hoje(conn) == []


def test_leads_para_enviar_hoje_includes_followup_after_3_days():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", email="x@exemplo.com")
    envio = storage.create_envio(conn, lead.id, TIPO_INICIAL)

    # simula que o envio inicial aconteceu há 4 dias
    old_date = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    conn.execute("UPDATE campanha_envios SET enviado_em = ? WHERE id = ?", (old_date, envio.id))
    conn.commit()

    resultado = engine.leads_para_enviar_hoje(conn)
    assert resultado == [(lead, "followup_1")]


def test_leads_para_enviar_hoje_excludes_lead_after_last_followup():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", email="x@exemplo.com")
    old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    for tipo in [TIPO_INICIAL, "followup_1", "followup_2", "followup_3"]:
        envio = storage.create_envio(conn, lead.id, tipo)
        conn.execute("UPDATE campanha_envios SET enviado_em = ? WHERE id = ?", (old_date, envio.id))
    conn.commit()

    assert engine.leads_para_enviar_hoje(conn) == []


def test_enviar_para_lead_creates_envio_and_sends_html_email():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", razao_social="Empresa X", email="x@exemplo.com")

    with patch("src.campaigns.engine.send_email_html") as mock_send:
        engine.enviar_para_lead(conn, lead, TIPO_INICIAL, "https://exemplo.com", "smtp.host", 587, "user", "pass")

    assert len(storage.envios_do_lead(conn, lead.id)) == 1
    mock_send.assert_called_once()
    to, subject, plain_body, html_body = mock_send.call_args[0][:4]
    assert to == "x@exemplo.com"
    assert "Empresa X" in subject
    assert "Empresa X" in plain_body
    assert "<img" in html_body


def test_rodar_diario_sends_to_all_pending_leads_and_tracks_errors():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", razao_social="Empresa X", email="x@exemplo.com")
    storage.create_lead(conn, "22.333.444/0001-55", razao_social="Empresa Y", email="y@exemplo.com")

    with patch("src.campaigns.engine.send_email_html", side_effect=[None, RuntimeError("smtp caiu")]):
        resultado = engine.rodar_diario(conn, "https://exemplo.com", "smtp.host", 587, "user", "pass")

    assert resultado["leads_verificados"] == 2
    assert resultado["enviados"] == 1
    assert len(resultado["erros"]) == 1


def test_gerar_relatorio_semanal_reports_sends_and_events():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", email="x@exemplo.com")
    envio = storage.create_envio(conn, lead.id, TIPO_INICIAL)
    storage.add_evento(conn, envio.id, "open")
    storage.add_evento(conn, envio.id, "click")

    relatorio = engine.gerar_relatorio_semanal(conn, date.today() - timedelta(days=7), date.today())

    assert "E-mails enviados: 1" in relatorio
    assert "Aberturas (únicas por envio): 1" in relatorio
    assert "Cliques (únicos por envio): 1" in relatorio


def test_gerar_relatorio_semanal_handles_no_sends():
    conn = _conn()
    relatorio = engine.gerar_relatorio_semanal(conn, date.today() - timedelta(days=7), date.today())
    assert "Nenhum envio" in relatorio


def test_enviar_relatorio_semanal_sends_email_with_report_body():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", email="x@exemplo.com")
    storage.create_envio(conn, lead.id, TIPO_INICIAL)

    with patch("src.campaigns.engine.send_email") as mock_send:
        engine.enviar_relatorio_semanal(conn, "admin@exemplo.com", "smtp.host", 587, "user", "pass")

    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == "admin@exemplo.com"


def test_buscar_emails_pendentes_sets_email_for_leads_without_one():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", razao_social="Empresa X")
    storage.create_lead(conn, "22.333.444/0001-55", razao_social="Empresa Y", email="ja-tem@exemplo.com")

    with patch("src.campaigns.engine.buscar_email_por_empresa", return_value="achado@empresax.com.br") as mock_busca:
        resultado = engine.buscar_emails_pendentes(conn, "API_KEY")

    mock_busca.assert_called_once_with("Empresa X", "API_KEY")
    assert resultado == {"leads_verificados": 1, "encontrados": 1, "erros": []}
    assert storage.get_lead(conn, lead.id).email == "achado@empresax.com.br"


def test_buscar_emails_pendentes_records_error_without_stopping_others():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", razao_social="Empresa X")
    storage.create_lead(conn, "22.333.444/0001-55", razao_social="Empresa Y")

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
    storage.create_lead(conn, "11.222.333/0001-44", razao_social="Empresa X")

    with patch("src.campaigns.engine.buscar_email_por_empresa", return_value=None):
        resultado = engine.buscar_emails_pendentes(conn, "API_KEY")

    assert resultado == {"leads_verificados": 1, "encontrados": 0, "erros": []}

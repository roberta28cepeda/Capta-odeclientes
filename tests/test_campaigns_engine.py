from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.campaigns import storage
from src.campaigns import engine
from src.campaigns.email_finder import EmailFinderError
from src.campaigns.models import Lead, TIPO_INICIAL, LIMITE_ENVIOS_POR_TESE_POR_DIA
from src.campaigns.phone_finder import PhoneFinderError

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


def test_leads_pendentes_por_tese_nao_faz_uma_consulta_por_lead():
    """Regressão: antes, leads_pendentes_por_tese chamava envios_do_lead
    (uma consulta ao banco) pra cada lead ativo, sem nenhum limite de
    tempo — com a carteira na casa dos milhares isso periodicamente
    estourava o timeout de 300s do Vercel em produção. A versão corrigida
    busca o histórico de todos os leads numa única chamada
    (envios_por_lead_ids).
    """
    conn = _conn()
    for i in range(5):
        storage.create_lead(conn, f"11.222.333/000{i}-44", TESE, razao_social=f"Empresa {i}", email=f"x{i}@exemplo.com")

    with patch("src.campaigns.storage.envios_do_lead") as mock_envios_do_lead:
        resultado = engine.leads_pendentes_por_tese(conn)

    mock_envios_do_lead.assert_not_called()
    assert len(resultado[TESE]) == 5


def test_leads_pendentes_por_tese_respeita_followup_pendente_de_cada_lead():
    conn = _conn()
    lead_novo = storage.create_lead(conn, "11.111.111/0001-11", TESE, razao_social="Novo", email="novo@exemplo.com")
    lead_recente = storage.create_lead(conn, "22.222.222/0001-22", TESE, razao_social="Recente", email="recente@exemplo.com")
    storage.create_envio(conn, lead_recente.id, TIPO_INICIAL)  # enviado agora — não é due pra followup ainda
    lead_due = storage.create_lead(conn, "33.333.333/0001-33", TESE, razao_social="Due", email="due@exemplo.com")
    envio_antigo = storage.create_envio(conn, lead_due.id, TIPO_INICIAL)
    _envelhecer_envio(conn, envio_antigo, dias=10)

    resultado = engine.leads_pendentes_por_tese(conn)

    pendentes_por_id = {lead.id: tipo for lead, tipo in resultado[TESE]}
    assert pendentes_por_id[lead_novo.id] == TIPO_INICIAL
    assert lead_recente.id not in pendentes_por_id
    assert lead_due.id in pendentes_por_id


def test_leads_para_enviar_hoje_excludes_lead_without_email():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")

    assert engine.leads_para_enviar_hoje(conn) == []


def test_leads_para_enviar_hoje_excludes_lead_sent_recently():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    storage.create_envio(conn, lead.id, TIPO_INICIAL)

    assert engine.leads_para_enviar_hoje(conn) == []


def test_leads_para_enviar_hoje_excludes_followup_before_5_days():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    envio = storage.create_envio(conn, lead.id, TIPO_INICIAL)
    _envelhecer_envio(conn, envio, 4)

    assert engine.leads_para_enviar_hoje(conn) == []


def test_leads_para_enviar_hoje_includes_followup_after_5_days():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    envio = storage.create_envio(conn, lead.id, TIPO_INICIAL)
    _envelhecer_envio(conn, envio, 5)

    resultado = engine.leads_para_enviar_hoje(conn)
    assert resultado == [(lead, "followup_1")]


def test_leads_para_enviar_hoje_excludes_lead_after_last_followup():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    for tipo in [TIPO_INICIAL, "followup_1"]:
        envio = storage.create_envio(conn, lead.id, tipo)
        _envelhecer_envio(conn, envio, 10)

    assert engine.leads_para_enviar_hoje(conn) == []


def test_leads_para_enviar_hoje_ignores_envio_de_tipo_obsoleto():
    """Lead que já recebeu followup_2/followup_3 numa versão antiga da
    cadência (3 follow-ups) não deve gerar erro nem receber mais nada.
    """
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, email="x@exemplo.com")
    envio = storage.create_envio(conn, lead.id, "followup_2")
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


def test_enviar_para_lead_nao_registra_envio_quando_smtp_falha():
    """Regressão: o envio era registrado no banco ANTES do SMTP confirmar o
    envio, então uma falha de SMTP ainda marcava o lead como "contatado
    hoje" e consumia a cota diária por tese sem nenhum e-mail sair de
    verdade — exatamente o que aconteceu em produção (ja_enviados_hoje=10,
    cota cheia, mas nenhum e-mail chegou de fato).
    """
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com")

    with patch("src.campaigns.engine.send_email_html", side_effect=RuntimeError("smtp caiu")):
        with pytest.raises(RuntimeError):
            engine.enviar_para_lead(conn, lead, TIPO_INICIAL, "https://exemplo.com", "smtp.host", 587, "user", "pass")

    assert storage.envios_do_lead(conn, lead.id) == []


def test_rodar_diario_sends_to_all_pending_leads_and_tracks_errors():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com")
    storage.create_lead(conn, "22.333.444/0001-55", TESE, razao_social="Empresa Y", email="y@exemplo.com")

    with patch("src.campaigns.engine.send_email_html", side_effect=[None, RuntimeError("smtp caiu")]):
        resultado = engine.rodar_diario(conn, "https://exemplo.com", "smtp.host", 587, "user", "pass")

    assert resultado["leads_verificados"] == 2
    assert resultado["enviados"] == 1
    assert len(resultado["erros"]) == 1


def test_rodar_diario_stops_when_orcamento_de_tempo_estoura():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com")
    storage.create_lead(conn, "22.333.444/0001-55", TESE, razao_social="Empresa Y", email="y@exemplo.com")

    with patch("src.campaigns.engine.send_email_html") as mock_send, patch(
        "src.campaigns.engine.monotonic", side_effect=[0.0, 0.0, 999.0]
    ):
        resultado = engine.rodar_diario(conn, "https://exemplo.com", "smtp.host", 587, "user", "pass", orcamento_segundos=10)

    mock_send.assert_called_once()
    assert resultado["enviados"] == 1
    assert resultado["leads_verificados"] == 2  # tamanho total da fila, não quantos foram tentados


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


def test_buscar_emails_pendentes_respects_limite_por_execucao():
    conn = _conn()
    for i in range(5):
        storage.create_lead(conn, f"{i:02d}.222.333/0001-44", TESE, razao_social=f"Empresa {i}")

    with patch("src.campaigns.engine.buscar_email_por_empresa", return_value="achado@empresa.com.br") as mock_busca:
        resultado = engine.buscar_emails_pendentes(conn, "API_KEY", limite=2)

    assert mock_busca.call_count == 2
    assert resultado["leads_verificados"] == 2
    assert resultado["encontrados"] == 2


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


def test_enviar_para_lead_followup_rascunho_nao_envia_nem_registra_envio():
    """Regressão: follow-up com [AJUSTAR]/[RASCUNHO] chegou em lead real."""
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com")
    storage.create_envio(conn, lead.id, TIPO_INICIAL)

    with patch("src.campaigns.engine.send_email") as mock_send:
        with pytest.raises(engine.TemplateRascunhoError):
            engine.enviar_para_lead(conn, lead, "followup_1", "https://exemplo.com", "smtp.host", 587, "user", "pass")

    mock_send.assert_not_called()
    assert [e.tipo for e in storage.envios_do_lead(conn, lead.id)] == [TIPO_INICIAL]


@pytest.mark.parametrize("tese", ["industria_tributaria_geral", "contadores_certificado"])
def test_followups_das_teses_ativas_nao_sao_rascunho(tese):
    conn = _conn()
    template = storage.get_template(conn, tese, "followup_1")
    assert not engine.template_eh_rascunho(template)


def test_enviar_para_lead_followup_uses_plain_text_not_html():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", OUTRA_TESE, razao_social="Empresa X", email="x@exemplo.com")
    storage.create_envio(conn, lead.id, TIPO_INICIAL)

    with patch("src.campaigns.engine.send_email") as mock_send, patch(
        "src.campaigns.engine.send_email_html"
    ) as mock_send_html:
        engine.enviar_para_lead(conn, lead, "followup_1", "https://exemplo.com", "smtp.host", 587, "user", "pass")

    mock_send.assert_called_once()
    mock_send_html.assert_not_called()
    to, subject, corpo = mock_send.call_args[0][:3]
    assert to == "x@exemplo.com"
    assert "[AJUSTAR" not in subject + corpo and "[RASCUNHO" not in subject + corpo
    assert "<" not in corpo  # texto puro, sem tag HTML nenhuma


def test_rodar_diario_returns_leads_enviados_for_whatsapp_digest():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X", email="x@exemplo.com")

    with patch("src.campaigns.engine.send_email_html"):
        resultado = engine.rodar_diario(conn, "https://exemplo.com", "smtp.host", 587, "user", "pass")

    assert len(resultado["leads_enviados"]) == 1
    assert resultado["leads_enviados"][0].cnpj == "11.222.333/0001-44"


def test_buscar_telefones_pendentes_sets_telefone_for_leads_without_one():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")
    storage.create_lead(conn, "22.333.444/0001-55", TESE, razao_social="Empresa Y", email="ja@exemplo.com")
    storage.set_lead_telefone(conn, storage.get_lead(conn, 2).id, "1122223333")

    with patch("src.campaigns.engine.buscar_telefone_por_cnpj", return_value="1155554444") as mock_busca:
        resultado = engine.buscar_telefones_pendentes(conn)

    mock_busca.assert_called_once_with("11.222.333/0001-44")
    assert resultado == {"leads_verificados": 1, "encontrados": 1, "erros": []}
    assert storage.get_lead(conn, lead.id).telefone == "1155554444"


def test_buscar_telefones_pendentes_stops_on_rate_limit_error():
    conn = _conn()
    storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")
    storage.create_lead(conn, "22.333.444/0001-55", TESE, razao_social="Empresa Y")

    with patch(
        "src.campaigns.engine.buscar_telefone_por_cnpj",
        side_effect=PhoneFinderError("limite de consultas por minuto atingido"),
    ) as mock_busca:
        resultado = engine.buscar_telefones_pendentes(conn)

    mock_busca.assert_called_once()  # parou no primeiro erro, não tentou o segundo lead
    assert resultado["leads_verificados"] == 0
    assert len(resultado["erros"]) == 1


def test_buscar_telefones_pendentes_respects_limite_por_execucao():
    conn = _conn()
    for i in range(5):
        storage.create_lead(conn, f"{i:02d}.222.333/0001-44", TESE, razao_social=f"Empresa {i}")

    with patch("src.campaigns.engine.buscar_telefone_por_cnpj", return_value="1155554444") as mock_busca:
        resultado = engine.buscar_telefones_pendentes(conn, limite=2)

    assert mock_busca.call_count == 2
    assert resultado["leads_verificados"] == 2
    assert resultado["encontrados"] == 2


def test_buscar_telefones_pendentes_usa_cnpja_quando_token_configurado():
    conn = _conn()
    lead = storage.create_lead(conn, "11.222.333/0001-44", TESE, razao_social="Empresa X")

    with patch("src.campaigns.engine.buscar_telefone_cnpja", return_value="(11) 95555-4444") as mock_cnpja, patch(
        "src.campaigns.engine.buscar_telefone_por_cnpj"
    ) as mock_receitaws:
        resultado = engine.buscar_telefones_pendentes(conn, cnpja_token="token-fake")

    mock_cnpja.assert_called_once_with("11.222.333/0001-44", "token-fake")
    mock_receitaws.assert_not_called()
    assert resultado == {"leads_verificados": 1, "encontrados": 1, "erros": []}
    assert storage.get_lead(conn, lead.id).telefone == "(11) 95555-4444"


def test_buscar_telefones_pendentes_stops_when_orcamento_de_tempo_estoura():
    conn = _conn()
    for i in range(5):
        storage.create_lead(conn, f"{i:02d}.222.333/0001-44", TESE, razao_social=f"Empresa {i}")

    # monotonic() é chamado uma vez antes do loop (início) e uma vez por
    # iteração — devolve um valor já além do orçamento na 2ª checagem, então
    # só o primeiro lead é processado antes de parar.
    with patch("src.campaigns.engine.buscar_telefone_por_cnpj", return_value="1155554444") as mock_busca, patch(
        "src.campaigns.engine.monotonic", side_effect=[0.0, 0.0, 999.0]
    ):
        resultado = engine.buscar_telefones_pendentes(conn, orcamento_segundos=10)

    assert mock_busca.call_count == 1
    assert resultado["leads_verificados"] == 1


def test_buscar_emails_pendentes_stops_when_orcamento_de_tempo_estoura():
    conn = _conn()
    for i in range(5):
        storage.create_lead(conn, f"{i:02d}.222.333/0001-44", TESE, razao_social=f"Empresa {i}")

    with patch(
        "src.campaigns.engine.buscar_email_por_empresa", return_value="achado@empresa.com.br"
    ) as mock_busca, patch("src.campaigns.engine.monotonic", side_effect=[0.0, 0.0, 999.0]):
        resultado = engine.buscar_emails_pendentes(conn, "API_KEY", orcamento_segundos=10)

    assert mock_busca.call_count == 1
    assert resultado["leads_verificados"] == 1


def test_montar_link_whatsapp_normalizes_numero_and_includes_mensagem():
    lead = Lead(
        id=1, cnpj="11.222.333/0001-44", tese=TESE, razao_social="Empresa X", email=None, status="ativo",
        criado_em="", valor_divida=1500.0, telefone="(11) 91234-5678",
    )

    link = engine.montar_link_whatsapp(lead)

    assert link.startswith("https://wa.me/5511912345678?text=")
    assert "Empresa" in link


def test_montar_link_whatsapp_returns_none_without_telefone():
    lead = Lead(
        id=1, cnpj="11.222.333/0001-44", tese=TESE, razao_social="Empresa X", email=None, status="ativo",
        criado_em="", telefone=None,
    )
    assert engine.montar_link_whatsapp(lead) is None


def test_montar_link_whatsapp_uses_dedicated_message_for_contadores_certificado():
    lead = Lead(
        id=1, cnpj="11.222.333/0001-44", tese="contadores_certificado", razao_social="Escritório Y", email=None,
        status="ativo", criado_em="", telefone="11912345678",
    )

    link = engine.montar_link_whatsapp(lead)

    assert "certificado" in link.lower() or "Fenacon" in link


def test_montar_link_whatsapp_uses_dedicated_message_for_simples_ibs_cbs():
    lead = Lead(
        id=1, cnpj="11.222.333/0001-44", tese="simples_ibs_cbs", razao_social="Empresa X", email=None,
        status="ativo", criado_em="", telefone="11912345678",
    )

    link = engine.montar_link_whatsapp(lead)

    assert "Simples" in link
    assert "Empresa" in link


def test_montar_link_whatsapp_falls_back_to_divida_message_for_unmapped_tese():
    lead = Lead(
        id=1, cnpj="11.222.333/0001-44", tese="contadores_tributaria", razao_social="Empresa X", email=None,
        status="ativo", criado_em="", valor_divida=500.0, telefone="11912345678",
    )

    link = engine.montar_link_whatsapp(lead)

    assert "pend" in link.lower()  # mensagem padrão de dívida


def test_montar_link_whatsapp_uses_dedicated_message_for_mei_regularizacao():
    lead = Lead(
        id=1, cnpj="11.222.333/0001-44", tese="mei_regularizacao", razao_social="Empresa X", email=None,
        status="ativo", criado_em="", telefone="11912345678",
    )

    link = engine.montar_link_whatsapp(lead)

    assert "MEI" in link or "CNPJ cancelado" in link


def test_montar_link_whatsapp_uses_dedicated_message_for_industria_tributaria_geral():
    lead = Lead(
        id=1, cnpj="11.222.333/0001-44", tese="industria_tributaria_geral", razao_social="Empresa X", email=None,
        status="ativo", criado_em="", valor_divida=1000.0, telefone="11912345678",
    )

    link = engine.montar_link_whatsapp(lead)

    assert "transa" in link.lower() or "tributária" in link.lower()


def test_montar_resumo_whatsapp_lists_leads_with_links():
    lead = Lead(
        id=1, cnpj="11.222.333/0001-44", tese=TESE, razao_social="Empresa X", email=None, status="ativo",
        criado_em="", telefone="11912345678",
    )

    resumo = engine.montar_resumo_whatsapp([lead], "https://exemplo.com")

    assert "Empresa X" in resumo
    assert "wa.me" in resumo
    assert "https://exemplo.com/admin/campanhas/whatsapp" in resumo


def test_montar_resumo_whatsapp_handles_no_leads():
    resumo = engine.montar_resumo_whatsapp([], "https://exemplo.com")
    assert "Nenhum lead" in resumo


def test_enviar_resumo_whatsapp_equipe_sends_email():
    conn = _conn()
    lead = Lead(
        id=1, cnpj="11.222.333/0001-44", tese=TESE, razao_social="Empresa X", email=None, status="ativo",
        criado_em="", telefone="11912345678",
    )

    with patch("src.campaigns.engine.send_email") as mock_send:
        engine.enviar_resumo_whatsapp_equipe(conn, [lead], "equipe@exemplo.com", "https://exemplo.com", "smtp.host", 587, "user", "pass")

    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == "equipe@exemplo.com"

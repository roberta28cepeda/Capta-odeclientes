"""Motor da campanha: decide quem recebe e-mail hoje (inicial ou próximo
follow-up) respeitando o limite diário por tese, monta e envia a mensagem
com rastreio (HTML no design da Leactis, CTA pro WhatsApp), e monta o
relatório semanal de abertura/clique.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from src.campaigns import html_shell, storage, tracking
from src.campaigns.email_finder import EmailFinderError, buscar_email_por_empresa
from src.campaigns.models import (
    DIAS_ENTRE_FOLLOWUPS,
    Envio,
    Lead,
    LIMITE_ENVIOS_POR_TESE_POR_DIA,
    STATUS_ATIVO,
    TIPO_INICIAL,
    TIPOS_ENVIO,
)
from src.fiscal_monitor.email_client import send_email, send_email_html

_TAG_HTML_RE = re.compile(r"<[^>]+>")


def _proximo_tipo_envio(envios: list[Envio]) -> str | None:
    """Dado o histórico de envios de um lead, retorna o próximo tipo a
    mandar, ou None se já mandou tudo (inicial + todos os follow-ups) ou se
    ainda não passou tempo suficiente desde o último envio.
    """
    if not envios:
        return TIPO_INICIAL
    ultimo = envios[-1]
    indice_atual = TIPOS_ENVIO.index(ultimo.tipo)
    if indice_atual + 1 >= len(TIPOS_ENVIO):
        return None  # já mandou o último follow-up
    enviado_em = datetime.fromisoformat(ultimo.enviado_em)
    if datetime.now(timezone.utc) - enviado_em < timedelta(days=DIAS_ENTRE_FOLLOWUPS):
        return None  # ainda não passou tempo suficiente desde o último envio
    return TIPOS_ENVIO[indice_atual + 1]


def _inicio_do_dia_utc(hoje: date | None = None) -> str:
    hoje = hoje or date.today()
    return datetime.combine(hoje, time.min, tzinfo=timezone.utc).isoformat()


def leads_pendentes_por_tese(conn) -> dict[str, list[tuple[Lead, str]]]:
    """Agrupa por tese os leads ativos com e-mail que precisam de algum
    contato hoje (inicial ou próximo follow-up), sem aplicar limite ainda.
    """
    resultado: dict[str, list[tuple[Lead, str]]] = {}
    for lead in storage.list_leads(conn):
        if lead.status != STATUS_ATIVO or not lead.email:
            continue
        tipo = _proximo_tipo_envio(storage.envios_do_lead(conn, lead.id))
        if tipo:
            resultado.setdefault(lead.tese, []).append((lead, tipo))
    return resultado


def leads_para_enviar_hoje(conn, hoje: date | None = None) -> list[tuple[Lead, str]]:
    """Aplica o limite diário por tese (inicial + follow-up somados) sobre
    os leads pendentes — cada tese só manda até `LIMITE_ENVIOS_POR_TESE_POR_DIA`
    e-mails por dia, contando o que já foi enviado hoje pra essa tese.
    """
    desde_iso = _inicio_do_dia_utc(hoje)
    resultado: list[tuple[Lead, str]] = []
    for tese, pendentes in leads_pendentes_por_tese(conn).items():
        ja_enviados_hoje = storage.envios_de_hoje_por_tese(conn, tese, desde_iso)
        vagas = max(0, LIMITE_ENVIOS_POR_TESE_POR_DIA - ja_enviados_hoje)
        resultado.extend(pendentes[:vagas])
    return resultado


def _substituir_placeholders(texto: str, contexto: dict[str, str]) -> str:
    for chave, valor in contexto.items():
        texto = texto.replace("{{" + chave + "}}", valor)
    return texto


def _formatar_valor_brl(valor: float | None) -> str:
    if valor is None:
        return ""
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _remover_tags_html(texto: str) -> str:
    return _TAG_HTML_RE.sub("", texto)


def enviar_para_lead(
    conn,
    lead: Lead,
    tipo: str,
    base_url: str,
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    smtp_from: str | None = None,
) -> None:
    template = storage.get_template(conn, lead.tese, tipo)
    if template is None:
        raise RuntimeError(f"Template '{tipo}' da tese '{lead.tese}' não encontrado.")

    envio = storage.create_envio(conn, lead.id, tipo)

    contexto = {
        "RAZAO_SOCIAL": lead.razao_social or lead.cnpj,
        "CNPJ": lead.cnpj,
        "VALOR_DIVIDA": _formatar_valor_brl(lead.valor_divida),
    }
    assunto = _substituir_placeholders(template.assunto, contexto)
    headline = _substituir_placeholders(template.headline, contexto)
    paragrafo1 = _substituir_placeholders(template.paragrafo1, contexto)
    paragrafo2 = _substituir_placeholders(template.paragrafo2, contexto)
    italico = _substituir_placeholders(template.italico, contexto)

    cta_url = tracking.click_url(base_url, envio.tracking_token, template.link_cta)
    pixel = tracking.pixel_img_tag(base_url, envio.tracking_token)

    corpo_html = html_shell.render_email_html(
        tag=template.tag, headline=headline, paragrafo1=paragrafo1, paragrafo2=paragrafo2,
        checklist=template.checklist, italico=italico, cta_texto=template.cta_texto, cta_url=cta_url,
        rodape_nota=template.rodape_nota, pixel_html=pixel,
    )
    corpo_texto = (
        f"{_remover_tags_html(paragrafo1)}\n\n{_remover_tags_html(paragrafo2)}\n\n"
        f"{template.cta_texto}: {cta_url}"
    )

    send_email_html(
        lead.email, assunto, corpo_texto, corpo_html, smtp_host, smtp_port, smtp_username, smtp_password,
        smtp_from=smtp_from,
    )


def rodar_diario(
    conn, base_url: str, smtp_host: str, smtp_port: int, smtp_username: str, smtp_password: str,
    smtp_from: str | None = None,
) -> dict:
    """Roda o envio do dia pra todos os leads que precisam de contato,
    respeitando o limite diário por tese — erro num lead não trava os
    demais, fica registrado no resultado.
    """
    leads_e_tipos = leads_para_enviar_hoje(conn)
    enviados = 0
    erros = []
    for lead, tipo in leads_e_tipos:
        try:
            enviar_para_lead(conn, lead, tipo, base_url, smtp_host, smtp_port, smtp_username, smtp_password, smtp_from=smtp_from)
            enviados += 1
        except Exception as exc:
            erros.append({"lead_id": lead.id, "cnpj": lead.cnpj, "tese": lead.tese, "erro": str(exc)})
    return {"leads_verificados": len(leads_e_tipos), "enviados": enviados, "erros": erros}


def buscar_emails_pendentes(conn, api_key: str) -> dict:
    """Busca o e-mail de cada lead ativo (de qualquer tese) que ainda não
    tem um cadastrado — roda automaticamente no cron diário, antes do
    envio, já que o usuário não opera por CLI em produção. Erro num lead
    (site fora do ar, cota esgotada etc.) não trava a busca dos demais.
    """
    leads = storage.leads_sem_email(conn)
    encontrados = 0
    erros = []
    for lead in leads:
        try:
            email = buscar_email_por_empresa(lead.razao_social or lead.cnpj, api_key)
        except EmailFinderError as exc:
            erros.append({"lead_id": lead.id, "cnpj": lead.cnpj, "tese": lead.tese, "erro": str(exc)})
            continue
        if email:
            storage.set_lead_email(conn, lead.id, email)
            encontrados += 1
    return {"leads_verificados": len(leads), "encontrados": encontrados, "erros": erros}


def gerar_relatorio_semanal(conn, desde: date, ate: date) -> str:
    desde_iso = datetime(desde.year, desde.month, desde.day, tzinfo=timezone.utc).isoformat()
    envios = storage.envios_desde(conn, desde_iso)
    if not envios:
        return f"Nenhum envio de campanha entre {desde.isoformat()} e {ate.isoformat()}."

    ids_enviados = {envio.id for envio in envios}
    eventos = storage.eventos_desde(conn, desde_iso)
    aberturas = {e.envio_id for e in eventos if e.tipo == "open" and e.envio_id in ids_enviados}
    cliques = {e.envio_id for e in eventos if e.tipo == "click" and e.envio_id in ids_enviados}

    total = len(envios)
    por_tipo = Counter(envio.tipo for envio in envios)

    leads_por_id: dict[int, Lead | None] = {}

    def _tese_do_envio(envio: Envio) -> str:
        if envio.lead_id not in leads_por_id:
            leads_por_id[envio.lead_id] = storage.get_lead(conn, envio.lead_id)
        lead = leads_por_id[envio.lead_id]
        return lead.tese if lead else "(desconhecida)"

    por_tese = Counter(_tese_do_envio(envio) for envio in envios)

    linhas = [
        f"Relatório semanal da campanha — {desde.isoformat()} a {ate.isoformat()}",
        "",
        f"E-mails enviados: {total}",
        f"Aberturas (únicas por envio): {len(aberturas)} ({len(aberturas) / total:.0%})",
        f"Cliques (únicos por envio): {len(cliques)} ({len(cliques) / total:.0%})",
        "",
        "Por tese:",
    ]
    for tese, qtd in sorted(por_tese.items()):
        linhas.append(f"  {tese}: {qtd} enviado(s)")
    linhas.append("")
    linhas.append("Por tipo de e-mail:")
    for tipo, qtd in sorted(por_tipo.items()):
        linhas.append(f"  {tipo}: {qtd} enviado(s)")

    return "\n".join(linhas)


def enviar_relatorio_semanal(
    conn, destinatario: str, smtp_host: str, smtp_port: int, smtp_username: str, smtp_password: str,
    smtp_from: str | None = None, hoje: date | None = None,
) -> None:
    hoje = hoje or date.today()
    desde = hoje - timedelta(days=7)
    corpo = gerar_relatorio_semanal(conn, desde, hoje)
    assunto = f"Relatório semanal — campanha ({desde.isoformat()} a {hoje.isoformat()})"
    send_email(destinatario, assunto, corpo, smtp_host, smtp_port, smtp_username, smtp_password, smtp_from=smtp_from)

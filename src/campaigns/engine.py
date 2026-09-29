"""Motor da campanha: decide quem recebe e-mail hoje (inicial ou próximo
follow-up), monta e envia a mensagem com rastreio, e monta o relatório
semanal de abertura/clique.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from src.campaigns import storage, tracking
from src.campaigns.models import DIAS_ENTRE_FOLLOWUPS, Envio, Lead, STATUS_ATIVO, TIPO_INICIAL, TIPOS_ENVIO
from src.fiscal_monitor.email_client import send_email, send_email_html


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


def leads_para_enviar_hoje(conn) -> list[tuple[Lead, str]]:
    """[(lead, tipo_envio)] pra cada lead ativo com e-mail que precisa de contato hoje."""
    resultado = []
    for lead in storage.list_leads(conn):
        if lead.status != STATUS_ATIVO or not lead.email:
            continue
        tipo = _proximo_tipo_envio(storage.envios_do_lead(conn, lead.id))
        if tipo:
            resultado.append((lead, tipo))
    return resultado


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
    template = storage.get_template(conn, tipo)
    if template is None:
        raise RuntimeError(f"Template '{tipo}' não encontrado — o banco não foi inicializado corretamente.")

    envio = storage.create_envio(conn, lead.id, tipo)

    contexto = {
        "razao_social": lead.razao_social or lead.cnpj,
        "cnpj": lead.cnpj,
        "link_cta": tracking.click_url(base_url, envio.tracking_token, template.link_cta),
    }
    assunto = template.assunto.format(**contexto)
    corpo_texto = template.corpo.format(**contexto)
    corpo_html = tracking.montar_corpo_html(corpo_texto, base_url, envio.tracking_token)

    send_email_html(
        lead.email, assunto, corpo_texto, corpo_html, smtp_host, smtp_port, smtp_username, smtp_password,
        smtp_from=smtp_from,
    )


def rodar_diario(
    conn, base_url: str, smtp_host: str, smtp_port: int, smtp_username: str, smtp_password: str,
    smtp_from: str | None = None,
) -> dict:
    """Roda o envio do dia pra todos os leads que precisam de contato —
    erro num lead não trava os demais, fica registrado no resultado.
    """
    leads_e_tipos = leads_para_enviar_hoje(conn)
    enviados = 0
    erros = []
    for lead, tipo in leads_e_tipos:
        try:
            enviar_para_lead(conn, lead, tipo, base_url, smtp_host, smtp_port, smtp_username, smtp_password, smtp_from=smtp_from)
            enviados += 1
        except Exception as exc:
            erros.append({"lead_id": lead.id, "cnpj": lead.cnpj, "erro": str(exc)})
    return {"leads_verificados": len(leads_e_tipos), "enviados": enviados, "erros": erros}


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

    linhas = [
        f"Relatório semanal da campanha PGFN — {desde.isoformat()} a {ate.isoformat()}",
        "",
        f"E-mails enviados: {total}",
        f"Aberturas (únicas por envio): {len(aberturas)} ({len(aberturas) / total:.0%})",
        f"Cliques (únicos por envio): {len(cliques)} ({len(cliques) / total:.0%})",
        "",
        "Por tipo de e-mail:",
    ]
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
    assunto = f"Relatório semanal — campanha PGFN ({desde.isoformat()} a {hoje.isoformat()})"
    send_email(destinatario, assunto, corpo, smtp_host, smtp_port, smtp_username, smtp_password, smtp_from=smtp_from)

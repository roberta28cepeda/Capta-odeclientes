"""Motor da campanha: decide quem recebe e-mail hoje (inicial ou próximo
follow-up) respeitando o limite diário por tese, monta e envia a mensagem
com rastreio (HTML no design da Leactis, CTA pro WhatsApp), e monta o
relatório semanal de abertura/clique.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from urllib.parse import quote

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
from src.campaigns.phone_finder import PhoneFinderError, buscar_telefone_por_cnpj
from src.fiscal_monitor.email_client import send_email, send_email_html

_TAG_HTML_RE = re.compile(r"<[^>]+>")


def _proximo_tipo_envio(envios: list[Envio]) -> str | None:
    """Dado o histórico de envios de um lead, retorna o próximo tipo a
    mandar, ou None se já mandou tudo (inicial + follow-up) ou se ainda não
    passou tempo suficiente desde o último envio.
    """
    if not envios:
        return TIPO_INICIAL
    ultimo = envios[-1]
    if ultimo.tipo not in TIPOS_ENVIO:
        return None  # tipo de uma versão antiga da cadência (ex: followup_2/3) — não manda mais nada
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
    """Manda o e-mail inicial (HTML com o design da marca) ou o follow-up
    (texto puro, de propósito, pra soar pessoal — mesmo padrão do Apps
    Script: nunca um follow-up com o mesmo visual do e-mail inicial).
    """
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

    if tipo == TIPO_INICIAL:
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
    else:
        corpo_texto = "\n\n".join(
            texto for texto in (
                _remover_tags_html(headline), _remover_tags_html(paragrafo1), _remover_tags_html(paragrafo2),
                _remover_tags_html(italico), f"{template.cta_texto}: {cta_url}",
            ) if texto.strip()
        )
        send_email(
            lead.email, assunto, corpo_texto, smtp_host, smtp_port, smtp_username, smtp_password, smtp_from=smtp_from
        )


ORCAMENTO_ENVIO_SEGUNDOS = 100
"""Tempo máximo que `rodar_diario` deixa passar mandando e-mail antes de
parar e devolver o que já conseguiu — ver `ORCAMENTO_BUSCA_EMAIL_SEGUNDOS`
pra explicação completa do porquê (resumo: a função serverless do Vercel
mata a execução aos 300s, e cada etapa (busca de e-mail, busca de
telefone, envio) precisa caber na fatia dela do orçamento total)."""


def rodar_diario(
    conn, base_url: str, smtp_host: str, smtp_port: int, smtp_username: str, smtp_password: str,
    smtp_from: str | None = None,
    orcamento_segundos: float = ORCAMENTO_ENVIO_SEGUNDOS,
) -> dict:
    """Roda o envio do dia pra todos os leads que precisam de contato,
    respeitando o limite diário por tese — erro num lead não trava os
    demais, fica registrado no resultado. Pára de mandar mais e-mail (sem
    erro, só interrompe) se passar do orçamento de tempo — o resto fica
    pendente pra próxima execução.

    `leads_enviados` traz os objetos `Lead` de quem recebeu e-mail agora
    (usado só internamente, pra montar o resumo de WhatsApp da equipe — não
    é serializável em JSON, quem chamar isso direto num endpoint precisa
    tirar essa chave do dicionário antes de devolver a resposta).
    """
    leads_e_tipos = leads_para_enviar_hoje(conn)
    inicio = monotonic()
    enviados = 0
    erros = []
    leads_enviados: list[Lead] = []
    for lead, tipo in leads_e_tipos:
        if monotonic() - inicio > orcamento_segundos:
            break
        try:
            enviar_para_lead(conn, lead, tipo, base_url, smtp_host, smtp_port, smtp_username, smtp_password, smtp_from=smtp_from)
            enviados += 1
            leads_enviados.append(lead)
        except Exception as exc:
            erros.append({"lead_id": lead.id, "cnpj": lead.cnpj, "tese": lead.tese, "erro": str(exc)})
    return {"leads_verificados": len(leads_e_tipos), "enviados": enviados, "erros": erros, "leads_enviados": leads_enviados}


LIMITE_BUSCA_TELEFONE_POR_EXECUCAO = 50
"""Teto superior de leads processados numa chamada — a defesa de verdade
contra travar é o orçamento de tempo abaixo; isso aqui só evita processar
uma lista gigante em memória sem necessidade."""

ORCAMENTO_BUSCA_TELEFONE_SEGUNDOS = 80
"""Essa função chama a ReceitaWS uma vez por lead, cada chamada com até
10s de timeout — com dezenas de leads pendentes (comum em carteira grande
importada da PGFN), um teto só por *quantidade* ainda podia estourar o
tempo máximo da função serverless do Vercel (300s) se a API estivesse
lenta, deixando o botão "Rodar agora" preso em "carregando" pra sempre.
Por isso o corte agora é por *tempo decorrido*, verificado antes de cada
chamada — pára e devolve o que já achou assim que bate o orçamento, sem
erro, e o resto fica pendente pra próxima execução. Mesmo padrão em
`buscar_emails_pendentes` e `rodar_diario`, cada um com sua fatia do
orçamento total de 300s."""


def buscar_telefones_pendentes(
    conn, limite: int = LIMITE_BUSCA_TELEFONE_POR_EXECUCAO, orcamento_segundos: float = ORCAMENTO_BUSCA_TELEFONE_SEGUNDOS
) -> dict:
    """Busca o telefone de cada lead ativo (de qualquer tese) que ainda não
    tem um cadastrado, via ReceitaWS — pára assim que bate no limite de
    consultas por minuto da API gratuita (ou no orçamento de tempo), em vez
    de insistir; o resto fica pendente pro próximo cron (igual o
    enriquecimento por hora do Apps Script, só que aqui roda dentro do
    mesmo cron diário).
    """
    leads = storage.leads_sem_telefone(conn)[:limite]
    inicio = monotonic()
    verificados = 0
    encontrados = 0
    erros = []
    for lead in leads:
        if monotonic() - inicio > orcamento_segundos:
            break
        try:
            telefone = buscar_telefone_por_cnpj(lead.cnpj)
        except PhoneFinderError as exc:
            erros.append({"lead_id": lead.id, "cnpj": lead.cnpj, "tese": lead.tese, "erro": str(exc)})
            break  # provavelmente rate limit — não adianta insistir nos próximos
        verificados += 1
        if telefone:
            storage.set_lead_telefone(conn, lead.id, telefone)
            encontrados += 1
    return {"leads_verificados": verificados, "encontrados": encontrados, "erros": erros}


_MENSAGEM_WHATSAPP_DIVIDA = (
    "⚠️ R$ {{VALOR}}… esse é o valor aproximado da pendência que identificamos vinculada à {{EMPRESA}}.\n\n"
    "E tem um ponto importante: enquanto essa dívida continuar em aberto, o valor pode seguir aumentando "
    "com juros e encargos.\n\n"
    "Por isso, nosso time separou alguns horários para analisar a situação da {{EMPRESA}} e orientar "
    "sobre as possibilidades de regularização.\n\n"
    "📅 Temos disponibilidade [DIA] às [HORÁRIO 1] ou [DIA] às [HORÁRIO 2].\n\n"
    "Qual dos dois horários funciona melhor pra você?"
)

# Mensagens reais (vindas do Apps Script) por tese — [DIA]/[HORÁRIO 1]/[HORÁRIO 2]
# ficam literais de propósito: quem for mandar edita isso na hora, no WhatsApp,
# antes de enviar (o envio em si nunca é automático). Tese sem mensagem própria
# cai na mensagem padrão de dívida (`_MENSAGEM_WHATSAPP_DIVIDA`).
_MENSAGENS_WHATSAPP_POR_TESE: dict[str, str] = {
    "transportadoras_pgfn": _MENSAGEM_WHATSAPP_DIVIDA,
    "contadores_certificado": (
        "💰 Seus clientes já compram certificado digital… mas essa receita pode estar ficando na mesa.\n\n"
        "Estamos ampliando a rede de contabilidades parceiras da Leactis para ajudar escritórios a "
        "transformar uma demanda que já existe na carteira em uma nova fonte de receita.\n\n"
        "🔓 Funciona assim: você indica o cliente, nosso time cuida de todo o atendimento e da emissão, "
        "e seu escritório recebe por cada certificado emitido.\n\n"
        "A parceria está sendo ampliada a partir do nosso relacionamento com a Fenacon e a Safeweb.\n\n"
        "📅 Separamos um horário rápido pra te mostrar como funciona: [DIA] às [HORÁRIO 1] ou [DIA] às "
        "[HORÁRIO 2].\n\n"
        "Qual dos dois horários funciona melhor pra você?"
    ),
    "simples_ibs_cbs": (
        "⚠️ 2027 está chegando… e identificamos uma pendência relacionada ao Simples Nacional da "
        "{{EMPRESA}} que merece atenção antes da virada do ano.\n\n"
        "Dependendo do caso, deixar essa situação em aberto pode afetar a regularidade fiscal da empresa "
        "e trazer consequências para sua permanência no regime.\n\n"
        "Por isso, estamos antecipando essa análise com algumas empresas antes que o problema fique "
        "para a última hora.\n\n"
        "📅 Nosso time tem disponibilidade [DIA] às [HORÁRIO 1] ou [DIA] às [HORÁRIO 2] para analisar o "
        "caso da {{EMPRESA}}.\n\n"
        "Qual horário funciona melhor pra você?"
    ),
    "industria_tributaria_geral": (
        "⚠️ R$ {{VALOR}}… esse é o valor aproximado do débito tributário federal que identificamos "
        "vinculado à {{EMPRESA}}, na Lista de Devedores da União.\n\n"
        "Enquanto isso não for resolvido, a {{EMPRESA}} fica sem Certidão Negativa de Débitos — o que "
        "trava renovação de crédito, licitação e negociação com fornecedores e clientes maiores. E o "
        "valor só cresce com juros (SELIC) enquanto a dívida continuar em aberto.\n\n"
        "Existe a possibilidade de negociar desconto em juros e multa, além de parcelamento estendido, "
        "via transação tributária federal — mas as condições de cada edital mudam com o tempo.\n\n"
        "📅 Nosso time tem disponibilidade [DIA] às [HORÁRIO 1] ou [DIA] às [HORÁRIO 2] para analisar o "
        "caso da {{EMPRESA}}.\n\n"
        "Qual horário funciona melhor pra você?"
    ),
    "mei_regularizacao": (
        "⚠️ Identificamos uma pendência no seu MEI ({{EMPRESA}}) — DAS em atraso e/ou declaração anual "
        "não entregue.\n\n"
        "Enquanto isso não for resolvido, você não consegue emitir nota, abrir conta PJ nem fechar "
        "contrato com empresas maiores — e corre risco real de ter o CNPJ cancelado de ofício pela "
        "Receita Federal. Cada mês em atraso também é um mês a menos contando pra sua aposentadoria pelo "
        "INSS.\n\n"
        "📅 Separamos um horário rápido pra resolver isso com você: [DIA] às [HORÁRIO 1] ou [DIA] às "
        "[HORÁRIO 2].\n\n"
        "Qual horário funciona melhor pra você?"
    ),
}


def tem_mensagem_whatsapp_dedicada(tese: str) -> bool:
    """Usado só pra diagnóstico (`/admin/status`) — indica se a tese tem
    mensagem de WhatsApp própria ou cai na genérica de dívida."""
    return tese in _MENSAGENS_WHATSAPP_POR_TESE


def montar_link_whatsapp(lead: Lead) -> str | None:
    """Link `wa.me` com mensagem pré-escrita pra equipe mandar a primeira
    mensagem pro lead — nunca automático (ver `README.md`, decisão de
    política: mandar a primeira mensagem comercial fria por WhatsApp sem
    consentimento fere a política da Meta e arrisca banir o número).
    """
    if not lead.telefone:
        return None
    numero = re.sub(r"\D", "", lead.telefone)
    if not numero:
        return None
    if not numero.startswith("55"):
        numero = f"55{numero}"
    nome = lead.razao_social or lead.cnpj
    template = _MENSAGENS_WHATSAPP_POR_TESE.get(lead.tese, _MENSAGEM_WHATSAPP_DIVIDA)
    mensagem = template.replace("{{EMPRESA}}", nome).replace("{{VALOR}}", _formatar_valor_brl(lead.valor_divida))
    return f"https://wa.me/{numero}?text={quote(mensagem)}"


def montar_resumo_whatsapp(leads: list[Lead], base_url: str) -> str:
    if not leads:
        return "Nenhum lead com telefone pra contato via WhatsApp hoje."
    linhas = ["Leads de hoje com telefone pra contato via WhatsApp:", ""]
    for lead in leads:
        nome = lead.razao_social or lead.cnpj
        linhas.append(f"- {nome} ({lead.cnpj}, {lead.tese}): {montar_link_whatsapp(lead)}")
    linhas.append("")
    linhas.append(
        f"Ou usa o cartão pra ir passando um lead de cada vez (evita duplicar contato): "
        f"{base_url}/admin/campanhas/whatsapp"
    )
    return "\n".join(linhas)


def enviar_resumo_whatsapp_equipe(
    conn, leads: list[Lead], destinatario: str, base_url: str, smtp_host: str, smtp_port: int, smtp_username: str,
    smtp_password: str, smtp_from: str | None = None,
) -> None:
    corpo = montar_resumo_whatsapp(leads, base_url)
    send_email(
        destinatario, "Leads de hoje pra WhatsApp — campanha", corpo, smtp_host, smtp_port, smtp_username,
        smtp_password, smtp_from=smtp_from,
    )


LIMITE_BUSCA_EMAIL_POR_EXECUCAO = 50
"""Teto superior de leads processados por chamada — a defesa de verdade
contra travar é o orçamento de tempo abaixo; isso aqui só evita processar
uma lista gigante (ex: dezenas de milhares de leads importados de uma
planilha da PGFN) em memória sem necessidade. Processa em ordem de
importação (mais antigos primeiro) e vai avançando um pouco a cada
execução diária até zerar o backlog."""

ORCAMENTO_BUSCA_EMAIL_SEGUNDOS = 80
"""Cada lead pode envolver duas chamadas HTTP com até 10s de timeout cada
(busca + extração da página) — um teto só por *quantidade* ainda podia
deixar essa etapa sozinha estourar o tempo máximo da função serverless do
Vercel (300s) se a Exa ou os sites de origem estivessem lentos, e foi
exatamente isso que aconteceu em produção (timeout de 300s confirmado nos
logs). Por isso o corte agora é por *tempo decorrido*: pára e devolve o
que já achou assim que bate o orçamento, sem contar como erro, e o resto
fica pendente pra próxima execução — se autorregula sozinho conforme a
API está mais rápida ou mais lenta no dia, sem precisar reajustar número
na mão. Mesmo padrão em `buscar_telefones_pendentes` e `rodar_diario`,
cada um com sua fatia do orçamento total de 300s."""


def buscar_emails_pendentes(
    conn, api_key: str, limite: int = LIMITE_BUSCA_EMAIL_POR_EXECUCAO, orcamento_segundos: float = ORCAMENTO_BUSCA_EMAIL_SEGUNDOS
) -> dict:
    """Busca o e-mail de cada lead ativo (de qualquer tese) que ainda não
    tem um cadastrado — roda automaticamente no cron diário, antes do
    envio, já que o usuário não opera por CLI em produção. Erro num lead
    (site fora do ar, cota esgotada etc.) não trava a busca dos demais.
    """
    leads = storage.leads_sem_email(conn)[:limite]
    inicio = monotonic()
    verificados = 0
    encontrados = 0
    erros = []
    for lead in leads:
        if monotonic() - inicio > orcamento_segundos:
            break
        verificados += 1
        try:
            email = buscar_email_por_empresa(lead.razao_social or lead.cnpj, api_key)
        except EmailFinderError as exc:
            erros.append({"lead_id": lead.id, "cnpj": lead.cnpj, "tese": lead.tese, "erro": str(exc)})
            continue
        if email:
            storage.set_lead_email(conn, lead.id, email)
            encontrados += 1
    return {"leads_verificados": verificados, "encontrados": encontrados, "erros": erros}


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

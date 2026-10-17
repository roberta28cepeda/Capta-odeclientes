"""Rotas web da campanha de prospecção (multi-tese): importação de leads
por tese, edição estruturada dos templates de e-mail, pixel de
abertura/link de clique rastreável, e o endpoint de cron que dispara os
envios do dia.

Registradas no mesmo app Flask do `fiscal_monitor` (`create_app()` em
`fiscal_monitor/server.py`) — mesmo projeto Vercel, mesmo Postgres, mesmo
login de admin.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template_string, request

from src.campaigns import brevo_client, engine, storage, tracking
from src.campaigns.brevo_client import BrevoSyncError
from src.campaigns.models import ESTAGIOS_LEAD, TIPOS_ENVIO
from src.campaigns.templates import DEFAULT_TEMPLATES
from src.common.web_styles import page
from src.common.webauth import cron_authorized, require_admin

bp = Blueprint("campaigns", __name__)


def _connect():
    db_path = current_app.config.get("CAMPAIGNS_DB_PATH") or storage.DEFAULT_DB_PATH
    return storage.connect(db_path)


def _connect_fiscal():
    """Conexão com o banco do `fiscal_monitor` (Carteira) — em produção é o
    mesmo Postgres, tabelas com prefixo diferente; usado só pela conversão
    de lead em cliente, que cria tenant/CNPJ do outro lado (ver
    `src.campaigns.engine`/`phone_finder.py`, que já importam de
    `fiscal_monitor` — mesmo padrão de dependência cruzada entre módulos).
    """
    from src.fiscal_monitor import storage as fiscal_storage

    db_path = current_app.config.get("DB_PATH") or fiscal_storage.DEFAULT_DB_PATH
    return fiscal_storage.connect(db_path)


def _quem_atual() -> str:
    auth = request.authorization
    if auth and auth.username:
        return auth.username
    return "desconhecido"


def _teses_conhecidas(conn) -> list[str]:
    """União das teses já seedadas no código com qualquer tese nova criada
    só no banco (leads importados ou template salvo pra uma tese ainda não
    prevista em `templates.py`).
    """
    return sorted(set(DEFAULT_TEMPLATES.keys()) | set(storage.list_teses(conn)) | set(storage.list_template_teses(conn)))


_LEADS_TEMPLATE = page("Campanha — Leads", """
<h1>Leads da campanha{% if tese %} — {{ tese }}{% endif %}</h1>
<p class="nav">
   <a href="/admin/campanhas/leads/importar">+ Importar leads (CSV)</a>
   <a href="/admin/campanhas/templates{% if tese %}?tese={{ tese }}{% endif %}">Editar templates de e-mail</a>
   <a href="/admin/campanhas/whatsapp">Cartão de contato via WhatsApp</a>
   <a href="/admin/campanhas/rodar-agora">Rodar campanha agora</a>
   <a href="/admin/campanhas/leads/aparar">Podar lista de leads</a>
</p>

{% if pausado %}
<div class="alert">Envio de e-mails da campanha está <strong>pausado</strong> — nem o cron automático nem o botão
"Rodar campanha agora" disparam e-mail enquanto isso. <form method="post" action="/admin/campanhas/retomar" class="inline"><button type="submit">Retomar envios</button></form></div>
{% else %}
<div class="card"><form method="post" action="/admin/campanhas/pausar" class="inline"><button type="submit">Pausar envio de e-mails</button></form></div>
{% endif %}

<div class="card">
<h2 style="margin-top:0">Painel — o que já saiu</h2>
<table>
<tr><th>Tese</th><th>Leads</th><th>Com e-mail</th><th>Com telefone</th><th>Enviados hoje</th><th>Enviados (7 dias)</th><th>Aberturas</th><th>Cliques</th><th>Taxa de abertura</th></tr>
{% for t, m in metricas.items() %}
<tr>
  <td>{{ t }}</td>
  <td>{{ m.leads }}</td>
  <td>{{ m.com_email }}</td>
  <td>{{ m.com_telefone }}</td>
  <td>{{ m.enviados_hoje }}</td>
  <td>{{ m.enviados_semana }}</td>
  <td>{{ m.aberturas }}</td>
  <td>{{ m.cliques }}</td>
  <td>{{ "%.0f"|format(m.aberturas / m.enviados_semana * 100) if m.enviados_semana else "-" }}{{ "%" if m.enviados_semana else "" }}</td>
</tr>
{% endfor %}
</table>
{% if not metricas %}<p>Nenhum lead importado ainda.</p>{% endif %}
<p><small>Aberturas/cliques contam envios únicos (não eventos repetidos) desde o início da
campanha; enviados contam só o período indicado na coluna.</small></p>
</div>

<div class="tabs">Teses:
{% for t in teses %}<a href="/admin/campanhas/leads?tese={{ t }}{% if estagio_filtro %}&estagio={{ estagio_filtro }}{% endif %}"{% if t == tese %} class="ativa"{% endif %}>{{ t }}</a>{% endfor %}
<a href="/admin/campanhas/leads{% if estagio_filtro %}?estagio={{ estagio_filtro }}{% endif %}">(todas)</a>
</div>
<div class="tabs">Estágio do funil:
{% for e in estagios %}<a href="/admin/campanhas/leads?estagio={{ e }}{% if tese %}&tese={{ tese }}{% endif %}"{% if e == estagio_filtro %} class="ativa"{% endif %}>{{ e }}</a>{% endfor %}
<a href="/admin/campanhas/leads{% if tese %}?tese={{ tese }}{% endif %}">(todos)</a>
</div>
<table>
<tr><th>CNPJ</th><th>Tese</th><th>Razão social</th><th>Valor dívida</th><th>E-mail</th><th>Status</th><th>Envios</th><th>Estágio</th><th></th></tr>
{% for lead, envios in leads %}
<tr>
  <td>{{ lead.cnpj }}</td>
  <td>{{ lead.tese }}</td>
  <td>{{ lead.razao_social or "-" }}</td>
  <td>{{ "R$ %.2f"|format(lead.valor_divida) if lead.valor_divida else "-" }}</td>
  <td>{{ lead.email or "(sem e-mail)" }}</td>
  <td>{{ lead.status }}</td>
  <td>{{ envios|join(", ") if envios else "-" }}</td>
  <td>
    <form method="post" action="/admin/campanhas/leads/{{ lead.id }}/estagio?tese={{ tese or '' }}&estagio_filtro={{ estagio_filtro or '' }}" class="inline">
      <select name="estagio" onchange="this.form.submit()">
        {% for e in estagios %}<option value="{{ e }}" {% if e == lead.estagio %}selected{% endif %}>{{ e }}</option>{% endfor %}
      </select>
    </form>
  </td>
  <td>
    {% if lead.estagio == "fechado" %}
    <form method="post" action="/admin/campanhas/leads/{{ lead.id }}/converter-em-cliente" class="inline">
      <button type="submit">Converter em cliente</button>
    </form>
    {% endif %}
  </td>
</tr>
{% endfor %}
</table>
""")

_IMPORTAR_LEADS_TEMPLATE = page("Importar leads", """
<p><a href="/admin/campanhas/leads">&larr; voltar</a></p>
<h1>Importar leads da campanha</h1>
{% if resultado %}<div class="success">{{ resultado }}</div>{% endif %}
<form method="post" enctype="multipart/form-data" class="card">
  <label>Tese (planilha)
     <input type="text" name="tese" list="teses-conhecidas" required placeholder="ex: transportadoras_pgfn">
     <datalist id="teses-conhecidas">{% for t in teses %}<option value="{{ t }}">{% endfor %}</datalist>
  </label>
  <label>CSV (colunas: cnpj,razao_social,email,valor_divida — email e valor_divida são opcionais)
     <input type="file" name="csv" accept=".csv" required></label>
  <button type="submit">Importar</button>
</form>
""")

_APARAR_LEADS_TEMPLATE = page("Podar lista de leads", """
<p><a href="/admin/campanhas/leads">&larr; voltar</a></p>
<h1>Podar lista de leads</h1>
<p>Mantém só os leads de maior valor de dívida pra uma tese, apagando o resto —
nunca apaga um lead que já recebeu algum e-mail (contato em andamento fica intacto).
Use isso quando uma planilha importada for grande demais pro ritmo real de busca de
e-mail/telefone e envio diário.</p>
{% if resultado %}<div class="success">{{ resultado }}</div>{% endif %}
<form method="post" class="card">
  <label>Tese<br>
    <select name="tese" required>
      {% for t in teses %}<option value="{{ t }}">{{ t }}</option>{% endfor %}
    </select>
  </label>
  <label>Manter quantos leads (os de maior valor de dívida)<input type="number" name="manter" value="500" min="1" required></label>
  <button type="submit">Podar agora</button>
</form>
""")

_TEMPLATES_TEMPLATE = page("Templates da campanha", """
<p><a href="/admin/campanhas/leads?tese={{ tese }}">&larr; voltar pros leads dessa tese</a></p>
<h1>Templates de e-mail — {{ tese }}</h1>
<div class="tabs">Teses:
{% for t in teses %}<a href="/admin/campanhas/templates?tese={{ t }}"{% if t == tese %} class="ativa"{% endif %}>{{ t }}</a>{% endfor %}
</div>
<p><small>Placeholders disponíveis em assunto/título/parágrafos/frase de urgência: <code>{{ '{{RAZAO_SOCIAL}}' }}</code>, <code>{{ '{{CNPJ}}' }}</code>, <code>{{ '{{VALOR_DIVIDA}}' }}</code></small></p>
{% for template in templates %}
<div class="card">
<h2 style="margin-top:0">{{ template.tipo }}</h2>
<form method="post" action="/admin/campanhas/templates/{{ tese }}/{{ template.tipo }}">
  <label>Assunto<input type="text" name="assunto" style="max-width:100%" value="{{ template.assunto }}"></label>
  <label>Tag (selo no topo do e-mail)<input type="text" name="tag" style="max-width:100%" value="{{ template.tag }}"></label>
  <label>Título<textarea name="headline" rows="2" style="max-width:100%">{{ template.headline }}</textarea></label>
  <label>Parágrafo 1<textarea name="paragrafo1" rows="3" style="max-width:100%">{{ template.paragrafo1 }}</textarea></label>
  <label>Parágrafo 2<textarea name="paragrafo2" rows="3" style="max-width:100%">{{ template.paragrafo2 }}</textarea></label>
  <label>Checklist (um item por linha)<textarea name="checklist" rows="4" style="max-width:100%">{{ template.checklist|join("\n") }}</textarea></label>
  <label>Frase de urgência (itálico)<textarea name="italico" rows="2" style="max-width:100%">{{ template.italico }}</textarea></label>
  <label>Texto do botão (CTA)<input type="text" name="cta_texto" style="max-width:100%" value="{{ template.cta_texto }}"></label>
  <label>Link de destino do CTA<input type="text" name="link_cta" style="max-width:100%" value="{{ template.link_cta }}"></label>
  <label>Nota de rodapé (itálico, cinza)<textarea name="rodape_nota" rows="2" style="max-width:100%">{{ template.rodape_nota }}</textarea></label>
  <button type="submit">Salvar {{ template.tipo }}</button>
</form>
</div>
{% endfor %}
""")


_WHATSAPP_CARTAO_TEMPLATE = page("Cartão WhatsApp — Campanha", """
<p><a href="/admin/campanhas/leads">&larr; voltar pros leads</a></p>
<h1>Cartão de contato via WhatsApp</h1>
<p class="lede">Mostra um lead pendente de cada vez — assim que alguém marca como
contatado, ele some da fila pra quem mais abrir essa página (evita
contato duplicado quando várias pessoas usam o mesmo número).</p>
{% if lead %}
<div class="card" style="max-width:420px">
  <h2 style="margin-top:0">{{ lead.razao_social or lead.cnpj }}</h2>
  <p>CNPJ: {{ lead.cnpj }} — Tese: {{ lead.tese }}</p>
  {% if lead.valor_divida %}<p>Dívida: R$ {{ "%.2f"|format(lead.valor_divida) }}</p>{% endif %}
  <p><a href="{{ link_whatsapp }}" target="_blank" rel="noopener">Abrir WhatsApp com mensagem pronta &rarr;</a></p>
  <form method="post" action="/admin/campanhas/whatsapp/{{ lead.id }}/contatado">
    <button type="submit">Marquei como contatado</button>
  </form>
</div>
<p>Faltam mais {{ restantes }} lead(s) na fila.</p>
{% else %}
<p>Nenhum lead pendente de contato via WhatsApp no momento (sem telefone achado ainda, ou todo mundo já foi contatado).</p>
{% endif %}
""")

_RODAR_AGORA_TEMPLATE = page("Rodar campanha agora", """
<p><a href="/admin/campanhas/leads">&larr; voltar pros leads</a></p>
<h1>Rodar campanha agora</h1>
<p>Dispara manualmente o mesmo processo do cron diário (busca de e-mail/telefone pendente,
envio de e-mails do dia, resumo de WhatsApp pra equipe, relatório semanal às segundas) —
use isso pra testar, ou se o agendamento automático do Vercel atrasar ou falhar.</p>
<form method="post">
  <button type="submit">Rodar agora</button>
</form>
{% if resultado %}
  {% if resultado.pausado %}
  <div class="alert">Envio de e-mails está pausado — nenhum e-mail foi disparado.
  <a href="/admin/campanhas/leads">Retome em Leads da campanha &rarr;</a></div>
  {% elif resultado.error %}
  <div class="alert">{{ resultado.error }}</div>
  {% else %}
  <h2>Resultado</h2>
  <table>
    <tr><td>Leads verificados hoje</td><td>{{ resultado.leads_verificados }}</td></tr>
    <tr><td>E-mails enviados</td><td>{{ resultado.enviados }}</td></tr>
    <tr><td>Erros no envio</td><td>{{ resultado.erros|length }}</td></tr>
    <tr><td>Busca de e-mail (Exa)</td><td>{{ resultado.busca_email.encontrados if resultado.busca_email else "não configurado (sem EXA_API_KEY)" }} achado(s) de {{ resultado.busca_email.leads_verificados if resultado.busca_email else 0 }} verificado(s)</td></tr>
    <tr><td>Busca de telefone (ReceitaWS)</td><td>{{ resultado.busca_telefone.encontrados }} achado(s) de {{ resultado.busca_telefone.leads_verificados }} verificado(s)</td></tr>
    <tr><td>Resumo de WhatsApp enviado pra equipe</td><td>{{ "sim" if resultado.resumo_whatsapp_enviado else "não" }}</td></tr>
    <tr><td>Relatório semanal enviado</td><td>{{ "sim" if resultado.relatorio_semanal_enviado else "não (só roda às segundas)" }}</td></tr>
  </table>
  {% if resultado.erros %}
  <h2>Detalhe dos erros</h2>
  <table>
    <tr><th>CNPJ</th><th>Tese</th><th>Erro</th></tr>
    {% for erro in resultado.erros %}
    <tr><td>{{ erro.cnpj }}</td><td>{{ erro.tese }}</td><td>{{ erro.erro }}</td></tr>
    {% endfor %}
  </table>
  {% endif %}
  {% endif %}
{% endif %}
""")


@bp.get("/admin/campanhas/whatsapp")
def cartao_whatsapp():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    pendentes = storage.leads_pendentes_whatsapp(conn)
    lead = pendentes[0] if pendentes else None
    link_whatsapp = engine.montar_link_whatsapp(lead) if lead else None
    return render_template_string(
        _WHATSAPP_CARTAO_TEMPLATE, lead=lead, link_whatsapp=link_whatsapp, restantes=max(0, len(pendentes) - 1)
    )


@bp.post("/admin/campanhas/whatsapp/<int:lead_id>/contatado")
def marcar_contatado_whatsapp(lead_id: int):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    storage.set_lead_whatsapp_contatado(conn, lead_id)
    return redirect("/admin/campanhas/whatsapp")


@bp.get("/admin/campanhas/leads")
def listar_leads():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    tese = request.args.get("tese") or None
    estagio_filtro = request.args.get("estagio") or None
    leads_db = storage.list_leads(conn, tese=tese)
    if estagio_filtro:
        leads_db = [lead for lead in leads_db if lead.estagio == estagio_filtro]
    # Antes disso, cada lead disparava sua própria consulta de envios (N+1)
    # — com a lista de leads já na casa dos milhares (importação da PGFN),
    # essa página sozinha estourava o timeout de 300s do Vercel e ficava
    # "carregando" pra sempre. `envios_por_lead_ids` busca tudo numa
    # consulta só.
    envios_por_lead = storage.envios_por_lead_ids(conn, [lead.id for lead in leads_db])
    leads = [(lead, [envio.tipo for envio in envios_por_lead.get(lead.id, [])]) for lead in leads_db]
    hoje_iso = datetime.combine(date.today(), time.min, tzinfo=timezone.utc).isoformat()
    semana_iso = datetime.combine(date.today() - timedelta(days=7), time.min, tzinfo=timezone.utc).isoformat()
    metricas = storage.metricas_por_tese(conn, hoje_iso, semana_iso)
    pausado = storage.envios_pausados(conn)
    return render_template_string(
        _LEADS_TEMPLATE, leads=leads, tese=tese, teses=_teses_conhecidas(conn), metricas=metricas,
        estagios=ESTAGIOS_LEAD, estagio_filtro=estagio_filtro, pausado=pausado,
    )


@bp.post("/admin/campanhas/pausar")
def pausar_campanha():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    storage.pausar_envios(conn, _quem_atual())
    return redirect("/admin/campanhas/leads")


@bp.post("/admin/campanhas/retomar")
def retomar_campanha():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    storage.retomar_envios(conn, _quem_atual())
    return redirect("/admin/campanhas/leads")


@bp.post("/admin/campanhas/leads/<int:lead_id>/estagio")
def mudar_estagio_lead(lead_id: int):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    estagio = request.form.get("estagio") or ""
    conn = _connect()
    if estagio in ESTAGIOS_LEAD:
        storage.set_lead_estagio(conn, lead_id, estagio)
    tese = request.args.get("tese", "")
    estagio_filtro = request.args.get("estagio_filtro", "")
    destino = "/admin/campanhas/leads?"
    partes = []
    if tese:
        partes.append(f"tese={tese}")
    if estagio_filtro:
        partes.append(f"estagio={estagio_filtro}")
    return redirect(destino + "&".join(partes))


@bp.post("/admin/campanhas/leads/<int:lead_id>/converter-em-cliente")
def converter_lead_em_cliente(lead_id: int):
    """Fecha o elo Captação→Carteira: um lead marcado como "fechado" vira
    tenant + CNPJ na carteira (módulo `fiscal_monitor`), sem precisar
    recadastrar nada a mão — hoje em produção isso era 100% manual.
    """
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    lead = storage.get_lead(conn, lead_id)
    if lead is None:
        return jsonify({"error": "lead não encontrado"}), 404

    fiscal_conn = _connect_fiscal()
    from src.fiscal_monitor import storage as fiscal_storage

    nome_tenant = lead.razao_social or lead.cnpj
    tenant = fiscal_storage.create_tenant(fiscal_conn, nome_tenant, contato_email=lead.email)
    fiscal_storage.upsert_cnpj(fiscal_conn, tenant.id, lead.cnpj, razao_social=lead.razao_social)
    fiscal_storage.registrar_auditoria(
        fiscal_conn, _quem_atual(), "lead_convertido_em_cliente", "tenant", tenant.id,
        f"lead_id={lead_id} cnpj={lead.cnpj} tese={lead.tese}",
    )
    fiscal_conn.close()
    return redirect(f"/tenants/{tenant.id}")


@bp.route("/admin/campanhas/leads/importar", methods=["GET", "POST"])
def importar_leads():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    if request.method == "GET":
        return render_template_string(_IMPORTAR_LEADS_TEMPLATE, teses=_teses_conhecidas(conn))

    tese = (request.form.get("tese") or "").strip()
    csv_file = request.files.get("csv")
    if not tese:
        return render_template_string(_IMPORTAR_LEADS_TEMPLATE, resultado="Informe a tese.", teses=_teses_conhecidas(conn)), 400
    if not csv_file or not csv_file.filename:
        return render_template_string(_IMPORTAR_LEADS_TEMPLATE, resultado="Selecione um arquivo CSV.", teses=_teses_conhecidas(conn)), 400

    stream = io.StringIO(csv_file.stream.read().decode("utf-8"))
    leads_para_criar = []
    for row in csv.DictReader(stream):
        cnpj = (row.get("cnpj") or "").strip()
        if not cnpj:
            continue
        valor_raw = (row.get("valor_divida") or "").strip()
        leads_para_criar.append(
            {
                "cnpj": cnpj,
                "razao_social": (row.get("razao_social") or "").strip() or None,
                "email": (row.get("email") or "").strip() or None,
                "valor_divida": float(valor_raw) if valor_raw else None,
            }
        )
    count = storage.bulk_create_leads(conn, tese, leads_para_criar) if leads_para_criar else 0
    return render_template_string(
        _IMPORTAR_LEADS_TEMPLATE, resultado=f"{count} lead(s) importado(s) na tese '{tese}'.", teses=_teses_conhecidas(conn)
    )


@bp.route("/admin/campanhas/leads/aparar", methods=["GET", "POST"])
def aparar_leads():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    if request.method == "GET":
        return render_template_string(_APARAR_LEADS_TEMPLATE, teses=_teses_conhecidas(conn))

    tese = (request.form.get("tese") or "").strip()
    manter_raw = (request.form.get("manter") or "").strip()
    if not tese or not manter_raw.isdigit():
        return (
            render_template_string(
                _APARAR_LEADS_TEMPLATE, resultado="Informe a tese e quantos leads manter (número).",
                teses=_teses_conhecidas(conn),
            ),
            400,
        )

    apagados = storage.aparar_leads_por_tese(conn, tese, int(manter_raw))
    return render_template_string(
        _APARAR_LEADS_TEMPLATE,
        resultado=f"{apagados} lead(s) apagado(s) da tese '{tese}' — ficaram os {manter_raw} de maior valor de dívida.",
        teses=_teses_conhecidas(conn),
    )


@bp.get("/admin/campanhas/templates")
def listar_templates():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    teses = _teses_conhecidas(conn)
    tese = request.args.get("tese") or (teses[0] if teses else None)
    if tese is None:
        return jsonify({"error": "nenhuma tese cadastrada ainda"}), 404
    templates = storage.list_templates(conn, tese=tese)
    return render_template_string(_TEMPLATES_TEMPLATE, templates=templates, tese=tese, teses=teses)


@bp.post("/admin/campanhas/templates/<tese>/<tipo>")
def salvar_template(tese: str, tipo: str):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    if tipo not in TIPOS_ENVIO:
        return jsonify({"error": f"tipo de template inválido: {tipo}"}), 404
    conn = _connect()
    checklist = [linha.strip() for linha in request.form.get("checklist", "").splitlines() if linha.strip()]
    storage.set_template(
        conn, tese, tipo,
        assunto=request.form.get("assunto", ""),
        tag=request.form.get("tag", ""),
        headline=request.form.get("headline", ""),
        paragrafo1=request.form.get("paragrafo1", ""),
        paragrafo2=request.form.get("paragrafo2", ""),
        checklist=checklist,
        italico=request.form.get("italico", ""),
        cta_texto=request.form.get("cta_texto", ""),
        link_cta=request.form.get("link_cta", ""),
        rodape_nota=request.form.get("rodape_nota", ""),
    )
    return redirect(f"/admin/campanhas/templates?tese={tese}")


def _sincronizar_engajado_brevo(conn, envio) -> None:
    """Primeiro engajamento (abertura ou clique) daquele envio → sincroniza
    o e-mail do lead com a lista de "engajados" no Brevo, igual o Apps
    Script já faz — silencioso se não tiver `BREVO_API_KEY`/
    `BREVO_ENGAJADOS_LIST_ID` configurados, e nunca trava o rastreio se o
    Brevo falhar (é um efeito colateral, não o propósito do endpoint).
    """
    api_key = os.environ.get("BREVO_API_KEY")
    list_id = os.environ.get("BREVO_ENGAJADOS_LIST_ID")
    if not api_key or not list_id:
        return
    ja_teve_evento = bool(storage.eventos_do_envio(conn, envio.id))
    if ja_teve_evento:
        return
    lead = storage.get_lead(conn, envio.lead_id)
    if not lead or not lead.email:
        return
    try:
        brevo_client.adicionar_contato_lista(lead.email, int(list_id), api_key)
    except BrevoSyncError:
        pass


@bp.get("/track/open/<token>.gif")
def track_open(token: str):
    conn = _connect()
    envio = storage.get_envio_by_token(conn, token)
    if envio is not None:
        _sincronizar_engajado_brevo(conn, envio)
        storage.add_evento(conn, envio.id, "open")
    return Response(tracking.PIXEL_GIF, mimetype="image/gif")


@bp.get("/track/click/<token>")
def track_click(token: str):
    destino = request.args.get("url", "/")
    conn = _connect()
    envio = storage.get_envio_by_token(conn, token)
    if envio is not None:
        _sincronizar_engajado_brevo(conn, envio)
        storage.add_evento(conn, envio.id, "click", url=destino)
    return redirect(destino)


TEMPO_LIMITE_TOTAL_SEGUNDOS = 240
"""O Vercel mata a execução aos 300s de verdade (confirmado em produção
— "Task timed out after 300 seconds"). Fica 60s de folga aqui pra
conexão com o banco, migração de schema, resumo de WhatsApp pra equipe e
relatório semanal — overhead que não dá pra cronometrar com precisão de
fora. Cada etapa abaixo recebe como orçamento o que *sobrou* do tempo até
aqui (não uma fatia fixa adivinhada) — se o banco demorou pra acordar ou
uma API de origem está lenta, as próximas etapas recebem automaticamente
menos tempo, em vez de cada uma assumir sempre a mesma fatia e estourar
o limite de verdade (foi exatamente isso que aconteceu com fatias fixas
de 80+80+100=260s, sem sobrar margem real)."""

TETO_BUSCA_EMAIL_SEGUNDOS = 150
"""A busca de e-mail é o gargalo real hoje: a maioria dos milhares de
leads importados ainda não tem e-mail, e sem e-mail o lead nunca entra na
fila de envio (`leads_pendentes_por_tese` exige `lead.email`). Com os
~3,5s por lead observados em produção, 150s processa ~40 leads por
execução — bem mais que os ~17 de antes — sem risco de estourar o
orçamento total, já que o envio raramente precisa de muito tempo
enquanto esse backlog não esvazia."""

TETO_BUSCA_TELEFONE_SEGUNDOS_RECEITAWS = 30
"""Sem CNPJA_API_TOKEN, cai na ReceitaWS — tem limite de poucas consultas
por minuto e a busca já pára sozinha no primeiro erro de limite (ver
`buscar_telefones_pendentes`), então gastar mais tempo aqui não acha mais
nada, só atrasa o resto."""

TETO_BUSCA_TELEFONE_SEGUNDOS_CNPJA = 100
"""Com CNPJA_API_TOKEN configurado (fonte paga, sem o limite agressivo da
ReceitaWS), telefone deixa de ser um gargalo artificial — mesmo raciocínio
da busca de e-mail: vale gastar mais do orçamento aqui enquanto o backlog
de leads sem telefone não esvazia."""


def _executar_campanha_diaria() -> dict:
    """Corpo de verdade do envio diário da campanha — chamado tanto pelo
    cron (`/cron/campanhas/rodar`, autenticado por `CRON_SECRET`) quanto
    pelo botão manual de admin (`/admin/campanhas/rodar-agora`), já que o
    cron do Vercel depende de agendamento externo que não dá pra verificar
    nem forçar por aqui — o botão manual garante que o envio sempre pode
    ser disparado na hora, autenticado por login de admin.
    """
    conn_check = _connect()
    if storage.envios_pausados(conn_check):
        conn_check.close()
        print("[campanha_diaria] pausado — nenhum e-mail disparado")
        return {"pausado": True}
    conn_check.close()

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    if not all([smtp_host, smtp_port, smtp_username, smtp_password]):
        print("[campanha_diaria] erro: SMTP não configurado")
        return {"error": "SMTP_HOST, SMTP_PORT, SMTP_USERNAME e SMTP_PASSWORD precisam estar configurados"}
    smtp_from = os.environ.get("SMTP_FROM")

    base_url = os.environ.get("PUBLIC_BASE_URL") or request.host_url.rstrip("/")

    inicio = monotonic()
    conn = _connect()

    def tempo_restante() -> float:
        return max(0.0, TEMPO_LIMITE_TOTAL_SEGUNDOS - (monotonic() - inicio))

    exa_api_key = os.environ.get("EXA_API_KEY")
    busca_email = (
        engine.buscar_emails_pendentes(
            conn, exa_api_key, limite=200, orcamento_segundos=min(TETO_BUSCA_EMAIL_SEGUNDOS, tempo_restante())
        )
        if exa_api_key
        else None
    )
    cnpja_token = os.environ.get("CNPJA_API_TOKEN")
    teto_busca_telefone = TETO_BUSCA_TELEFONE_SEGUNDOS_CNPJA if cnpja_token else TETO_BUSCA_TELEFONE_SEGUNDOS_RECEITAWS
    busca_telefone = engine.buscar_telefones_pendentes(
        conn, orcamento_segundos=min(teto_busca_telefone, tempo_restante()), cnpja_token=cnpja_token
    )

    resultado = engine.rodar_diario(
        conn, base_url, smtp_host, int(smtp_port), smtp_username, smtp_password, smtp_from=smtp_from,
        orcamento_segundos=tempo_restante(),
    )
    resultado.pop("leads_enviados")
    resultado["busca_email"] = busca_email
    resultado["busca_telefone"] = busca_telefone

    # O cron roda várias vezes por dia (cada execução processa só o que
    # cabe no orçamento de tempo dela — ver TEMPO_LIMITE_TOTAL_SEGUNDOS).
    # Por isso o resumo de WhatsApp NÃO pode olhar só pros leads enviados
    # *nesta* execução: o telefone de um lead muitas vezes só é achado numa
    # execução seguinte à do e-mail dele, então filtrar por "enviado agora
    # + já tinha telefone" quase nunca dava match (era basicamente isso que
    # fazia o resumo não chegar na prática). `leads_pendentes_whatsapp` é a
    # fila de verdade — todo lead ativo com telefone achado e ainda não
    # contatado, exatamente os mesmos contatos que já receberam e-mail da
    # campanha — e `ja_notificado_hoje`/`marcar_notificado_hoje` garantem
    # que ela só sai uma vez por dia, mesmo com várias execuções do cron.
    whatsapp_equipe_email = os.environ.get("WHATSAPP_EQUIPE_EMAIL")
    resumo_whatsapp_enviado = False
    if whatsapp_equipe_email and not storage.ja_notificado_hoje(conn, "resumo_whatsapp"):
        leads_pendentes = storage.leads_pendentes_whatsapp(conn)
        if leads_pendentes:
            engine.enviar_resumo_whatsapp_equipe(
                conn, leads_pendentes, whatsapp_equipe_email, base_url, smtp_host, int(smtp_port), smtp_username,
                smtp_password, smtp_from=smtp_from,
            )
            storage.marcar_notificado_hoje(conn, "resumo_whatsapp")
            resumo_whatsapp_enviado = True
    resultado["resumo_whatsapp_enviado"] = resumo_whatsapp_enviado

    relatorio_enviado = False
    if date.today().weekday() == 0 and not storage.ja_notificado_hoje(conn, "relatorio_semanal"):  # segunda-feira
        destinatario = os.environ.get("RELATORIO_SEMANAL_EMAIL") or smtp_username
        engine.enviar_relatorio_semanal(conn, destinatario, smtp_host, int(smtp_port), smtp_username, smtp_password, smtp_from=smtp_from)
        storage.marcar_notificado_hoje(conn, "relatorio_semanal")
        relatorio_enviado = True

    resultado["relatorio_semanal_enviado"] = relatorio_enviado
    print(f"[campanha_diaria] resultado={resultado}")
    return resultado


@bp.route("/cron/campanhas/rodar", methods=["GET", "POST"])
def cron_rodar():
    if not cron_authorized():
        return jsonify({"error": "não autorizado — CRON_SECRET ausente ou incorreto"}), 401

    resultado = _executar_campanha_diaria()
    return jsonify(resultado), (500 if "error" in resultado else 200)


@bp.get("/admin/campanhas/rodar-agora")
def rodar_agora_form():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    return render_template_string(_RODAR_AGORA_TEMPLATE)


@bp.post("/admin/campanhas/rodar-agora")
def rodar_agora():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized

    resultado = _executar_campanha_diaria()
    return render_template_string(_RODAR_AGORA_TEMPLATE, resultado=resultado)


@bp.get("/admin/campanhas/diagnostico/envios-hoje")
def diagnostico_envios_hoje():
    """Lista os envios registrados hoje, com CNPJ do lead e eventos de
    rastreio (abertura/clique) associados — pra investigar antes de decidir
    se um envio é "fantasma" (bug: marcado como enviado sem o SMTP
    confirmar) ou se de fato saiu e foi aberto por alguém.
    """
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized

    conn = _connect()
    desde_iso = datetime.combine(date.today(), time.min, tzinfo=timezone.utc).isoformat()
    resultado = []
    for envio in storage.envios_desde(conn, desde_iso):
        lead = storage.get_lead(conn, envio.lead_id)
        eventos = storage.eventos_do_envio(conn, envio.id)
        resultado.append({
            "envio_id": envio.id, "lead_id": envio.lead_id,
            "cnpj": lead.cnpj if lead else None, "tese": lead.tese if lead else None,
            "tipo": envio.tipo, "enviado_em": envio.enviado_em,
            "eventos": [{"tipo": e.tipo, "ocorrido_em": e.ocorrido_em} for e in eventos],
        })
    return jsonify(resultado)


@bp.post("/admin/campanhas/limpar-envios-fantasma-hoje")
def limpar_envios_fantasma_hoje():
    """Ação administrativa única: apaga os envios registrados hoje — usada
    pra limpar a cota diária por tese inflada por um bug já corrigido (ver
    `enviar_para_lead`), em que o lead era marcado como contatado mesmo
    quando o SMTP falhava, sem nenhum e-mail sair. Não faz parte do fluxo
    normal; só existe pra destravar a cota do dia em que o bug foi achado,
    sem precisar esperar a virada natural à meia-noite.
    """
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized

    conn = _connect()
    desde_iso = datetime.combine(date.today(), time.min, tzinfo=timezone.utc).isoformat()
    total_apagado = storage.deletar_envios_desde(conn, desde_iso)
    return jsonify({"envios_apagados": total_apagado, "desde": desde_iso})

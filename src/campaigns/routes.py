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
from datetime import date

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template_string, request

from src.campaigns import engine, storage, tracking
from src.campaigns.models import TIPOS_ENVIO
from src.campaigns.templates import DEFAULT_TEMPLATES
from src.common.webauth import cron_authorized, require_admin

bp = Blueprint("campaigns", __name__)


def _connect():
    db_path = current_app.config.get("CAMPAIGNS_DB_PATH") or storage.DEFAULT_DB_PATH
    return storage.connect(db_path)


def _teses_conhecidas(conn) -> list[str]:
    """União das teses já seedadas no código com qualquer tese nova criada
    só no banco (leads importados ou template salvo pra uma tese ainda não
    prevista em `templates.py`).
    """
    return sorted(set(DEFAULT_TEMPLATES.keys()) | set(storage.list_teses(conn)) | set(storage.list_template_teses(conn)))


_LEADS_TEMPLATE = """
<!doctype html>
<title>Campanha — Leads</title>
<h1>Leads da campanha{% if tese %} — {{ tese }}{% endif %}</h1>
<p><a href="/admin/campanhas/leads/importar">+ Importar leads (CSV)</a> ·
   <a href="/admin/campanhas/templates{% if tese %}?tese={{ tese }}{% endif %}">Editar templates de e-mail</a></p>
<p>Teses:
{% for t in teses %}<a href="/admin/campanhas/leads?tese={{ t }}" style="margin-right:10px;{% if t == tese %}font-weight:bold;{% endif %}">{{ t }}</a>{% endfor %}
<a href="/admin/campanhas/leads">(todas)</a>
</p>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>CNPJ</th><th>Tese</th><th>Razão social</th><th>Valor dívida</th><th>E-mail</th><th>Status</th><th>Envios</th></tr>
{% for lead, envios in leads %}
<tr>
  <td>{{ lead.cnpj }}</td>
  <td>{{ lead.tese }}</td>
  <td>{{ lead.razao_social or "-" }}</td>
  <td>{{ "R$ %.2f"|format(lead.valor_divida) if lead.valor_divida else "-" }}</td>
  <td>{{ lead.email or "(sem e-mail)" }}</td>
  <td>{{ lead.status }}</td>
  <td>{{ envios|join(", ") if envios else "-" }}</td>
</tr>
{% endfor %}
</table>
"""

_IMPORTAR_LEADS_TEMPLATE = """
<!doctype html>
<title>Importar leads</title>
<h1>Importar leads da campanha</h1>
<p><a href="/admin/campanhas/leads">&larr; voltar</a></p>
{% if resultado %}<p>{{ resultado }}</p>{% endif %}
<form method="post" enctype="multipart/form-data">
  <p><label>Tese (planilha)<br>
     <input type="text" name="tese" list="teses-conhecidas" required placeholder="ex: transportadoras_pgfn">
     <datalist id="teses-conhecidas">{% for t in teses %}<option value="{{ t }}">{% endfor %}</datalist>
  </label></p>
  <p><label>CSV (colunas: cnpj,razao_social,email,valor_divida — email e valor_divida são opcionais)<br>
     <input type="file" name="csv" accept=".csv" required></label></p>
  <button type="submit">Importar</button>
</form>
"""

_TEMPLATES_TEMPLATE = """
<!doctype html>
<title>Templates da campanha</title>
<h1>Templates de e-mail — {{ tese }}</h1>
<p><a href="/admin/campanhas/leads?tese={{ tese }}">&larr; voltar pros leads dessa tese</a></p>
<p>Teses:
{% for t in teses %}<a href="/admin/campanhas/templates?tese={{ t }}" style="margin-right:10px;{% if t == tese %}font-weight:bold;{% endif %}">{{ t }}</a>{% endfor %}
</p>
<p>Placeholders disponíveis em assunto/título/parágrafos/frase de urgência: <code>{{ '{{RAZAO_SOCIAL}}' }}</code>, <code>{{ '{{CNPJ}}' }}</code>, <code>{{ '{{VALOR_DIVIDA}}' }}</code></p>
{% for template in templates %}
<hr>
<h2>{{ template.tipo }}</h2>
<form method="post" action="/admin/campanhas/templates/{{ tese }}/{{ template.tipo }}">
  <p><label>Assunto<br><input type="text" name="assunto" style="width:100%" value="{{ template.assunto }}"></label></p>
  <p><label>Tag (selo no topo do e-mail)<br><input type="text" name="tag" style="width:100%" value="{{ template.tag }}"></label></p>
  <p><label>Título<br><textarea name="headline" rows="2" style="width:100%">{{ template.headline }}</textarea></label></p>
  <p><label>Parágrafo 1<br><textarea name="paragrafo1" rows="3" style="width:100%">{{ template.paragrafo1 }}</textarea></label></p>
  <p><label>Parágrafo 2<br><textarea name="paragrafo2" rows="3" style="width:100%">{{ template.paragrafo2 }}</textarea></label></p>
  <p><label>Checklist (um item por linha)<br><textarea name="checklist" rows="4" style="width:100%">{{ template.checklist|join("\n") }}</textarea></label></p>
  <p><label>Frase de urgência (itálico)<br><textarea name="italico" rows="2" style="width:100%">{{ template.italico }}</textarea></label></p>
  <p><label>Texto do botão (CTA)<br><input type="text" name="cta_texto" style="width:100%" value="{{ template.cta_texto }}"></label></p>
  <p><label>Link de destino do CTA<br><input type="text" name="link_cta" style="width:100%" value="{{ template.link_cta }}"></label></p>
  <p><label>Nota de rodapé (itálico, cinza)<br><textarea name="rodape_nota" rows="2" style="width:100%">{{ template.rodape_nota }}</textarea></label></p>
  <button type="submit">Salvar {{ template.tipo }}</button>
</form>
{% endfor %}
"""


@bp.get("/admin/campanhas/leads")
def listar_leads():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    tese = request.args.get("tese") or None
    leads = [
        (lead, [envio.tipo for envio in storage.envios_do_lead(conn, lead.id)])
        for lead in storage.list_leads(conn, tese=tese)
    ]
    return render_template_string(_LEADS_TEMPLATE, leads=leads, tese=tese, teses=_teses_conhecidas(conn))


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
    count = 0
    for row in csv.DictReader(stream):
        cnpj = (row.get("cnpj") or "").strip()
        if not cnpj:
            continue
        valor_raw = (row.get("valor_divida") or "").strip()
        storage.create_lead(
            conn, cnpj, tese, razao_social=(row.get("razao_social") or "").strip() or None,
            email=(row.get("email") or "").strip() or None,
            valor_divida=float(valor_raw) if valor_raw else None,
        )
        count += 1
    return render_template_string(
        _IMPORTAR_LEADS_TEMPLATE, resultado=f"{count} lead(s) importado(s) na tese '{tese}'.", teses=_teses_conhecidas(conn)
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


@bp.get("/track/open/<token>.gif")
def track_open(token: str):
    conn = _connect()
    envio = storage.get_envio_by_token(conn, token)
    if envio is not None:
        storage.add_evento(conn, envio.id, "open")
    return Response(tracking.PIXEL_GIF, mimetype="image/gif")


@bp.get("/track/click/<token>")
def track_click(token: str):
    destino = request.args.get("url", "/")
    conn = _connect()
    envio = storage.get_envio_by_token(conn, token)
    if envio is not None:
        storage.add_evento(conn, envio.id, "click", url=destino)
    return redirect(destino)


@bp.route("/cron/campanhas/rodar", methods=["GET", "POST"])
def cron_rodar():
    if not cron_authorized():
        return jsonify({"error": "não autorizado — CRON_SECRET ausente ou incorreto"}), 401

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    if not all([smtp_host, smtp_port, smtp_username, smtp_password]):
        return jsonify({"error": "SMTP_HOST, SMTP_PORT, SMTP_USERNAME e SMTP_PASSWORD precisam estar configurados"}), 500
    smtp_from = os.environ.get("SMTP_FROM")

    base_url = os.environ.get("PUBLIC_BASE_URL") or request.host_url.rstrip("/")

    conn = _connect()

    exa_api_key = os.environ.get("EXA_API_KEY")
    busca_email = engine.buscar_emails_pendentes(conn, exa_api_key) if exa_api_key else None

    resultado = engine.rodar_diario(conn, base_url, smtp_host, int(smtp_port), smtp_username, smtp_password, smtp_from=smtp_from)
    resultado["busca_email"] = busca_email

    relatorio_enviado = False
    if date.today().weekday() == 0:  # segunda-feira
        destinatario = os.environ.get("RELATORIO_SEMANAL_EMAIL") or smtp_username
        engine.enviar_relatorio_semanal(conn, destinatario, smtp_host, int(smtp_port), smtp_username, smtp_password, smtp_from=smtp_from)
        relatorio_enviado = True

    resultado["relatorio_semanal_enviado"] = relatorio_enviado
    return jsonify(resultado)

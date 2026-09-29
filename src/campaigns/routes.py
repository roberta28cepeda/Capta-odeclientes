"""Rotas web da campanha de prospecção da PGFN: importação de leads,
edição dos templates de e-mail, pixel de abertura/link de clique
rastreável, e o endpoint de cron que dispara os envios do dia.

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
from src.common.webauth import cron_authorized, require_admin

bp = Blueprint("campaigns", __name__)


def _connect():
    db_path = current_app.config.get("CAMPAIGNS_DB_PATH") or storage.DEFAULT_DB_PATH
    return storage.connect(db_path)


_LEADS_TEMPLATE = """
<!doctype html>
<title>Campanha PGFN — Leads</title>
<h1>Leads da campanha PGFN</h1>
<p><a href="/admin/campanhas/leads/importar">+ Importar leads (CSV)</a> ·
   <a href="/admin/campanhas/templates">Editar templates de e-mail</a></p>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>CNPJ</th><th>Razão social</th><th>E-mail</th><th>Status</th><th>Envios</th></tr>
{% for lead, envios in leads %}
<tr>
  <td>{{ lead.cnpj }}</td>
  <td>{{ lead.razao_social or "-" }}</td>
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
<h1>Importar leads da campanha PGFN</h1>
<p><a href="/admin/campanhas/leads">&larr; voltar</a></p>
{% if resultado %}<p>{{ resultado }}</p>{% endif %}
<form method="post" enctype="multipart/form-data">
  <p><label>CSV (colunas: cnpj,razao_social,email — email é opcional)<br>
     <input type="file" name="csv" accept=".csv" required></label></p>
  <button type="submit">Importar</button>
</form>
"""

_TEMPLATES_TEMPLATE = """
<!doctype html>
<title>Templates da campanha</title>
<h1>Templates de e-mail da campanha PGFN</h1>
<p><a href="/admin/campanhas/leads">&larr; voltar</a></p>
<p>Placeholders disponíveis: <code>{razao_social}</code>, <code>{cnpj}</code>, <code>{link_cta}</code></p>
{% for template in templates %}
<h2>{{ template.tipo }}</h2>
<form method="post" action="/admin/campanhas/templates/{{ template.tipo }}">
  <p><label>Assunto<br><input type="text" name="assunto" style="width:100%" value="{{ template.assunto }}"></label></p>
  <p><label>Corpo<br><textarea name="corpo" rows="8" style="width:100%">{{ template.corpo }}</textarea></label></p>
  <p><label>Link de destino (link_cta)<br><input type="text" name="link_cta" style="width:100%" value="{{ template.link_cta }}"></label></p>
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
    leads = [(lead, [envio.tipo for envio in storage.envios_do_lead(conn, lead.id)]) for lead in storage.list_leads(conn)]
    return render_template_string(_LEADS_TEMPLATE, leads=leads)


@bp.route("/admin/campanhas/leads/importar", methods=["GET", "POST"])
def importar_leads():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    if request.method == "GET":
        return render_template_string(_IMPORTAR_LEADS_TEMPLATE)

    csv_file = request.files.get("csv")
    if not csv_file or not csv_file.filename:
        return render_template_string(_IMPORTAR_LEADS_TEMPLATE, resultado="Selecione um arquivo CSV."), 400

    conn = _connect()
    stream = io.StringIO(csv_file.stream.read().decode("utf-8"))
    count = 0
    for row in csv.DictReader(stream):
        cnpj = (row.get("cnpj") or "").strip()
        if not cnpj:
            continue
        storage.create_lead(
            conn, cnpj, razao_social=(row.get("razao_social") or "").strip() or None,
            email=(row.get("email") or "").strip() or None,
        )
        count += 1
    return render_template_string(_IMPORTAR_LEADS_TEMPLATE, resultado=f"{count} lead(s) importado(s).")


@bp.get("/admin/campanhas/templates")
def listar_templates():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    conn = _connect()
    templates = storage.list_templates(conn)
    return render_template_string(_TEMPLATES_TEMPLATE, templates=templates)


@bp.post("/admin/campanhas/templates/<tipo>")
def salvar_template(tipo: str):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    if tipo not in TIPOS_ENVIO:
        return jsonify({"error": f"tipo de template inválido: {tipo}"}), 404
    conn = _connect()
    storage.set_template(
        conn, tipo,
        assunto=request.form.get("assunto", ""),
        corpo=request.form.get("corpo", ""),
        link_cta=request.form.get("link_cta", ""),
    )
    return redirect("/admin/campanhas/templates")


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
    resultado = engine.rodar_diario(conn, base_url, smtp_host, int(smtp_port), smtp_username, smtp_password, smtp_from=smtp_from)

    relatorio_enviado = False
    if date.today().weekday() == 0:  # segunda-feira
        destinatario = os.environ.get("RELATORIO_SEMANAL_EMAIL") or smtp_username
        engine.enviar_relatorio_semanal(conn, destinatario, smtp_host, int(smtp_port), smtp_username, smtp_password, smtp_from=smtp_from)
        relatorio_enviado = True

    resultado["relatorio_semanal_enviado"] = relatorio_enviado
    return jsonify(resultado)

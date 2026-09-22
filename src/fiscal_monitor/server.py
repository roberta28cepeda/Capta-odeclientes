"""Dashboard: lista escritórios (tenants), a carteira de CNPJs de cada um,
os achados fiscais em aberto, e o formulário de pré-análise pública
(só CNPJ, sem procuração/e-CAC).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import date

from flask import Flask, after_this_request, jsonify, render_template_string, request, send_file

from src.fiscal_monitor import monitor, storage
from src.fiscal_monitor.pdf import render_pre_analise_pdf
from src.fiscal_monitor.preanalise import (
    ConsultaCnpjError,
    consultar_cnpj_publico,
    gerar_alertas,
    montar_pre_analise,
    only_digits,
    validar_cnpj,
)

_TENANTS_TEMPLATE = """
<!doctype html>
<title>Monitoramento Fiscal</title>
<h1>Escritórios monitorados</h1>
<p><a href="/pre-analise">Gerar pré-análise pública (só CNPJ, sem procuração) &rarr;</a></p>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>ID</th><th>Nome</th><th>CNPJs na carteira</th></tr>
{% for tenant, count in tenants %}
<tr>
  <td>{{ tenant.id }}</td>
  <td><a href="/tenants/{{ tenant.id }}">{{ tenant.nome }}</a></td>
  <td>{{ count }}</td>
</tr>
{% endfor %}
</table>
"""

_TENANT_DETAIL_TEMPLATE = """
<!doctype html>
<title>{{ tenant.nome }}</title>
<h1>{{ tenant.nome }}</h1>

<h2>Carteira</h2>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>CNPJ</th><th>Razão social</th><th>Regime</th><th></th></tr>
{% for cnpj in cnpjs %}
<tr>
  <td>{{ cnpj.cnpj }}</td>
  <td>{{ cnpj.razao_social or "-" }}</td>
  <td>{{ cnpj.regime_tributario or "-" }}</td>
  <td><a href="/tenants/{{ tenant.id }}/cnpjs/{{ cnpj.id }}/historico">histórico</a></td>
</tr>
{% endfor %}
</table>

{% if sublimite_alerts %}
<h2>Alertas de sublimite do Simples Nacional</h2>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>CNPJ</th><th>Razão social</th><th>Faturamento 12m</th><th>Situação</th></tr>
{% for item in sublimite_alerts %}
<tr>
  <td>{{ item.cnpj.cnpj }}</td>
  <td>{{ item.cnpj.razao_social or "-" }}</td>
  <td>R$ {{ "%.2f"|format(item.faturamento_12m) }}</td>
  <td>{{ item.label }}</td>
</tr>
{% endfor %}
</table>
{% endif %}

<h2>Achados em aberto (nova/recorrente)</h2>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>CNPJ</th><th>Razão social</th><th>Esfera</th><th>Tipo</th><th>Descrição</th><th>Status</th></tr>
{% for cnpj, finding in findings %}
<tr>
  <td>{{ cnpj.cnpj }}</td>
  <td>{{ cnpj.razao_social or "-" }}</td>
  <td>{{ finding.esfera }}</td>
  <td>{{ finding.tipo }}</td>
  <td>{{ finding.descricao }}</td>
  <td>{{ finding.status }}</td>
</tr>
{% endfor %}
</table>
{% if not findings %}<p>Nenhum achado em aberto.</p>{% endif %}
"""

_CNPJ_HISTORY_TEMPLATE = """
<!doctype html>
<title>Histórico — {{ cnpj.cnpj }}</title>
<h1>Histórico — {{ cnpj.razao_social or cnpj.cnpj }} ({{ cnpj.cnpj }})</h1>
<p><a href="/tenants/{{ cnpj.tenant_id }}">&larr; voltar pro escritório</a></p>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>Verificado em</th><th>Esfera</th><th>Tipo</th><th>Descrição</th><th>Status</th></tr>
{% for verificado_em, provider, finding in historico %}
<tr>
  <td>{{ verificado_em }}</td>
  <td>{{ finding.esfera }}</td>
  <td>{{ finding.tipo }}</td>
  <td>{{ finding.descricao }}</td>
  <td>{{ finding.status }}</td>
</tr>
{% endfor %}
</table>
{% if not historico %}<p>Nenhum snapshot importado ainda para este CNPJ.</p>{% endif %}
"""

_PRE_ANALISE_FORM_TEMPLATE = """
<!doctype html>
<title>Pré-Análise Fiscal</title>
<h1>Pré-Análise Fiscal</h1>
<p>Só o CNPJ — sem procuração, sem acesso ao e-CAC. Gera um PDF pra levar na reunião.</p>
{% if erro %}<p style="color:#B23A48"><strong>{{ erro }}</strong></p>{% endif %}
<form method="post" enctype="multipart/form-data">
  <p><label>CNPJ<br><input type="text" name="cnpj" required placeholder="00.000.000/0000-00" value="{{ cnpj or '' }}"></label></p>
  <p><label>Nome do escritório (opcional)<br><input type="text" name="escritorio_nome" value="{{ escritorio_nome or '' }}"></label></p>
  <p><label>Logo (opcional)<br><input type="file" name="logo" accept="image/*"></label></p>
  <button type="submit">Gerar pré-análise (PDF)</button>
</form>
"""


def create_app(db_path: str = storage.DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)

    def _connect() -> sqlite3.Connection:
        return storage.connect(db_path)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/pre-analise", methods=["GET", "POST"])
    def pre_analise():
        if request.method == "GET":
            return render_template_string(_PRE_ANALISE_FORM_TEMPLATE)

        cnpj = (request.form.get("cnpj") or "").strip()
        escritorio_nome = (request.form.get("escritorio_nome") or "").strip() or None

        if not validar_cnpj(cnpj):
            return (
                render_template_string(
                    _PRE_ANALISE_FORM_TEMPLATE,
                    erro="CNPJ inválido — confira os dígitos.",
                    cnpj=cnpj,
                    escritorio_nome=escritorio_nome,
                ),
                400,
            )

        logo_path = None
        logo_file = request.files.get("logo")
        if logo_file and logo_file.filename:
            fd, logo_path = tempfile.mkstemp(suffix=os.path.splitext(logo_file.filename)[1] or ".png")
            os.close(fd)
            logo_file.save(logo_path)

        try:
            dados = consultar_cnpj_publico(cnpj)
        except ConsultaCnpjError as exc:
            if logo_path and os.path.exists(logo_path):
                os.remove(logo_path)
            return (
                render_template_string(
                    _PRE_ANALISE_FORM_TEMPLATE, erro=str(exc), cnpj=cnpj, escritorio_nome=escritorio_nome
                ),
                400,
            )

        analise = montar_pre_analise(dados)
        alertas = gerar_alertas(analise)

        fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        render_pre_analise_pdf(analise, alertas, pdf_path, escritorio_nome=escritorio_nome, logo_path=logo_path)

        @after_this_request
        def _cleanup(response):
            for path in (pdf_path, logo_path):
                if path and os.path.exists(path):
                    os.remove(path)
            return response

        return send_file(
            pdf_path, as_attachment=True, download_name=f"pre_analise_{only_digits(cnpj)}.pdf", mimetype="application/pdf"
        )

    @app.get("/tenants")
    def tenants_list():
        conn = _connect()
        tenants = storage.list_tenants(conn)
        rows = [(tenant, len(storage.list_cnpjs(conn, tenant.id))) for tenant in tenants]
        conn.close()
        return render_template_string(_TENANTS_TEMPLATE, tenants=rows)

    @app.get("/tenants/<int:tenant_id>")
    def tenant_detail(tenant_id: int):
        conn = _connect()
        tenant = storage.get_tenant(conn, tenant_id)
        if tenant is None:
            conn.close()
            return jsonify({"error": "tenant não encontrado"}), 404
        cnpjs = storage.list_cnpjs(conn, tenant_id)
        findings = _flatten_open_findings(storage.findings_by_cnpj_for_tenant(conn, tenant_id))
        referencia = request.args.get("referencia") or date.today().strftime("%Y-%m")
        sublimite_alerts = monitor.check_sublimite_simples(conn, tenant_id, referencia)
        conn.close()
        return render_template_string(
            _TENANT_DETAIL_TEMPLATE,
            tenant=tenant,
            cnpjs=cnpjs,
            findings=findings,
            sublimite_alerts=sublimite_alerts,
        )

    @app.get("/tenants/<int:tenant_id>/cnpjs/<int:cnpj_id>/historico")
    def cnpj_history(tenant_id: int, cnpj_id: int):
        conn = _connect()
        cnpj = storage.get_cnpj(conn, cnpj_id)
        if cnpj is None or cnpj.tenant_id != tenant_id:
            conn.close()
            return jsonify({"error": "CNPJ não encontrado nesse tenant"}), 404
        historico = storage.all_findings_for_cnpj(conn, cnpj_id)
        conn.close()
        return render_template_string(_CNPJ_HISTORY_TEMPLATE, cnpj=cnpj, historico=historico)

    @app.get("/tenants/<int:tenant_id>/findings.json")
    def tenant_findings_json(tenant_id: int):
        conn = _connect()
        tenant = storage.get_tenant(conn, tenant_id)
        if tenant is None:
            conn.close()
            return jsonify({"error": "tenant não encontrado"}), 404
        findings = _flatten_open_findings(storage.findings_by_cnpj_for_tenant(conn, tenant_id))
        conn.close()
        return jsonify(
            [
                {
                    "cnpj": cnpj.cnpj,
                    "razao_social": cnpj.razao_social,
                    "esfera": finding.esfera,
                    "tipo": finding.tipo,
                    "descricao": finding.descricao,
                    "valor": finding.valor,
                    "vencimento": finding.vencimento,
                    "status": finding.status,
                }
                for cnpj, finding in findings
            ]
        )

    return app


def _flatten_open_findings(
    findings_by_cnpj: list[tuple[storage.Cnpj, list[storage.Finding]]],
) -> list[tuple[storage.Cnpj, storage.Finding]]:
    return [(cnpj, finding) for cnpj, findings in findings_by_cnpj for finding in findings]

"""Dashboard somente-leitura: lista escritórios (tenants), a carteira de
CNPJs de cada um e os achados fiscais em aberto.
"""

from __future__ import annotations

import sqlite3

from flask import Flask, jsonify, render_template_string

from src.fiscal_monitor import storage

_TENANTS_TEMPLATE = """
<!doctype html>
<title>Monitoramento Fiscal</title>
<h1>Escritórios monitorados</h1>
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
<p>Achados em aberto (nova/recorrente):</p>
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


def create_app(db_path: str = storage.DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)

    def _connect() -> sqlite3.Connection:
        return storage.connect(db_path)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

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
        findings = _flatten_open_findings(storage.findings_by_cnpj_for_tenant(conn, tenant_id))
        conn.close()
        return render_template_string(_TENANT_DETAIL_TEMPLATE, tenant=tenant, findings=findings)

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

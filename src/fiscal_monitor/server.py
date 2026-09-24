"""Dashboard: lista escritórios (tenants), a carteira de CNPJs de cada um,
os achados fiscais em aberto, e o formulário de pré-análise pública
(só CNPJ, sem procuração/e-CAC).
"""

from __future__ import annotations

import io
import os
import secrets
import sqlite3
import tempfile
from datetime import date

from flask import Flask, Response, after_this_request, jsonify, render_template_string, request, send_file

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
from src.fiscal_monitor.providers import import_portfolio_csv

_TENANTS_TEMPLATE = """
<!doctype html>
<title>Monitoramento Fiscal</title>
<h1>Escritórios monitorados</h1>
<p><a href="/admin/tenants/novo">+ Cadastrar novo escritório</a></p>
<p><a href="/pre-analise">Gerar pré-análise pública (só CNPJ, sem procuração) &rarr;</a></p>
<p style="font-size:0.9em"><a href="/privacidade">Política de Privacidade e LGPD</a></p>
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
  <td><a href="/tenants/{{ tenant.id }}/cnpjs/{{ cnpj.id }}/historico?token={{ request.args.get('token', '') }}">histórico</a></td>
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
<p><a href="/tenants/{{ cnpj.tenant_id }}?token={{ request.args.get('token', '') }}">&larr; voltar pro escritório</a></p>
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

_NOVO_TENANT_TEMPLATE = """
<!doctype html>
<title>Cadastrar escritório</title>
<h1>Cadastrar novo escritório</h1>
<p><a href="/tenants">&larr; voltar pra lista</a></p>
{% if erro %}<p style="color:#B23A48"><strong>{{ erro }}</strong></p>{% endif %}
<form method="post" enctype="multipart/form-data">
  <p><label>Nome do escritório<br><input type="text" name="nome" required value="{{ nome or '' }}"></label></p>
  <p><label>WhatsApp de contato (opcional)<br><input type="text" name="whatsapp" placeholder="5511999999999" value="{{ whatsapp or '' }}"></label></p>
  <p><label>E-mail de contato (opcional)<br><input type="email" name="email" value="{{ email or '' }}"></label></p>
  <p><label>Plano (opcional)<br><input type="text" name="plano" value="{{ plano or '' }}"></label></p>
  <p><label>Carteira de CNPJs — CSV (opcional, pode importar depois)<br>
     <input type="file" name="carteira" accept=".csv"><br>
     <small>colunas: cnpj,razao_social,nome_fantasia,regime_tributario</small></label></p>
  <button type="submit">Cadastrar</button>
</form>
"""

_TENANT_CRIADO_TEMPLATE = """
<!doctype html>
<title>Escritório cadastrado</title>
<h1>Escritório cadastrado: {{ tenant.nome }}</h1>
<p>Link de acesso pra esse escritório (guarde/envie com cuidado — dá acesso à carteira dele):</p>
<p><code>{{ link }}</code></p>
{% if resultado_carteira %}<p>Carteira: {{ resultado_carteira }}</p>{% endif %}
<p><a href="/tenants">&larr; voltar pra lista</a> · <a href="{{ link }}">ver a carteira deste escritório</a></p>
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
<p style="margin-top:2rem;font-size:0.9em"><a href="/privacidade">Política de Privacidade e LGPD</a></p>
"""

_PRIVACIDADE_TEMPLATE = """
<!doctype html>
<title>Política de Privacidade</title>
<h1>Política de Privacidade e Proteção de Dados (LGPD)</h1>
<p><em>Última atualização: {{ hoje }}</em></p>

<h2>1. Quem é o responsável pelos dados</h2>
<p>
  <strong>LEAO CONSULTORIA ESTRATEGICA LTDA</strong> (Leactis),
  CNPJ 63.586.147/0001-25, é a controladora dos dados tratados nesta
  plataforma de monitoramento fiscal, nos termos da Lei Geral de Proteção
  de Dados (Lei nº 13.709/2018 — LGPD).
</p>

<h2>2. Quais dados coletamos, e de onde</h2>
<p><strong>Pré-análise pública</strong> (página <code>/pre-analise</code>):
o CNPJ informado é consultado em tempo real na
<a href="https://brasilapi.com.br" target="_blank" rel="noopener">BrasilAPI</a>,
um serviço de terceiros que espelha dados públicos da Receita Federal
(situação cadastral, natureza jurídica, enquadramento no Simples
Nacional/MEI). Essa consulta <strong>não é armazenada</strong> em nosso
banco de dados — o PDF é gerado na hora e a busca não fica salva.</p>
<p><strong>Carteira de clientes do escritório contábil</strong> (área
autenticada): CNPJ, razão social, regime tributário, contato de WhatsApp
do escritório, e os achados fiscais (pendências, multas, DAS, CNDs,
parcelamentos) que o próprio escritório importa manualmente. Esses dados
ficam armazenados em nosso banco enquanto o escritório for cliente.</p>

<h2>3. Com quem compartilhamos</h2>
<ul>
  <li><strong>BrasilAPI</strong> — recebe o CNPJ digitado na pré-análise pública, pra devolver o dado cadastral público correspondente.</li>
  <li><strong>Meta (WhatsApp Cloud API)</strong> — usada só se o escritório optar por receber alertas fiscais por WhatsApp; recebe o número de contato cadastrado e o texto do alerta.</li>
</ul>
<p>Não vendemos nem compartilhamos dados com terceiros para fins de publicidade.</p>

<h2>4. Por quanto tempo guardamos</h2>
<p>Os dados da carteira de clientes ficam armazenados enquanto o
escritório contábil for cliente da Leactis. Não há exclusão automática
por prazo — a exclusão acontece mediante solicitação (veja abaixo) ou ao
fim da relação contratual.</p>

<h2>5. Segurança</h2>
<p>A conexão com o site é criptografada (HTTPS). O acesso à carteira de
cada escritório é protegido por um token de acesso individual; a listagem
administrativa de todos os escritórios exige autenticação própria. Ainda
assim, nenhum sistema é 100% livre de risco — se você suspeitar de
qualquer uso indevido, entre em contato imediatamente pelo canal abaixo.</p>

<h2>6. Seus direitos</h2>
<p>Como titular dos dados, você pode solicitar a qualquer momento:
confirmação de que tratamos seus dados, acesso, correção, exclusão,
portabilidade, ou informação sobre com quem compartilhamos seus dados.</p>

<h2>7. Contato</h2>
<p>Para exercer esses direitos ou tirar dúvidas sobre este tratamento de
dados, escreva para <a href="mailto:contato@leactis.com.br">contato@leactis.com.br</a>.</p>
"""


def _admin_authenticated() -> bool:
    """`/tenants` (lista com todos os escritórios) só é visível pra quem
    conhece a senha de administrador — sem ADMIN_PASSWORD configurada, o
    acesso é negado por padrão (não liberado).
    """
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_password:
        return False
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    auth = request.authorization
    if not auth:
        return False
    return secrets.compare_digest(auth.username or "", admin_username) and secrets.compare_digest(
        auth.password or "", admin_password
    )


def _require_admin() -> Response | None:
    if _admin_authenticated():
        return None
    return Response(
        "Autenticação necessária.", 401, {"WWW-Authenticate": 'Basic realm="Monitoramento Fiscal"'}
    )


def _tenant_authorized(tenant: storage.Tenant) -> bool:
    """Acesso à carteira de um tenant: senha de admin, ou o token de acesso
    daquele tenant específico (`?token=...`) — cada escritório só entra na
    própria carteira, não na dos outros.
    """
    if _admin_authenticated():
        return True
    token = request.args.get("token", "")
    return bool(tenant.acesso_token) and secrets.compare_digest(token, tenant.acesso_token)


def create_app(db_path: str = storage.DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)

    def _connect() -> sqlite3.Connection:
        return storage.connect(db_path)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/privacidade")
    def privacidade():
        return render_template_string(_PRIVACIDADE_TEMPLATE, hoje=date.today().strftime("%d/%m/%Y"))

    @app.route("/admin/tenants/novo", methods=["GET", "POST"])
    def novo_tenant():
        unauthorized = _require_admin()
        if unauthorized:
            return unauthorized

        if request.method == "GET":
            return render_template_string(_NOVO_TENANT_TEMPLATE)

        nome = (request.form.get("nome") or "").strip()
        whatsapp = (request.form.get("whatsapp") or "").strip() or None
        email = (request.form.get("email") or "").strip() or None
        plano = (request.form.get("plano") or "").strip() or None

        if not nome:
            return (
                render_template_string(
                    _NOVO_TENANT_TEMPLATE, erro="Nome do escritório é obrigatório.",
                    whatsapp=whatsapp, email=email, plano=plano,
                ),
                400,
            )

        conn = _connect()
        tenant = storage.create_tenant(conn, nome, contato_whatsapp=whatsapp, plano=plano, contato_email=email)

        resultado_carteira = None
        carteira_file = request.files.get("carteira")
        if carteira_file and carteira_file.filename:
            stream = io.StringIO(carteira_file.stream.read().decode("utf-8"))
            count, erro_carteira = import_portfolio_csv(conn, tenant.id, stream)
            resultado_carteira = erro_carteira or f"{count} CNPJ(s) importado(s)."
        conn.close()

        link = f"/tenants/{tenant.id}?token={tenant.acesso_token}"
        return render_template_string(
            _TENANT_CRIADO_TEMPLATE, tenant=tenant, link=link, resultado_carteira=resultado_carteira
        )

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
        unauthorized = _require_admin()
        if unauthorized:
            return unauthorized
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
        if not _tenant_authorized(tenant):
            conn.close()
            return jsonify({"error": "acesso não autorizado — informe ?token=... ou faça login de admin"}), 403
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
        tenant = storage.get_tenant(conn, tenant_id)
        cnpj = storage.get_cnpj(conn, cnpj_id)
        if tenant is None or cnpj is None or cnpj.tenant_id != tenant_id:
            conn.close()
            return jsonify({"error": "CNPJ não encontrado nesse tenant"}), 404
        if not _tenant_authorized(tenant):
            conn.close()
            return jsonify({"error": "acesso não autorizado — informe ?token=... ou faça login de admin"}), 403
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
        if not _tenant_authorized(tenant):
            conn.close()
            return jsonify({"error": "acesso não autorizado — informe ?token=... ou faça login de admin"}), 403
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

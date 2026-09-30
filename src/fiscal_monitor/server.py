"""Dashboard: lista escritórios (tenants), a carteira de CNPJs de cada um,
os achados fiscais em aberto, e o formulário de pré-análise (só CNPJ, sem
procuração/e-CAC) — restrito a login de admin.
"""

from __future__ import annotations

import io
import os
import secrets
import sqlite3
import tempfile
from datetime import date

from flask import Flask, Response, after_this_request, jsonify, render_template_string, request, send_file

from src.common.webauth import admin_authenticated, cron_authorized, require_admin
from src.fiscal_monitor import monitor, storage
from src.fiscal_monitor.cron import check_all_tenants
from src.fiscal_monitor.infosimples import (
    ConsultaDebitosError,
    consultar_cnd_federal,
    consultar_lista_devedores,
    gerar_alertas_fiscais,
    montar_divida_ativa,
    montar_situacao_fiscal,
)
from src.fiscal_monitor.pdf import render_pre_analise_pdf
from src.fiscal_monitor.preanalise import (
    CartaoCnpjError,
    ConsultaCnpjError,
    buscar_cartao_cnpj_pdf,
    consultar_cnpj_cnpja,
    consultar_cnpj_publico,
    gerar_alertas,
    montar_pre_analise,
    montar_pre_analise_cnpja,
    only_digits,
    validar_cnpj,
)
from src.fiscal_monitor.providers import import_portfolio_csv
from werkzeug.security import generate_password_hash

_TENANTS_TEMPLATE = """
<!doctype html>
<title>Monitoramento Fiscal</title>
<h1>Escritórios monitorados</h1>
<p><a href="/admin/tenants/novo">+ Cadastrar novo escritório</a></p>
<p><a href="/pre-analise">Gerar pré-análise (só CNPJ, sem procuração) &rarr;</a></p>
<p><a href="/admin/campanhas/leads">Campanhas de prospecção (leads, templates por tese) &rarr;</a></p>
<p><a href="/admin/usuarios">Gerenciar usuários da equipe &rarr;</a></p>
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

_USUARIOS_TEMPLATE = """
<!doctype html>
<title>Usuários da equipe</title>
<h1>Usuários da equipe</h1>
<p><a href="/tenants">&larr; voltar</a></p>
{% if erro %}<p style="color:#B23A48"><strong>{{ erro }}</strong></p>{% endif %}
{% if sucesso %}<p style="color:#1a7a3c"><strong>{{ sucesso }}</strong></p>{% endif %}

<h2>Cadastrar novo acesso</h2>
<form method="post">
  <p><label>Nome<br><input type="text" name="nome" value="{{ nome or '' }}"></label></p>
  <p><label>Usuário (login)<br><input type="text" name="username" required value="{{ username or '' }}"></label></p>
  <p><label>Senha<br><input type="password" name="password" required minlength="8"></label></p>
  <button type="submit">Cadastrar</button>
</form>

<h2>Acessos cadastrados</h2>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>Usuário</th><th>Nome</th><th>Criado em</th><th>Status</th><th></th></tr>
{% for usuario in usuarios %}
<tr>
  <td>{{ usuario.username }}</td>
  <td>{{ usuario.nome or "-" }}</td>
  <td>{{ usuario.criado_em[:10] }}</td>
  <td>{{ "ativo" if usuario.ativo else "desativado" }}</td>
  <td>
    <form method="post" action="/admin/usuarios/{{ usuario.id }}/alternar-ativo" style="display:inline">
      <button type="submit">{{ "Desativar" if usuario.ativo else "Reativar" }}</button>
    </form>
  </td>
</tr>
{% endfor %}
</table>
{% if not usuarios %}<p>Nenhum acesso individual cadastrado ainda — só o usuário mestre (ADMIN_USERNAME).</p>{% endif %}
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
{% if cnpja_disponivel %}
<form method="get" action="/pre-analise/cartao-cnpj" style="margin-top:1.5rem;padding-top:1rem;border-top:1px solid #ccc">
  <p><label>Baixar Cartão CNPJ oficial (PDF direto da Receita Federal, via CNPJá)<br>
     <input type="text" name="cnpj" required placeholder="00.000.000/0000-00"></label></p>
  <button type="submit">Baixar Cartão CNPJ</button>
</form>
{% endif %}
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
<p><strong>Pré-análise</strong> (página <code>/pre-analise</code>, restrita a
login de administrador): o CNPJ informado é consultado em tempo real na
<a href="https://brasilapi.com.br" target="_blank" rel="noopener">BrasilAPI</a>
ou na <a href="https://cnpja.com" target="_blank" rel="noopener">CNPJá</a>
(conforme a configuração), serviços de terceiros que espelham dados
públicos da Receita Federal (situação cadastral, natureza jurídica,
enquadramento no Simples Nacional/MEI, quadro de sócios) e, quando
solicitado, o Cartão CNPJ oficial emitido pela própria Receita Federal.
Essa consulta <strong>não é armazenada</strong> em nosso banco de dados —
o PDF é gerado na hora e a busca não fica salva.</p>
<p><strong>Carteira de clientes do escritório contábil</strong> (área
autenticada): CNPJ, razão social, regime tributário, contato de WhatsApp
do escritório, e os achados fiscais (pendências, multas, DAS, CNDs,
parcelamentos) que o próprio escritório importa manualmente. Esses dados
ficam armazenados em nosso banco enquanto o escritório for cliente.</p>

<h2>3. Com quem compartilhamos</h2>
<ul>
  <li><strong>BrasilAPI / CNPJá</strong> — recebem o CNPJ digitado na pré-análise, pra devolver o dado cadastral público correspondente (e, na CNPJá, o Cartão CNPJ oficial quando solicitado).</li>
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


def _tenant_authorized(tenant: storage.Tenant) -> bool:
    """Acesso à carteira de um tenant: senha de admin, ou o token de acesso
    daquele tenant específico (`?token=...`) — cada escritório só entra na
    própria carteira, não na dos outros.
    """
    if admin_authenticated():
        return True
    token = request.args.get("token", "")
    return bool(tenant.acesso_token) and secrets.compare_digest(token, tenant.acesso_token)


def create_app(
    db_path: str = storage.DEFAULT_DB_PATH,
    campaigns_db_path: str | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config["CAMPAIGNS_DB_PATH"] = campaigns_db_path
    app.config["DB_PATH"] = db_path

    def _connect() -> sqlite3.Connection:
        return storage.connect(db_path)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/cron/check-all", methods=["GET", "POST"])
    def cron_check_all():
        if not cron_authorized():
            return jsonify({"error": "não autorizado — CRON_SECRET ausente ou incorreto"}), 401
        conn = _connect()
        resultados = check_all_tenants(conn)
        conn.close()
        return jsonify({"tenants_verificados": len(resultados), "resultados": resultados})

    @app.get("/privacidade")
    def privacidade():
        return render_template_string(_PRIVACIDADE_TEMPLATE, hoje=date.today().strftime("%d/%m/%Y"))

    @app.route("/admin/tenants/novo", methods=["GET", "POST"])
    def novo_tenant():
        unauthorized = require_admin()
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

    @app.route("/admin/usuarios", methods=["GET", "POST"])
    def admin_usuarios():
        unauthorized = require_admin()
        if unauthorized:
            return unauthorized

        conn = _connect()

        if request.method == "GET":
            usuarios = storage.list_admin_users(conn)
            conn.close()
            return render_template_string(_USUARIOS_TEMPLATE, usuarios=usuarios)

        nome = (request.form.get("nome") or "").strip() or None
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if not username or len(password) < 8:
            usuarios = storage.list_admin_users(conn)
            conn.close()
            return (
                render_template_string(
                    _USUARIOS_TEMPLATE,
                    usuarios=usuarios,
                    erro="Usuário é obrigatório e a senha precisa ter pelo menos 8 caracteres.",
                    nome=nome,
                    username=username,
                ),
                400,
            )

        if storage.get_admin_user_by_username(conn, username) is not None:
            usuarios = storage.list_admin_users(conn)
            conn.close()
            return (
                render_template_string(
                    _USUARIOS_TEMPLATE, usuarios=usuarios, erro=f"Já existe um usuário '{username}'.", nome=nome
                ),
                400,
            )

        storage.create_admin_user(conn, username, generate_password_hash(password), nome=nome)
        usuarios = storage.list_admin_users(conn)
        conn.close()
        return render_template_string(_USUARIOS_TEMPLATE, usuarios=usuarios, sucesso=f"Usuário '{username}' cadastrado.")

    @app.post("/admin/usuarios/<int:user_id>/alternar-ativo")
    def alternar_ativo_usuario(user_id: int):
        unauthorized = require_admin()
        if unauthorized:
            return unauthorized

        conn = _connect()
        usuarios = storage.list_admin_users(conn)
        alvo = next((u for u in usuarios if u.id == user_id), None)
        if alvo is None:
            conn.close()
            return jsonify({"error": "usuário não encontrado"}), 404

        storage.set_admin_user_ativo(conn, user_id, not alvo.ativo)
        usuarios = storage.list_admin_users(conn)
        conn.close()
        return render_template_string(_USUARIOS_TEMPLATE, usuarios=usuarios)

    @app.route("/pre-analise", methods=["GET", "POST"])
    def pre_analise():
        unauthorized = require_admin()
        if unauthorized:
            return unauthorized

        cnpja_token = os.environ.get("CNPJA_API_TOKEN")

        if request.method == "GET":
            return render_template_string(_PRE_ANALISE_FORM_TEMPLATE, cnpja_disponivel=bool(cnpja_token))

        cnpj = (request.form.get("cnpj") or "").strip()
        escritorio_nome = (request.form.get("escritorio_nome") or "").strip() or None

        if not validar_cnpj(cnpj):
            return (
                render_template_string(
                    _PRE_ANALISE_FORM_TEMPLATE,
                    erro="CNPJ inválido — confira os dígitos.",
                    cnpj=cnpj,
                    escritorio_nome=escritorio_nome,
                    cnpja_disponivel=bool(cnpja_token),
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
            if cnpja_token:
                dados = consultar_cnpj_cnpja(cnpj, cnpja_token)
                analise = montar_pre_analise_cnpja(dados)
            else:
                dados = consultar_cnpj_publico(cnpj)
                analise = montar_pre_analise(dados)
        except ConsultaCnpjError as exc:
            if logo_path and os.path.exists(logo_path):
                os.remove(logo_path)
            return (
                render_template_string(
                    _PRE_ANALISE_FORM_TEMPLATE,
                    erro=str(exc),
                    cnpj=cnpj,
                    escritorio_nome=escritorio_nome,
                    cnpja_disponivel=bool(cnpja_token),
                ),
                400,
            )

        alertas = gerar_alertas(analise)

        situacao_fiscal = None
        divida_ativa = None
        infosimples_token = os.environ.get("INFOSIMPLES_API_TOKEN")
        if infosimples_token:
            try:
                situacao_fiscal = montar_situacao_fiscal(consultar_cnd_federal(cnpj, infosimples_token))
                divida_ativa = montar_divida_ativa(consultar_lista_devedores(cnpj, infosimples_token))
                alertas += gerar_alertas_fiscais(situacao_fiscal, divida_ativa)
            except ConsultaDebitosError as exc:
                alertas.append(f"Não foi possível consultar situação fiscal/dívida ativa (PGFN): {exc}")

        fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        render_pre_analise_pdf(
            analise,
            alertas,
            pdf_path,
            escritorio_nome=escritorio_nome,
            logo_path=logo_path,
            situacao_fiscal=situacao_fiscal,
            divida_ativa=divida_ativa,
        )

        @after_this_request
        def _cleanup(response):
            for path in (pdf_path, logo_path):
                if path and os.path.exists(path):
                    os.remove(path)
            return response

        return send_file(
            pdf_path, as_attachment=True, download_name=f"pre_analise_{only_digits(cnpj)}.pdf", mimetype="application/pdf"
        )

    @app.get("/pre-analise/cartao-cnpj")
    def cartao_cnpj():
        unauthorized = require_admin()
        if unauthorized:
            return unauthorized

        cnpja_token = os.environ.get("CNPJA_API_TOKEN")
        if not cnpja_token:
            return jsonify({"error": "CNPJA_API_TOKEN não configurado — Cartão CNPJ oficial indisponível."}), 500

        cnpj = (request.args.get("cnpj") or "").strip()
        if not validar_cnpj(cnpj):
            return jsonify({"error": "CNPJ inválido — confira os dígitos."}), 400

        try:
            pdf_bytes = buscar_cartao_cnpj_pdf(cnpj, cnpja_token)
        except CartaoCnpjError as exc:
            return jsonify({"error": str(exc)}), 502

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=cartao_cnpj_{only_digits(cnpj)}.pdf"},
        )

    @app.get("/tenants")
    def tenants_list():
        unauthorized = require_admin()
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

    from src.campaigns.routes import bp as campaigns_bp

    app.register_blueprint(campaigns_bp)

    return app


def _flatten_open_findings(
    findings_by_cnpj: list[tuple[storage.Cnpj, list[storage.Finding]]],
) -> list[tuple[storage.Cnpj, storage.Finding]]:
    return [(cnpj, finding) for cnpj, findings in findings_by_cnpj for finding in findings]

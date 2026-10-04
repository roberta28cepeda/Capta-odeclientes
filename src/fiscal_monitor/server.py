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

from flask import Flask, Response, after_this_request, jsonify, redirect, render_template_string, request, send_file

from src.common.web_styles import page
from src.common.webauth import admin_authenticated, cron_authorized, require_admin
from src.fiscal_monitor import monitor, storage
from src.fiscal_monitor.cron import check_all_tenants, run_infosimples_semanal
from src.fiscal_monitor.infosimples import (
    ConsultaDebitosError,
    consultar_cnd_federal,
    consultar_cndt_trabalhista,
    consultar_lista_devedores,
    consultar_regularidade_fgts,
    enriquecer_com_dados_abertos,
    gerar_alertas_fiscais,
    montar_divida_ativa,
    montar_situacao_cndt,
    montar_situacao_fgts,
    montar_situacao_fiscal,
)
from src.fiscal_monitor.pgfn_dados_abertos import ArquivoDadosAbertosError, importar_arquivo
from src.fiscal_monitor.pdf import render_dossie_fiscal_pdf, render_pre_analise_pdf
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
from src.fiscal_monitor.models import ORGAOS_CERTIDAO
from src.fiscal_monitor.providers import import_portfolio_csv
from src.fiscal_monitor.reforma import FATURAMENTO_MAXIMO, FATURAMENTO_MINIMO, simular
from src.fiscal_monitor.risco import calcular_score_risco, certidao_status, orgaos_exigidos
from werkzeug.security import generate_password_hash

from src.campaigns import storage as campaigns_storage

_TENANTS_TEMPLATE = page("Monitoramento Fiscal", """
<h1>Escritórios monitorados</h1>
<nav class="nav">
  <a href="/admin/tenants/novo">+ Cadastrar novo escritório</a>
  <a href="/pre-analise">Gerar pré-análise (só CNPJ, sem procuração)</a>
  <a href="/admin/campanhas/leads">Campanhas de prospecção</a>
  <a href="/admin/usuarios">Usuários da equipe</a>
  <a href="/reforma-tributaria">Simulador da Reforma Tributária</a>
  <a href="/admin/pgfn-dados-abertos">Dados Abertos da PGFN</a>
  <a href="/admin/check-all/rodar-agora">Rodar checagem da carteira agora</a>
  <a href="/admin/status">Status do sistema</a>
</nav>
<table>
<tr><th>ID</th><th>Nome</th><th>CNPJs na carteira</th></tr>
{% for tenant, count in tenants %}
<tr>
  <td>{{ tenant.id }}</td>
  <td><a href="/tenants/{{ tenant.id }}">{{ tenant.nome }}</a></td>
  <td>{{ count }}</td>
</tr>
{% endfor %}
</table>
<p><small><a href="/privacidade">Política de Privacidade e LGPD</a></small></p>
""")

_CHECK_ALL_RODAR_AGORA_TEMPLATE = page("Rodar checagem da carteira", """
<p><a href="/tenants">&larr; voltar</a></p>
<h1>Rodar checagem da carteira agora</h1>
<p>Roda o motor de alerta (achados vencendo, sublimite do Simples) de todos os escritórios e dispara
WhatsApp/e-mail pra quem tem contato configurado — o mesmo que o cron diário faz.</p>
<p>A busca automática via InfoSimples (CND, dívida ativa, FGTS, CNDT) só roda às segundas-feiras por
padrão, pra controlar o custo. Marque a opção abaixo pra forçar fora do dia normal.</p>
<form method="post" class="card">
  <label><input type="checkbox" name="forcar_infosimples"> Forçar busca InfoSimples agora (mesmo não sendo segunda)</label>
  <button type="submit">Rodar agora</button>
</form>

{% if resultado %}
<h2>Resultado</h2>
<table>
<tr><th>Escritórios verificados</th><td>{{ resultado.tenants_verificados }}</td></tr>
<tr><th>Busca InfoSimples rodou</th><td>{{ "sim" if resultado.infosimples_semanal_rodou else "não" }}</td></tr>
</table>
{% if resultado.infosimples_semanal_resultado %}
<h3>Achados da busca InfoSimples</h3>
<table>
<tr><th>CNPJ</th><th>Achados</th><th>Erro</th></tr>
{% for r in resultado.infosimples_semanal_resultado %}
<tr><td>{{ r.cnpj }}</td><td>{{ r.achados }}</td><td>{{ r.erro or "-" }}</td></tr>
{% endfor %}
</table>
{% endif %}
<h3>Alertas por escritório</h3>
<table>
<tr><th>Escritório</th><th>Alertas</th><th>Sublimite</th><th>WhatsApp</th><th>E-mail</th><th>Erro</th></tr>
{% for r in resultado.resultados %}
<tr>
  <td>{{ r.nome }}</td>
  <td>{{ r.alertas }}</td>
  <td>{{ r.sublimite_alertas }}</td>
  <td>{{ "sim" if r.enviado_whatsapp else "não" }}</td>
  <td>{{ "sim" if r.enviado_email else "não" }}</td>
  <td>{{ r.erro or "-" }}</td>
</tr>
{% endfor %}
</table>
{% endif %}
""")

_TENANT_DETAIL_TEMPLATE = page("{{ tenant.nome }}", """
<p><a href="/tenants">&larr; voltar</a></p>
<h1>{{ tenant.nome }}</h1>
<nav class="nav">
  <a href="/reforma-tributaria">Simulador da Reforma Tributária</a>
</nav>

<h2>Carteira</h2>
<table>
<tr><th>CNPJ</th><th>Razão social</th><th>UF</th><th>Regime</th><th>Risco</th><th></th></tr>
{% for cnpj in cnpjs %}
<tr>
  <td>{{ cnpj.cnpj }}</td>
  <td>{{ cnpj.razao_social or "-" }}</td>
  <td>{{ cnpj.uf or "-" }}</td>
  <td>{{ cnpj.regime_tributario or "-" }}</td>
  <td>{{ scores[cnpj.id].score }} ({{ scores[cnpj.id].urgencia }})</td>
  <td>
    <a href="/tenants/{{ tenant.id }}/cnpjs/{{ cnpj.id }}/historico?token={{ request.args.get('token', '') }}">histórico</a> ·
    <a href="/tenants/{{ tenant.id }}/cnpjs/{{ cnpj.id }}/obrigacoes?token={{ request.args.get('token', '') }}">obrigações</a> ·
    <a href="/tenants/{{ tenant.id }}/cnpjs/{{ cnpj.id }}/certidoes?token={{ request.args.get('token', '') }}">certidões</a>
  </td>
</tr>
{% endfor %}
</table>

{% if sublimite_alerts %}
<h2>Alertas de sublimite do Simples Nacional</h2>
<table>
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
<table>
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
""")

_CNPJ_HISTORY_TEMPLATE = page("Histórico — {{ cnpj.cnpj }}", """
<p><a href="/tenants/{{ cnpj.tenant_id }}?token={{ request.args.get('token', '') }}">&larr; voltar pro escritório</a></p>
<h1>Histórico — {{ cnpj.razao_social or cnpj.cnpj }} ({{ cnpj.cnpj }})</h1>
<table>
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
""")

_OBRIGACOES_TEMPLATE = page("Obrigações — {{ cnpj.cnpj }}", """
<p><a href="/tenants/{{ cnpj.tenant_id }}?token={{ request.args.get('token', '') }}">&larr; voltar pro escritório</a></p>
<h1>Obrigações — {{ cnpj.razao_social or cnpj.cnpj }} ({{ cnpj.cnpj }})</h1>

<h2>Cadastrar obrigação</h2>
<form method="post" class="card">
  <label>Tipo (ex: DAS, DCTFWeb, DEFIS)<input type="text" name="tipo" required></label>
  <label>Vencimento<input type="date" name="vencimento" required></label>
  <button type="submit">Cadastrar</button>
</form>

<h2>Obrigações cadastradas</h2>
<table>
<tr><th>Tipo</th><th>Vencimento</th><th>Status</th><th></th></tr>
{% for obrigacao in obrigacoes %}
<tr>
  <td>{{ obrigacao.tipo }}</td>
  <td>{{ obrigacao.vencimento }}</td>
  <td>{{ obrigacao.status }}</td>
  <td>
    {% if obrigacao.status == "pendente" %}
    <form method="post" action="/tenants/{{ cnpj.tenant_id }}/cnpjs/{{ cnpj.id }}/obrigacoes/{{ obrigacao.id }}/entregue?token={{ request.args.get('token', '') }}" class="inline">
      <button type="submit">Marcar entregue</button>
    </form>
    {% endif %}
  </td>
</tr>
{% endfor %}
</table>
{% if not obrigacoes %}<p>Nenhuma obrigação cadastrada ainda.</p>{% endif %}
""")

_CERTIDOES_TEMPLATE = page("Certidões — {{ cnpj.cnpj }}", """
<p><a href="/tenants/{{ cnpj.tenant_id }}?token={{ request.args.get('token', '') }}">&larr; voltar pro escritório</a></p>
<h1>Certidões — {{ cnpj.razao_social or cnpj.cnpj }} ({{ cnpj.cnpj }})</h1>
<p>Órgãos exigidos pra essa empresa (UF: {{ cnpj.uf or "não informada" }}): {{ orgaos|join(", ") }}</p>
{% if certidoes %}<p><a href="/tenants/{{ cnpj.tenant_id }}/cnpjs/{{ cnpj.id }}/certidoes/unificado.pdf?token={{ request.args.get('token', '') }}">Baixar todas em um único PDF &rarr;</a></p>{% endif %}

<h2>Dossiê fiscal automático</h2>
<p>Consulta ao vivo na InfoSimples (CND federal, dívida ativa/PGFN, FGTS e CNDT) e gera um único PDF —
não precisa upload manual. Cada consulta tem custo.</p>
<p><a href="/tenants/{{ cnpj.tenant_id }}/cnpjs/{{ cnpj.id }}/certidoes/dossie-fiscal.pdf?token={{ request.args.get('token', '') }}">Baixar dossiê fiscal automático (PDF) &rarr;</a></p>

<h2>Enviar certidão (PDF real)</h2>
<form method="post" enctype="multipart/form-data" class="card">
  <label>Órgão
    <select name="orgao" required>
      {% for orgao in todos_orgaos %}<option value="{{ orgao }}">{{ orgao|upper }}</option>{% endfor %}
    </select>
  </label>
  <label>Número/código de controle (opcional)<input type="text" name="numero"></label>
  <label>Data de emissão<input type="date" name="emitida_em" required></label>
  <label>Validade<input type="date" name="valida_ate" required></label>
  <label>Arquivo PDF<input type="file" name="arquivo" accept="application/pdf" required></label>
  <button type="submit">Enviar</button>
</form>

<h2>Situação por órgão</h2>
<table>
<tr><th>Órgão</th><th>Status</th><th>Validade</th><th>Número</th><th></th></tr>
{% for orgao in orgaos %}
{% set certidao = atuais.get(orgao) %}
<tr>
  <td>{{ orgao|upper }}</td>
  <td>{{ status.get(orgao, "sem certidão") }}</td>
  <td>{{ certidao.valida_ate if certidao else "-" }}</td>
  <td>{{ certidao.numero if certidao and certidao.numero else "-" }}</td>
  <td>{% if certidao %}<a href="/tenants/{{ cnpj.tenant_id }}/cnpjs/{{ cnpj.id }}/certidoes/{{ certidao.id }}/baixar?token={{ request.args.get('token', '') }}">baixar</a>{% endif %}</td>
</tr>
{% endfor %}
</table>
""")

_REFORMA_TEMPLATE = page("Simulador da Reforma Tributária", """
<p><a href="/tenants">&larr; voltar</a></p>
<h1>Simulador da Reforma Tributária (ilustrativo)</h1>
<div class="alert">{{ resultado.aviso if resultado else "Valores ilustrativos (placeholders), não use para cálculo real nem para orientar cliente sem validar com um contador." }}</div>
<form method="get" class="card">
  <label>Faturamento anual (R$ {{ faturamento_min }} a R$ {{ faturamento_max }})
    <input type="number" name="faturamento" min="{{ faturamento_min }}" max="{{ faturamento_max }}" step="1000" value="{{ resultado.faturamento if resultado else '' }}" required>
  </label>
  <button type="submit">Simular</button>
</form>
{% if resultado %}
<table>
<tr><th>Regime</th><th>Valor estimado</th></tr>
<tr{% if resultado.melhor == "unificado" %} style="font-weight:bold"{% endif %}><td>Simples Unificado</td><td>R$ {{ "%.2f"|format(resultado.unificado) }}</td></tr>
<tr{% if resultado.melhor == "hibrido" %} style="font-weight:bold"{% endif %}><td>Híbrido</td><td>R$ {{ "%.2f"|format(resultado.hibrido) }}</td></tr>
</table>
<p>Melhor opção (ilustrativa): <strong>{{ "Simples Unificado" if resultado.melhor == "unificado" else "Híbrido" }}</strong> — diferença de R$ {{ "%.2f"|format(resultado.diferenca) }}.</p>
{% endif %}
""")

_NOVO_TENANT_TEMPLATE = page("Cadastrar escritório", """
<p><a href="/tenants">&larr; voltar pra lista</a></p>
<h1>Cadastrar novo escritório</h1>
{% if erro %}<div class="alert">{{ erro }}</div>{% endif %}
<form method="post" enctype="multipart/form-data" class="card">
  <label>Nome do escritório<input type="text" name="nome" required value="{{ nome or '' }}"></label>
  <label>WhatsApp de contato (opcional)<input type="text" name="whatsapp" placeholder="5511999999999" value="{{ whatsapp or '' }}"></label>
  <label>E-mail de contato (opcional)<input type="email" name="email" value="{{ email or '' }}"></label>
  <label>Plano (opcional)<input type="text" name="plano" value="{{ plano or '' }}"></label>
  <label>Carteira de CNPJs — CSV (opcional, pode importar depois)
    <input type="file" name="carteira" accept=".csv">
    <small>colunas: cnpj,razao_social,nome_fantasia,regime_tributario</small>
  </label>
  <button type="submit">Cadastrar</button>
</form>
""")

_USUARIOS_TEMPLATE = page("Usuários da equipe", """
<p><a href="/tenants">&larr; voltar</a></p>
<h1>Usuários da equipe</h1>
{% if erro %}<div class="alert">{{ erro }}</div>{% endif %}
{% if sucesso %}<div class="success">{{ sucesso }}</div>{% endif %}

<h2>Cadastrar novo acesso</h2>
<form method="post" class="card">
  <label>Nome<input type="text" name="nome" value="{{ nome or '' }}"></label>
  <label>Usuário (login)<input type="text" name="username" required value="{{ username or '' }}"></label>
  <label>Senha<input type="password" name="password" required minlength="8"></label>
  <button type="submit">Cadastrar</button>
</form>

<h2>Acessos cadastrados</h2>
<table>
<tr><th>Usuário</th><th>Nome</th><th>Criado em</th><th>Status</th><th></th></tr>
{% for usuario in usuarios %}
<tr>
  <td>{{ usuario.username }}</td>
  <td>{{ usuario.nome or "-" }}</td>
  <td>{{ usuario.criado_em[:10] }}</td>
  <td>{{ "ativo" if usuario.ativo else "desativado" }}</td>
  <td>
    <form method="post" action="/admin/usuarios/{{ usuario.id }}/alternar-ativo" class="inline">
      <button type="submit">{{ "Desativar" if usuario.ativo else "Reativar" }}</button>
    </form>
  </td>
</tr>
{% endfor %}
</table>
{% if not usuarios %}<p>Nenhum acesso individual cadastrado ainda — só o usuário mestre (ADMIN_USERNAME).</p>{% endif %}
""")

_PGFN_DADOS_ABERTOS_TEMPLATE = """
<!doctype html>
<title>Dados Abertos da PGFN</title>
<h1>Dados Abertos da PGFN</h1>
<p><a href="/tenants">&larr; voltar</a></p>
<p>Importa o arquivo trimestral de Dados Abertos da dívida ativa (baixado em
gov.br/pgfn &rarr; Acesso à Informação &rarr; Dados Abertos — <strong>não</strong>
confundir com a "Lista de Devedores"). Isso completa a pré-análise com data
de inscrição e se a dívida já foi ajuizada ou protestada, pra cada
inscrição que também aparecer numa consulta futura.</p>
{% if erro %}<p style="color:#B23A48"><strong>{{ erro }}</strong></p>{% endif %}
{% if sucesso %}<p style="color:#1a7a3c"><strong>{{ sucesso }}</strong></p>{% endif %}
<form method="post" enctype="multipart/form-data">
  <p><label>Referência (ex: 2026-03)<br><input type="text" name="base_referencia" required placeholder="AAAA-MM" value="{{ base_referencia or '' }}"></label></p>
  <p><label>Arquivo (.xlsx ou .csv)<br><input type="file" name="arquivo" accept=".xlsx,.csv" required></label></p>
  <button type="submit">Importar</button>
</form>
"""

_STATUS_TEMPLATE = page("Status do sistema", """
<p><a href="/tenants">&larr; voltar</a></p>
<h1>Status do sistema</h1>
<p>Diagnóstico rápido do que está configurado e com dado de verdade — sem mostrar
nenhum valor de senha/token, só se está presente ou não.</p>

<h2>Integrações (variáveis de ambiente)</h2>
<table>
<tr><th>Variável</th><th>Status</th></tr>
{% for nome, configurado in integracoes %}
<tr><td>{{ nome }}</td><td>{{ "✅ configurado" if configurado else "❌ não configurado" }}</td></tr>
{% endfor %}
</table>

<h2>Dados Abertos da PGFN (pré-análise)</h2>
<p>Inscrições importadas: <strong>{{ dividas_abertas_count }}</strong>
{% if dividas_abertas_count == 0 %}— nenhuma ainda, então a pré-análise não mostra data de
inscrição nem ajuizamento/protesto pra nenhum CNPJ. <a href="/admin/pgfn-dados-abertos">Importar agora &rarr;</a>
{% endif %}</p>

<h2>Leads de campanha por tese</h2>
<table>
<tr><th>Tese</th><th>Leads</th><th>Com e-mail</th><th>Com telefone</th></tr>
{% for tese, total, com_email, com_telefone in leads_por_tese %}
<tr><td>{{ tese }}</td><td>{{ total }}</td><td>{{ com_email }}</td><td>{{ com_telefone }}</td></tr>
{% endfor %}
</table>
{% if not leads_por_tese %}<p>Nenhum lead importado ainda em nenhuma tese. <a href="/admin/campanhas/leads/importar">Importar &rarr;</a></p>{% endif %}

<h2>Templates de e-mail — status do texto</h2>
<table>
<tr><th>Tese</th><th>E-mail inicial</th><th>WhatsApp</th></tr>
{% for tese, email_status, whatsapp_status in templates_status %}
<tr><td>{{ tese }}</td><td>{{ email_status }}</td><td>{{ whatsapp_status }}</td></tr>
{% endfor %}
</table>
""")

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

    def _rodar_check_all(conn, forcar_infosimples: bool = False) -> dict:
        """Corpo de verdade do check diário — chamado tanto pelo cron
        (`/cron/check-all`) quanto pelo botão manual de admin, igual ao
        padrão já usado pra campanhas (`_executar_campanha_diaria`).

        A busca via InfoSimples só roda às segundas-feiras por padrão
        (gate por `weekday() == 0`, mesmo padrão do relatório semanal de
        campanhas) — fica achado novo pronto antes de `check_all_tenants`
        rodar o motor de alerta logo em seguida, então um achado que a
        InfoSimples trouxe hoje já sai no mesmo WhatsApp/e-mail.
        `forcar_infosimples=True` (só o botão manual oferece isso) ignora
        o dia da semana — útil pra rodar fora de segunda sem esperar.
        """
        infosimples_token = os.environ.get("INFOSIMPLES_API_TOKEN")
        infosimples_resultado = None
        if infosimples_token and (forcar_infosimples or date.today().weekday() == 0):
            infosimples_resultado = run_infosimples_semanal(conn, infosimples_token)

        resultados = check_all_tenants(conn)
        return {
            "tenants_verificados": len(resultados),
            "resultados": resultados,
            "infosimples_semanal_rodou": infosimples_resultado is not None,
            "infosimples_semanal_resultado": infosimples_resultado,
        }

    @app.route("/cron/check-all", methods=["GET", "POST"])
    def cron_check_all():
        if not cron_authorized():
            return jsonify({"error": "não autorizado — CRON_SECRET ausente ou incorreto"}), 401
        conn = _connect()
        resultado = _rodar_check_all(conn)
        conn.close()
        return jsonify(resultado)

    @app.get("/admin/check-all/rodar-agora")
    def check_all_rodar_agora_form():
        unauthorized = require_admin()
        if unauthorized:
            return unauthorized
        return render_template_string(_CHECK_ALL_RODAR_AGORA_TEMPLATE, resultado=None)

    @app.post("/admin/check-all/rodar-agora")
    def check_all_rodar_agora():
        unauthorized = require_admin()
        if unauthorized:
            return unauthorized
        forcar_infosimples = request.form.get("forcar_infosimples") == "on"
        conn = _connect()
        resultado = _rodar_check_all(conn, forcar_infosimples=forcar_infosimples)
        conn.close()
        return render_template_string(_CHECK_ALL_RODAR_AGORA_TEMPLATE, resultado=resultado)

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

    @app.route("/admin/pgfn-dados-abertos", methods=["GET", "POST"])
    def pgfn_dados_abertos():
        unauthorized = require_admin()
        if unauthorized:
            return unauthorized

        if request.method == "GET":
            return render_template_string(_PGFN_DADOS_ABERTOS_TEMPLATE)

        base_referencia = (request.form.get("base_referencia") or "").strip()
        arquivo = request.files.get("arquivo")

        if not base_referencia or not arquivo or not arquivo.filename:
            return (
                render_template_string(
                    _PGFN_DADOS_ABERTOS_TEMPLATE,
                    erro="Referência e arquivo são obrigatórios.",
                    base_referencia=base_referencia,
                ),
                400,
            )

        conn = _connect()
        try:
            quantidade = importar_arquivo(conn, io.BytesIO(arquivo.stream.read()), arquivo.filename, base_referencia)
        except ArquivoDadosAbertosError as exc:
            conn.close()
            return (
                render_template_string(_PGFN_DADOS_ABERTOS_TEMPLATE, erro=str(exc), base_referencia=base_referencia),
                400,
            )
        conn.close()
        return render_template_string(
            _PGFN_DADOS_ABERTOS_TEMPLATE,
            sucesso=f"{quantidade} inscrição(ões) importada(s)/atualizada(s).",
        )

    @app.get("/admin/status")
    def status_sistema():
        unauthorized = require_admin()
        if unauthorized:
            return unauthorized

        from src.campaigns.engine import tem_mensagem_whatsapp_dedicada
        from src.campaigns.models import TIPO_INICIAL

        integracoes = [
            (
                "INFOSIMPLES_API_TOKEN (CND + Lista de Devedores + FGTS + CNDT na pré-análise)",
                bool(os.environ.get("INFOSIMPLES_API_TOKEN")),
            ),
            ("CNPJA_API_TOKEN (dado cadastral completo + Cartão CNPJ)", bool(os.environ.get("CNPJA_API_TOKEN"))),
            ("EXA_API_KEY (busca automática de e-mail dos leads)", bool(os.environ.get("EXA_API_KEY"))),
            ("SMTP_HOST/PORT/USERNAME/PASSWORD (envio de e-mail da campanha)",
             bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_PORT") and os.environ.get("SMTP_USERNAME") and os.environ.get("SMTP_PASSWORD"))),
            ("CRON_SECRET (cron automático do Vercel)", bool(os.environ.get("CRON_SECRET"))),
            ("WHATSAPP_EQUIPE_EMAIL (resumo diário de telefones pra equipe)", bool(os.environ.get("WHATSAPP_EQUIPE_EMAIL"))),
            ("BREVO_API_KEY (sincronização de engajados)", bool(os.environ.get("BREVO_API_KEY"))),
        ]

        conn = _connect()
        dividas_abertas_count = storage.count_dividas_abertas_pgfn(conn)
        conn.close()

        campanhas_conn = campaigns_storage.connect(campaigns_db_path or campaigns_storage.DEFAULT_DB_PATH)
        todas_teses = sorted(set(campaigns_storage.list_teses(campanhas_conn)) | set(campaigns_storage.list_template_teses(campanhas_conn)))
        leads_por_tese = []
        for tese in todas_teses:
            leads = campaigns_storage.list_leads(campanhas_conn, tese)
            if not leads:
                continue
            leads_por_tese.append(
                (tese, len(leads), sum(1 for lead in leads if lead.email), sum(1 for lead in leads if lead.telefone))
            )

        templates_status = []
        for tese in todas_teses:
            template = campaigns_storage.get_template(campanhas_conn, tese, TIPO_INICIAL)
            email_status = "⚠️ rascunho" if (template and template.headline.startswith("[AJUSTAR")) else (
                "✅ texto real" if template else "— sem template"
            )
            whatsapp_status = "✅ mensagem própria" if tem_mensagem_whatsapp_dedicada(tese) else "— mensagem genérica de dívida"
            templates_status.append((tese, email_status, whatsapp_status))
        campanhas_conn.close()

        return render_template_string(
            _STATUS_TEMPLATE,
            integracoes=integracoes,
            dividas_abertas_count=dividas_abertas_count,
            leads_por_tese=leads_por_tese,
            templates_status=templates_status,
        )

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
        situacao_fgts = None
        situacao_cndt = None
        infosimples_token = os.environ.get("INFOSIMPLES_API_TOKEN")
        if infosimples_token:
            try:
                situacao_fiscal = montar_situacao_fiscal(consultar_cnd_federal(cnpj, infosimples_token))
            except ConsultaDebitosError as exc:
                alertas.append(f"Não foi possível consultar CND federal (Receita Federal/PGFN): {exc}")

            try:
                divida_ativa = montar_divida_ativa(consultar_lista_devedores(cnpj, infosimples_token))
                if divida_ativa:
                    conn = _connect()
                    try:
                        divida_ativa = enriquecer_com_dados_abertos(conn, divida_ativa)
                    finally:
                        conn.close()
            except ConsultaDebitosError as exc:
                alertas.append(f"Não foi possível consultar lista de devedores da PGFN: {exc}")

            try:
                situacao_fgts = montar_situacao_fgts(consultar_regularidade_fgts(cnpj, infosimples_token))
            except ConsultaDebitosError as exc:
                alertas.append(f"Não foi possível consultar regularidade do FGTS (Caixa): {exc}")

            try:
                situacao_cndt = montar_situacao_cndt(consultar_cndt_trabalhista(cnpj, infosimples_token))
            except ConsultaDebitosError as exc:
                alertas.append(f"Não foi possível consultar CNDT (débitos trabalhistas): {exc}")

            alertas += gerar_alertas_fiscais(situacao_fiscal, divida_ativa, situacao_fgts, situacao_cndt)

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
            situacao_fgts=situacao_fgts,
            situacao_cndt=situacao_cndt,
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

    @app.get("/admin/diagnostico/infosimples")
    def diagnostico_infosimples():
        """Chama a InfoSimples direto (sem passar pelo PDF/alertas) e
        devolve a resposta bruta em JSON — pra diagnosticar se a chamada
        de verdade está acontecendo (token válido, API respondendo),
        separado de qualquer problema de como o resultado é exibido.
        """
        unauthorized = require_admin()
        if unauthorized:
            return unauthorized

        cnpj = (request.args.get("cnpj") or "").strip()
        if not validar_cnpj(cnpj):
            return jsonify({"error": "CNPJ inválido — confira os dígitos."}), 400

        token = os.environ.get("INFOSIMPLES_API_TOKEN")
        resultado = {"cnpj": cnpj, "infosimples_token_configurado": bool(token)}
        if not token:
            return jsonify(resultado)

        try:
            resultado["cnd_federal"] = consultar_cnd_federal(cnpj, token)
        except ConsultaDebitosError as exc:
            resultado["cnd_federal_erro"] = str(exc)

        try:
            resultado["lista_devedores"] = consultar_lista_devedores(cnpj, token)
        except ConsultaDebitosError as exc:
            resultado["lista_devedores_erro"] = str(exc)

        try:
            resultado["regularidade_fgts"] = consultar_regularidade_fgts(cnpj, token)
        except ConsultaDebitosError as exc:
            resultado["regularidade_fgts_erro"] = str(exc)

        try:
            resultado["cndt_trabalhista"] = consultar_cndt_trabalhista(cnpj, token)
        except ConsultaDebitosError as exc:
            resultado["cndt_trabalhista_erro"] = str(exc)

        return jsonify(resultado)

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
        scores = {
            cnpj.id: calcular_score_risco(
                cnpj.uf, storage.list_obrigacoes(conn, cnpj.id), storage.latest_certidoes_by_orgao(conn, cnpj.id)
            )
            for cnpj in cnpjs
        }
        conn.close()
        return render_template_string(
            _TENANT_DETAIL_TEMPLATE,
            tenant=tenant,
            cnpjs=cnpjs,
            findings=findings,
            sublimite_alerts=sublimite_alerts,
            scores=scores,
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

    def _get_cnpj_or_404(conn, tenant_id: int, cnpj_id: int):
        tenant = storage.get_tenant(conn, tenant_id)
        cnpj = storage.get_cnpj(conn, cnpj_id)
        if tenant is None or cnpj is None or cnpj.tenant_id != tenant_id:
            return None, None
        return tenant, cnpj

    @app.route("/tenants/<int:tenant_id>/cnpjs/<int:cnpj_id>/obrigacoes", methods=["GET", "POST"])
    def obrigacoes(tenant_id: int, cnpj_id: int):
        conn = _connect()
        tenant, cnpj = _get_cnpj_or_404(conn, tenant_id, cnpj_id)
        if tenant is None:
            conn.close()
            return jsonify({"error": "CNPJ não encontrado nesse tenant"}), 404
        if not _tenant_authorized(tenant):
            conn.close()
            return jsonify({"error": "acesso não autorizado — informe ?token=... ou faça login de admin"}), 403

        if request.method == "POST":
            tipo = (request.form.get("tipo") or "").strip()
            vencimento = (request.form.get("vencimento") or "").strip()
            if tipo and vencimento:
                storage.create_obrigacao(conn, cnpj_id, tipo, vencimento)

        obrigacoes_lista = storage.list_obrigacoes(conn, cnpj_id)
        conn.close()
        return render_template_string(_OBRIGACOES_TEMPLATE, cnpj=cnpj, obrigacoes=obrigacoes_lista)

    @app.post("/tenants/<int:tenant_id>/cnpjs/<int:cnpj_id>/obrigacoes/<int:obrigacao_id>/entregue")
    def marcar_obrigacao_entregue_route(tenant_id: int, cnpj_id: int, obrigacao_id: int):
        conn = _connect()
        tenant, cnpj = _get_cnpj_or_404(conn, tenant_id, cnpj_id)
        if tenant is None:
            conn.close()
            return jsonify({"error": "CNPJ não encontrado nesse tenant"}), 404
        if not _tenant_authorized(tenant):
            conn.close()
            return jsonify({"error": "acesso não autorizado — informe ?token=... ou faça login de admin"}), 403
        storage.marcar_obrigacao_entregue(conn, obrigacao_id)
        conn.close()
        token = request.args.get("token", "")
        return redirect(f"/tenants/{tenant_id}/cnpjs/{cnpj_id}/obrigacoes?token={token}")

    @app.route("/tenants/<int:tenant_id>/cnpjs/<int:cnpj_id>/certidoes", methods=["GET", "POST"])
    def certidoes(tenant_id: int, cnpj_id: int):
        conn = _connect()
        tenant, cnpj = _get_cnpj_or_404(conn, tenant_id, cnpj_id)
        if tenant is None:
            conn.close()
            return jsonify({"error": "CNPJ não encontrado nesse tenant"}), 404
        if not _tenant_authorized(tenant):
            conn.close()
            return jsonify({"error": "acesso não autorizado — informe ?token=... ou faça login de admin"}), 403

        if request.method == "POST":
            orgao = (request.form.get("orgao") or "").strip().lower()
            emitida_em = (request.form.get("emitida_em") or "").strip()
            valida_ate = (request.form.get("valida_ate") or "").strip()
            numero = (request.form.get("numero") or "").strip() or None
            arquivo = request.files.get("arquivo")
            if orgao in ORGAOS_CERTIDAO and emitida_em and valida_ate and arquivo and arquivo.filename:
                storage.create_certidao(
                    conn, cnpj_id, orgao, numero, emitida_em, valida_ate, arquivo.filename, arquivo.read()
                )

        orgaos_lista = orgaos_exigidos(cnpj.uf)
        atuais = storage.latest_certidoes_by_orgao(conn, cnpj_id)
        status = {orgao: certidao_status(certidao.valida_ate) for orgao, certidao in atuais.items()}
        conn.close()
        return render_template_string(
            _CERTIDOES_TEMPLATE, cnpj=cnpj, orgaos=orgaos_lista, todos_orgaos=sorted(ORGAOS_CERTIDAO),
            atuais=atuais, status=status, certidoes=atuais,
        )

    @app.get("/tenants/<int:tenant_id>/cnpjs/<int:cnpj_id>/certidoes/<int:certidao_id>/baixar")
    def baixar_certidao(tenant_id: int, cnpj_id: int, certidao_id: int):
        conn = _connect()
        tenant, cnpj = _get_cnpj_or_404(conn, tenant_id, cnpj_id)
        if tenant is None:
            conn.close()
            return jsonify({"error": "CNPJ não encontrado nesse tenant"}), 404
        if not _tenant_authorized(tenant):
            conn.close()
            return jsonify({"error": "acesso não autorizado — informe ?token=... ou faça login de admin"}), 403
        certidao = storage.get_certidao(conn, certidao_id)
        arquivo = storage.get_certidao_arquivo(conn, certidao_id)
        conn.close()
        if certidao is None or arquivo is None or certidao.cnpj_id != cnpj_id:
            return jsonify({"error": "certidão não encontrada"}), 404
        return Response(
            arquivo, mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={certidao.arquivo_nome}"},
        )

    @app.get("/tenants/<int:tenant_id>/cnpjs/<int:cnpj_id>/certidoes/unificado.pdf")
    def baixar_certidoes_unificado(tenant_id: int, cnpj_id: int):
        conn = _connect()
        tenant, cnpj = _get_cnpj_or_404(conn, tenant_id, cnpj_id)
        if tenant is None:
            conn.close()
            return jsonify({"error": "CNPJ não encontrado nesse tenant"}), 404
        if not _tenant_authorized(tenant):
            conn.close()
            return jsonify({"error": "acesso não autorizado — informe ?token=... ou faça login de admin"}), 403
        atuais = storage.latest_certidoes_by_orgao(conn, cnpj_id)
        arquivos = [storage.get_certidao_arquivo(conn, certidao.id) for certidao in atuais.values()]
        conn.close()
        arquivos = [a for a in arquivos if a]
        if not arquivos:
            return jsonify({"error": "nenhuma certidão enviada ainda pra esse CNPJ"}), 404

        from pypdf import PdfWriter

        writer = PdfWriter()
        for conteudo in arquivos:
            writer.append(io.BytesIO(conteudo))
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        return Response(
            buffer.read(), mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=certidoes_{only_digits(cnpj.cnpj)}.pdf"},
        )

    @app.get("/tenants/<int:tenant_id>/cnpjs/<int:cnpj_id>/certidoes/dossie-fiscal.pdf")
    def dossie_fiscal_automatico(tenant_id: int, cnpj_id: int):
        """Dossiê fiscal automático: consulta ao vivo na InfoSimples (CND
        federal, dívida ativa/PGFN, FGTS, CNDT) pra um CNPJ já na carteira
        e devolve tudo consolidado num único PDF — sem precisar de upload
        manual de cada certidão (diferente de `/certidoes/unificado.pdf`,
        que só junta o que já foi enviado).
        """
        conn = _connect()
        tenant, cnpj = _get_cnpj_or_404(conn, tenant_id, cnpj_id)
        if tenant is None:
            conn.close()
            return jsonify({"error": "CNPJ não encontrado nesse tenant"}), 404
        if not _tenant_authorized(tenant):
            conn.close()
            return jsonify({"error": "acesso não autorizado — informe ?token=... ou faça login de admin"}), 403
        conn.close()

        token = os.environ.get("INFOSIMPLES_API_TOKEN")
        if not token:
            return jsonify({"error": "INFOSIMPLES_API_TOKEN não configurado — não é possível buscar automaticamente."}), 400

        situacao_fiscal = None
        divida_ativa = None
        situacao_fgts = None
        situacao_cndt = None
        alertas: list[str] = []

        try:
            situacao_fiscal = montar_situacao_fiscal(consultar_cnd_federal(cnpj.cnpj, token))
        except ConsultaDebitosError as exc:
            alertas.append(f"Não foi possível consultar CND federal (Receita Federal/PGFN): {exc}")

        try:
            divida_ativa = montar_divida_ativa(consultar_lista_devedores(cnpj.cnpj, token))
            if divida_ativa:
                conn = _connect()
                try:
                    divida_ativa = enriquecer_com_dados_abertos(conn, divida_ativa)
                finally:
                    conn.close()
        except ConsultaDebitosError as exc:
            alertas.append(f"Não foi possível consultar lista de devedores da PGFN: {exc}")

        try:
            situacao_fgts = montar_situacao_fgts(consultar_regularidade_fgts(cnpj.cnpj, token))
        except ConsultaDebitosError as exc:
            alertas.append(f"Não foi possível consultar regularidade do FGTS (Caixa): {exc}")

        try:
            situacao_cndt = montar_situacao_cndt(consultar_cndt_trabalhista(cnpj.cnpj, token))
        except ConsultaDebitosError as exc:
            alertas.append(f"Não foi possível consultar CNDT (débitos trabalhistas): {exc}")

        alertas += gerar_alertas_fiscais(situacao_fiscal, divida_ativa, situacao_fgts, situacao_cndt)

        fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        render_dossie_fiscal_pdf(
            cnpj,
            tenant,
            alertas,
            pdf_path,
            gerado_em=date.today().isoformat(),
            situacao_fiscal=situacao_fiscal,
            divida_ativa=divida_ativa,
            situacao_fgts=situacao_fgts,
            situacao_cndt=situacao_cndt,
        )

        @after_this_request
        def _cleanup(response):
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            return response

        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=f"dossie_fiscal_{only_digits(cnpj.cnpj)}.pdf",
            mimetype="application/pdf",
        )

    @app.get("/reforma-tributaria")
    def reforma_tributaria():
        unauthorized = require_admin()
        if unauthorized:
            return unauthorized
        faturamento_raw = request.args.get("faturamento")
        resultado = None
        if faturamento_raw:
            try:
                faturamento = float(faturamento_raw)
            except ValueError:
                faturamento = None
            if faturamento is not None:
                resultado = simular(faturamento)
        return render_template_string(
            _REFORMA_TEMPLATE, resultado=resultado, faturamento_min=int(FATURAMENTO_MINIMO),
            faturamento_max=int(FATURAMENTO_MAXIMO),
        )

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

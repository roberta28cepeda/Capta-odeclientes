"""Acha o e-mail de contato de uma empresa a partir do nome/razão social,
via Brave Search API (2.000 buscas grátis/mês no plano gratuito — cobre um
volume de até ~65 leads novos/dia, ver README) + leitura da página
resultante procurando um e-mail.

Usa a Brave Search API (não a Google Custom Search JSON API) porque o
Google fechou essa API pra novas contas em 2025 e vai descontinuar de vez
em 2027 — "pesquisar toda a Web" nem existe mais pra mecanismo criado
agora, só busca em domínios específicos, o que não serve pra buscar o
site de qualquer empresa.

Não é 100% confiável (nem toda empresa tem e-mail público, nem toda busca
acha o site certo) — é uma tentativa best-effort, igual o enriquecimento
de telefone via BrasilAPI no módulo `prospecting.pgfn`.
"""

from __future__ import annotations

import re

import requests

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# E-mails genéricos de institucional/spam/exemplo que não valem como contato.
_DOMINIOS_IGNORADOS = {"sentry.io", "wixpress.com", "example.com", "godaddy.com", "schema.org"}

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


class EmailFinderError(RuntimeError):
    """Erro ao consultar a Brave Search API (chave inválida, cota excedida etc.)."""


def _extrair_email(texto: str) -> str | None:
    for match in _EMAIL_RE.findall(texto):
        dominio = match.split("@")[-1].lower()
        if dominio not in _DOMINIOS_IGNORADOS and not dominio.endswith(".png") and not dominio.endswith(".jpg"):
            return match
    return None


def buscar_email_por_empresa(
    razao_social: str, api_key: str, session: requests.Session | None = None
) -> str | None:
    """Busca o site da empresa via Brave Search e tenta extrair um e-mail dele.

    Retorna None (sem erro) se não achar nenhum resultado ou nenhum e-mail
    na página — CNPJ sem e-mail público não deve travar o resto do lote.
    """
    session = session or requests.Session()

    try:
        response = session.get(
            SEARCH_URL,
            params={"q": f"{razao_social} contato e-mail", "count": 3},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        raise EmailFinderError(f"Falha ao consultar a Brave Search API: {exc}") from exc

    if response.status_code == 429:
        raise EmailFinderError("Cota mensal da Brave Search API excedida (2.000 buscas grátis/mês).")
    if response.status_code != 200:
        raise EmailFinderError(f"Brave Search API retornou {response.status_code}: {response.text[:200]}")

    payload = response.json()
    resultados = payload.get("web", {}).get("results", [])
    for item in resultados:
        snippet = f"{item.get('title', '')} {item.get('description', '')}"
        email = _extrair_email(snippet)
        if email:
            return email

        link = item.get("url")
        if not link:
            continue
        try:
            page = session.get(link, timeout=10)
        except requests.exceptions.RequestException:
            continue
        if page.status_code == 200:
            email = _extrair_email(page.text)
            if email:
                return email

    return None

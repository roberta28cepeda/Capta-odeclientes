"""Acha o e-mail de contato de uma empresa a partir do nome/razão social,
via Google Custom Search JSON API (100 buscas grátis/dia — acima disso é
pago, ver README) + leitura da página resultante procurando um e-mail.

Não é 100% confiável (nem toda empresa tem e-mail público, nem toda busca
acha o site certo) — é uma tentativa best-effort, igual o enriquecimento
de telefone via BrasilAPI no módulo `prospecting.pgfn`.
"""

from __future__ import annotations

import re

import requests

SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

# E-mails genéricos de institucional/spam/exemplo que não valem como contato.
_DOMINIOS_IGNORADOS = {"sentry.io", "wixpress.com", "example.com", "godaddy.com", "schema.org"}

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


class EmailFinderError(RuntimeError):
    """Erro ao consultar a Custom Search API (chave/cx inválidos, cota excedida etc.)."""


def _extrair_email(html: str) -> str | None:
    for match in _EMAIL_RE.findall(html):
        dominio = match.split("@")[-1].lower()
        if dominio not in _DOMINIOS_IGNORADOS and not dominio.endswith(".png") and not dominio.endswith(".jpg"):
            return match
    return None


def buscar_email_por_empresa(
    razao_social: str, api_key: str, search_engine_id: str, session: requests.Session | None = None
) -> str | None:
    """Busca o site da empresa no Google e tenta extrair um e-mail dele.

    Retorna None (sem erro) se não achar nenhum resultado ou nenhum e-mail
    na página — CNPJ sem e-mail público não deve travar o resto do lote.
    """
    session = session or requests.Session()

    try:
        response = session.get(
            SEARCH_URL,
            params={"key": api_key, "cx": search_engine_id, "q": f"{razao_social} contato e-mail", "num": 3},
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        raise EmailFinderError(f"Falha ao consultar a Custom Search API: {exc}") from exc

    if response.status_code == 429:
        raise EmailFinderError("Cota diária da Custom Search API excedida (100 buscas grátis/dia).")
    if response.status_code != 200:
        raise EmailFinderError(f"Custom Search API retornou {response.status_code}: {response.text[:200]}")

    payload = response.json()
    for item in payload.get("items", []):
        snippet = f"{item.get('title', '')} {item.get('snippet', '')}"
        email = _extrair_email(snippet)
        if email:
            return email

        link = item.get("link")
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

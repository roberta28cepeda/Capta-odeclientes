"""Acha o e-mail de contato de uma empresa a partir do nome/razão social,
via Exa Search API (bônus de $20 na criação da conta + $10/mês grátis
recorrente, sem cartão de crédito — ver README) + leitura do conteúdo da
página resultante procurando um e-mail.

Já usou Google Custom Search e depois Brave Search — ambos fecharam o
tier gratuito sem cartão pra conta nova em 2025/2026. A Exa continua sem
exigir cartão: se o crédito mensal acabar, a busca só para de funcionar
até o mês renovar, nunca gera cobrança sem cartão cadastrado.

Não é 100% confiável (nem toda empresa tem e-mail público, nem toda busca
acha o site certo) — é uma tentativa best-effort, igual o enriquecimento
de telefone via BrasilAPI no módulo `prospecting.pgfn`.
"""

from __future__ import annotations

import re

import requests

SEARCH_URL = "https://api.exa.ai/search"

# E-mails genéricos de institucional/spam/exemplo que não valem como contato.
_DOMINIOS_IGNORADOS = {"sentry.io", "wixpress.com", "example.com", "godaddy.com", "schema.org"}

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


class EmailFinderError(RuntimeError):
    """Erro ao consultar a Exa Search API (chave inválida, crédito esgotado etc.)."""


def _extrair_email(texto: str) -> str | None:
    for match in _EMAIL_RE.findall(texto):
        dominio = match.split("@")[-1].lower()
        if dominio not in _DOMINIOS_IGNORADOS and not dominio.endswith(".png") and not dominio.endswith(".jpg"):
            return match
    return None


def buscar_email_por_empresa(
    razao_social: str, api_key: str, session: requests.Session | None = None
) -> str | None:
    """Busca o site da empresa via Exa e tenta extrair um e-mail dele.

    Retorna None (sem erro) se não achar nenhum resultado ou nenhum e-mail
    — CNPJ sem e-mail público não deve travar o resto do lote.
    """
    session = session or requests.Session()

    try:
        response = session.post(
            SEARCH_URL,
            json={"query": f"{razao_social} contato e-mail", "numResults": 3, "contents": {"text": True}},
            headers={"accept": "application/json", "content-type": "application/json", "x-api-key": api_key},
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        raise EmailFinderError(f"Falha ao consultar a Exa Search API: {exc}") from exc

    if response.status_code == 401:
        raise EmailFinderError("Chave da Exa Search API inválida.")
    if response.status_code == 429:
        raise EmailFinderError("Crédito mensal da Exa Search API esgotado (renova no próximo mês).")
    if response.status_code != 200:
        raise EmailFinderError(f"Exa Search API retornou {response.status_code}: {response.text[:200]}")

    payload = response.json()
    for item in payload.get("results", []):
        snippet = f"{item.get('title', '')} {item.get('text', '')}"
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

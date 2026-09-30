"""Acha o telefone de contato de uma empresa a partir do CNPJ, via ReceitaWS
— mesma fonte pública que o Apps Script já usa pra enriquecer telefone
(o CSV da PGFN só traz CNPJ, razão social e valor da dívida).

Gratuita, mas com limite de 3 consultas por minuto no plano free — por
isso o lote pára assim que bate no limite (erro `PhoneFinderError`), em
vez de insistir e desperdiçar chamada; o resto dos leads sem telefone
continua pendente pro próximo cron.
"""

from __future__ import annotations

import requests

from src.fiscal_monitor.preanalise import only_digits

RECEITAWS_URL = "https://www.receitaws.com.br/v1/cnpj/{cnpj}"


class PhoneFinderError(RuntimeError):
    """Erro ao consultar a ReceitaWS (rate limit, CNPJ inválido, API fora do ar)."""


def buscar_telefone_por_cnpj(cnpj: str, session: requests.Session | None = None) -> str | None:
    """Retorna o primeiro telefone cadastrado na Receita Federal pra esse
    CNPJ, ou `None` (sem erro) se a empresa não tiver telefone público.
    """
    session = session or requests.Session()
    url = RECEITAWS_URL.format(cnpj=only_digits(cnpj))
    try:
        response = session.get(url, timeout=10)
    except requests.exceptions.RequestException as exc:
        raise PhoneFinderError(f"Falha de conexão ao consultar CNPJ {cnpj} na ReceitaWS: {exc}") from exc

    if response.status_code == 429:
        raise PhoneFinderError("Limite de consultas por minuto da ReceitaWS atingido — tenta de novo mais tarde.")
    if response.status_code >= 400:
        raise PhoneFinderError(f"ReceitaWS retornou HTTP {response.status_code} pro CNPJ {cnpj}.")

    corpo = response.json()
    if corpo.get("status") == "ERROR":
        mensagem = corpo.get("message", "")
        if "minuto" in mensagem.lower() or "limite" in mensagem.lower():
            raise PhoneFinderError(f"Limite de consultas da ReceitaWS atingido: {mensagem}")
        return None  # CNPJ não encontrado — não é erro, só não tem o que achar

    telefone = (corpo.get("telefone") or "").strip()
    if not telefone:
        return None
    return telefone.split("/")[0].strip()

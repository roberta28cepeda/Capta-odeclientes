"""Sincroniza quem abre/clica um e-mail da campanha pra uma lista de
"engajados" no Brevo — mesmo mecanismo que o Apps Script já usa hoje, pra
depois mandar artigo do blog pra quem já demonstrou interesse real (essa
segunda parte, o envio do artigo em si, roda fora deste módulo).

Só ativa quando `BREVO_API_KEY` e `BREVO_ENGAJADOS_LIST_ID` estão
configurados — sem isso, o rastreio de abertura/clique continua
funcionando normal, só sem sincronizar com o Brevo.
"""

from __future__ import annotations

import requests

BREVO_CONTACTS_URL = "https://api.brevo.com/v3/contacts"


class BrevoSyncError(RuntimeError):
    """Erro ao sincronizar um contato com o Brevo (chave inválida, API fora do ar)."""


def adicionar_contato_lista(
    email: str, list_id: int, api_key: str, session: requests.Session | None = None
) -> None:
    """Adiciona (ou atualiza, se já existir) um contato numa lista do Brevo."""
    session = session or requests.Session()
    try:
        response = session.post(
            BREVO_CONTACTS_URL,
            json={"email": email, "listIds": [list_id], "updateEnabled": True},
            headers={"api-key": api_key, "content-type": "application/json", "accept": "application/json"},
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        raise BrevoSyncError(f"Falha de conexão ao sincronizar {email} com o Brevo: {exc}") from exc

    if response.status_code not in (200, 201, 204):
        raise BrevoSyncError(f"Brevo retornou HTTP {response.status_code} ao sincronizar {email}: {response.text[:200]}")

"""Assinatura eletrônica de documentos via Clicksign.

Usada pela feature de Documentos (`server.py`, rota
`.../documentos/<id>/solicitar-assinatura`) pra mandar um PDF já
enviado (contrato/procuração) pra assinatura eletrônica do cliente, em
vez de depender só de upload manual do PDF já assinado em papel.

Mesmo padrão de `infosimples.py`: uma classe de erro dedicada, um
helper privado que todo público usa, token sempre recebido como
parâmetro explícito (nunca lido de env var dentro deste módulo — isso é
responsabilidade de quem chama, em `server.py`, exatamente como
`INFOSIMPLES_API_TOKEN`/`CNPJA_API_TOKEN` já funcionam).

Os paths/payloads exatos abaixo são uma aproximação razoável da API v3
da Clicksign (JSON:API) — sem credencial disponível neste ambiente pra
validar contra a API real. Confirmar contra a documentação atual da
Clicksign (https://developers.clicksign.com/) antes de usar em
produção; a forma do módulo (erro, assinatura de cada função, retorno
tipado) já é definitiva.
"""

from __future__ import annotations

import base64

import requests

CLICKSIGN_BASE_URL = "https://api.clicksign.com/api/v3"
_REQUEST_TIMEOUT_SECONDS = 30


class AssinaturaError(RuntimeError):
    """Erro ao criar/consultar/baixar uma solicitação de assinatura na Clicksign."""


def _request_clicksign(
    method: str, path: str, token: str, json_payload: dict | None = None, session: requests.Session | None = None,
) -> dict:
    session = session or requests.Session()
    url = f"{CLICKSIGN_BASE_URL}{path}"
    try:
        response = session.request(
            method,
            url,
            params={"access_token": token},
            json=json_payload,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        raise AssinaturaError(f"Falha de conexão ao chamar a Clicksign ({path}): {exc}") from exc

    if response.status_code >= 400:
        try:
            corpo_erro = response.json()
            mensagem = corpo_erro.get("errors") or corpo_erro.get("message") or response.text
        except ValueError:
            mensagem = response.text
        raise AssinaturaError(f"Erro da Clicksign (HTTP {response.status_code}) em {path}: {mensagem}")

    try:
        return response.json()
    except ValueError as exc:
        raise AssinaturaError(f"Resposta inválida da Clicksign (HTTP {response.status_code}) em {path}") from exc


def criar_solicitacao(
    nome_arquivo: str,
    conteudo_pdf: bytes,
    signatario_nome: str,
    signatario_email: str,
    token: str,
    session: requests.Session | None = None,
) -> dict:
    """Envia o PDF e cria o envelope com um signatário, pedindo assinatura
    por autenticação via e-mail. Retorna um dict com, no mínimo,
    `envelope_id` (usado depois pra consultar status e pelo webhook)."""
    conteudo_base64 = base64.b64encode(conteudo_pdf).decode("ascii")
    payload = {
        "data": {
            "type": "envelopes",
            "attributes": {"name": nome_arquivo, "locale": "pt-BR", "auto_close": True},
        }
    }
    envelope = _request_clicksign("POST", "/envelopes", token, json_payload=payload, session=session)
    envelope_id = envelope["data"]["id"]

    documento_payload = {
        "data": {
            "type": "documents",
            "attributes": {
                "filename": nome_arquivo,
                "content_base64": f"data:application/pdf;base64,{conteudo_base64}",
            },
        }
    }
    _request_clicksign(
        "POST", f"/envelopes/{envelope_id}/documents", token, json_payload=documento_payload, session=session
    )

    signatario_payload = {
        "data": {
            "type": "signers",
            "attributes": {
                "name": signatario_nome,
                "email": signatario_email,
                "communicate_events": {"document_signed": "email"},
            },
        }
    }
    _request_clicksign(
        "POST", f"/envelopes/{envelope_id}/signers", token, json_payload=signatario_payload, session=session
    )

    _request_clicksign(
        "PATCH", f"/envelopes/{envelope_id}",
        token,
        json_payload={"data": {"type": "envelopes", "id": envelope_id, "attributes": {"status": "running"}}},
        session=session,
    )

    return {"envelope_id": envelope_id}


def consultar_solicitacao(envelope_id: str, token: str, session: requests.Session | None = None) -> dict:
    """Consulta status atual de um envelope — fallback caso o webhook não chegue."""
    resultado = _request_clicksign("GET", f"/envelopes/{envelope_id}", token, session=session)
    return resultado.get("data", {}).get("attributes", {})


def baixar_documento_assinado(envelope_id: str, token: str, session: requests.Session | None = None) -> bytes:
    """Baixa o PDF final assinado de um envelope já concluído."""
    resultado = _request_clicksign("GET", f"/envelopes/{envelope_id}/documents", token, session=session)
    documentos = resultado.get("data") or []
    if not documentos:
        raise AssinaturaError(f"Envelope {envelope_id} não tem documento assinado disponível.")
    download_url = documentos[0].get("attributes", {}).get("downloads", {}).get("signed_file_url")
    if not download_url:
        raise AssinaturaError(f"Envelope {envelope_id} não trouxe URL de download do PDF assinado.")

    session = session or requests.Session()
    try:
        response = session.get(download_url, timeout=_REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        raise AssinaturaError(f"Falha ao baixar PDF assinado do envelope {envelope_id}: {exc}") from exc
    if response.status_code >= 400:
        raise AssinaturaError(f"Erro ao baixar PDF assinado do envelope {envelope_id} (HTTP {response.status_code})")
    return response.content

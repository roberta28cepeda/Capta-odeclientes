"""Gateway de pagamento de honorários via Asaas (boleto/PIX/cartão).

Usada pela feature de Faturamento de honorários (`server.py`, rota
`/tenants/<id>/financeiro/<id>/gerar-cobranca`) pra gerar uma cobrança
real — hoje `Honorario` é só um registro manual de controle (sem
gateway nenhum); isso adiciona a opção de gerar boleto/PIX/cartão de
verdade e acompanhar o pagamento via webhook, sem obrigar o uso (quem
não configurar `ASAAS_API_KEY` continua marcando pago manualmente).

Mesmo padrão de `infosimples.py`/`clicksign.py`: uma classe de erro
dedicada, um helper privado que todo público usa, a API key sempre
recebida como parâmetro explícito (nunca lida de env var dentro deste
módulo).

Os paths/payloads exatos abaixo são uma aproximação razoável da API v3
da Asaas — sem credencial disponível neste ambiente pra validar contra
a API real. Confirmar contra a documentação atual
(https://docs.asaas.com/) antes de usar em produção; a forma do módulo
(erro, assinatura de cada função, retorno tipado) já é definitiva.
"""

from __future__ import annotations

import requests

from src.fiscal_monitor.preanalise import only_digits

ASAAS_BASE_URL = "https://api.asaas.com/v3"  # trocar por https://sandbox.asaas.com/api/v3 durante testes
_REQUEST_TIMEOUT_SECONDS = 30


class CobrancaError(RuntimeError):
    """Erro ao criar/consultar cliente ou cobrança na Asaas."""


def _request_asaas(
    method: str, path: str, api_key: str, params: dict | None = None, json_payload: dict | None = None,
    session: requests.Session | None = None,
) -> dict:
    session = session or requests.Session()
    url = f"{ASAAS_BASE_URL}{path}"
    try:
        response = session.request(
            method,
            url,
            headers={"access_token": api_key},
            params=params,
            json=json_payload,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        raise CobrancaError(f"Falha de conexão ao chamar a Asaas ({path}): {exc}") from exc

    try:
        corpo = response.json()
    except ValueError as exc:
        raise CobrancaError(f"Resposta inválida da Asaas (HTTP {response.status_code}) em {path}") from exc

    if response.status_code >= 400:
        erros = corpo.get("errors") or []
        mensagem = "; ".join(erro.get("description", "") for erro in erros) or corpo.get("message") or str(corpo)
        raise CobrancaError(f"Erro da Asaas (HTTP {response.status_code}) em {path}: {mensagem}")

    return corpo


def obter_ou_criar_cliente(
    nome: str, cnpj: str, email: str | None, api_key: str, session: requests.Session | None = None,
) -> str:
    """Busca o cliente Asaas por CNPJ (idempotente); cria se não existir.
    Retorna o `customer_id` da Asaas."""
    cnpj_limpo = only_digits(cnpj)
    encontrados = _request_asaas(
        "GET", "/customers", api_key, params={"cpfCnpj": cnpj_limpo}, session=session
    )
    existentes = encontrados.get("data") or []
    if existentes:
        return existentes[0]["id"]

    payload = {"name": nome, "cpfCnpj": cnpj_limpo}
    if email:
        payload["email"] = email
    criado = _request_asaas("POST", "/customers", api_key, json_payload=payload, session=session)
    return criado["id"]


def criar_cobranca(
    customer_id: str,
    valor: float,
    vencimento: str,
    descricao: str,
    api_key: str,
    session: requests.Session | None = None,
) -> dict:
    """Cria a cobrança (billingType UNDEFINED — cliente escolhe boleto/PIX/
    cartão no link). Retorna dict com, no mínimo, `id`, `invoiceUrl`, `status`."""
    payload = {
        "customer": customer_id,
        "billingType": "UNDEFINED",
        "value": valor,
        "dueDate": vencimento,
        "description": descricao,
    }
    return _request_asaas("POST", "/payments", api_key, json_payload=payload, session=session)


def consultar_cobranca(payment_id: str, api_key: str, session: requests.Session | None = None) -> dict:
    """Consulta status atual de uma cobrança — fallback caso o webhook não chegue."""
    return _request_asaas("GET", f"/payments/{payment_id}", api_key, session=session)

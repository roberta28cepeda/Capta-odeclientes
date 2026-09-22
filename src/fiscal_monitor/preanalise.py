"""Pré-análise fiscal só com o CNPJ — sem procuração, sem e-CAC.

Resolve uma dor real de prospecção: o cliente não quer dar procuração ou
acesso ao e-CAC antes de fechar contrato. Com só o CNPJ, dá pra puxar o
que já é **público** — situação cadastral, enquadramento no Simples
Nacional/MEI, natureza jurídica — via BrasilAPI, um espelho gratuito e
sem autenticação dos dados que a própria Receita Federal já publica. Gera
um PDF com esse diagnóstico inicial pra usar na reunião de venda, antes de
pedir qualquer acesso.

O que isso **não** traz: pendências, multas e dívidas privadas exigem
procuração eletrônica + e-CAC (ver `providers.py`) — não são dado
público. A pré-análise é só a "porta de entrada".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

BRASILAPI_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"


class ConsultaCnpjError(RuntimeError):
    """Erro ao consultar o CNPJ na BrasilAPI (CNPJ inválido, não encontrado, API fora do ar)."""


@dataclass
class PreAnalise:
    cnpj: str
    razao_social: str
    nome_fantasia: str | None
    situacao_cadastral: str | None
    data_situacao_cadastral: str | None
    natureza_juridica: str | None
    cnae_principal: str | None
    porte: str | None
    uf: str | None
    municipio: str | None
    data_inicio_atividade: str | None
    opcao_pelo_simples: bool | None
    opcao_pelo_mei: bool | None
    capital_social: float | None
    socios: list[str] = field(default_factory=list)


def only_digits(cnpj: str) -> str:
    return "".join(c for c in cnpj if c.isdigit())


def consultar_cnpj_publico(cnpj: str, session: requests.Session | None = None) -> dict:
    """Consulta os dados cadastrais públicos de um CNPJ na BrasilAPI."""
    session = session or requests.Session()
    url = BRASILAPI_URL.format(cnpj=only_digits(cnpj))
    response = session.get(url, timeout=10)
    if response.status_code == 404:
        raise ConsultaCnpjError(f"CNPJ {cnpj} não encontrado.")
    if response.status_code >= 400:
        raise ConsultaCnpjError(f"Erro ao consultar CNPJ {cnpj}: HTTP {response.status_code}")
    return response.json()


def montar_pre_analise(dados: dict) -> PreAnalise:
    socios = [socio.get("nome_socio", "") for socio in dados.get("qsa", []) if socio.get("nome_socio")]
    return PreAnalise(
        cnpj=dados.get("cnpj", ""),
        razao_social=dados.get("razao_social", ""),
        nome_fantasia=dados.get("nome_fantasia") or None,
        situacao_cadastral=dados.get("descricao_situacao_cadastral"),
        data_situacao_cadastral=dados.get("data_situacao_cadastral"),
        natureza_juridica=dados.get("natureza_juridica") or dados.get("descricao_natureza_juridica"),
        cnae_principal=dados.get("cnae_fiscal_descricao"),
        porte=dados.get("descricao_porte") or dados.get("porte"),
        uf=dados.get("uf"),
        municipio=dados.get("municipio"),
        data_inicio_atividade=dados.get("data_inicio_atividade"),
        opcao_pelo_simples=dados.get("opcao_pelo_simples"),
        opcao_pelo_mei=dados.get("opcao_pelo_mei"),
        capital_social=dados.get("capital_social"),
        socios=socios,
    )


def gerar_alertas(analise: PreAnalise) -> list[str]:
    """Alertas conservadores, só com base em dado cadastral público — nada
    de pendência/multa aqui (isso exige procuração, ver providers.py).
    """
    alertas = []

    if analise.situacao_cadastral and analise.situacao_cadastral.strip().upper() != "ATIVA":
        alertas.append(
            f"Situação cadastral: {analise.situacao_cadastral} — não está ATIVA, "
            "vale entender o motivo antes de prosseguir."
        )

    if analise.porte in {"ME", "EPP"} and analise.opcao_pelo_simples is False:
        alertas.append(
            "Empresa de porte ME/EPP mas não optante pelo Simples Nacional — "
            "vale avaliar se o enquadramento tributário atual é o mais vantajoso."
        )

    if not alertas:
        alertas.append("Nenhum alerta cadastral identificado na pré-análise pública.")

    return alertas

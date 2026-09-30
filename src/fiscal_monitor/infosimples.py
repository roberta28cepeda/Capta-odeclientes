"""Situação fiscal e dívida ativa (PGFN/Receita Federal) via InfoSimples.

Complementa a pré-análise cadastral (`preanalise.py`, BrasilAPI/CNPJá) com
dado que só é público via consulta ativa à Receita Federal — não dá pra
puxar de um espelho gratuito como a BrasilAPI. A InfoSimples é uma
revendedora paga que automatiza essas consultas nos sites oficiais e
devolve JSON. Usada só quando `INFOSIMPLES_API_TOKEN` está configurada —
sem isso, a pré-análise segue funcionando normal, só sem essa seção.

Dois produtos, mesma conta/token:

- CND Federal (`/receita-federal/pgfn/nova`): emite uma nova Certidão de
  Débitos Relativos a Créditos Tributários Federais e à Dívida Ativa da
  União — diz se a empresa tem débito ativo na Receita Federal e/ou PGFN.
- Lista de Devedores (`/receita-federal/pgfn/devedores`): consulta se o
  CNPJ está inscrito em dívida ativa da União/FGTS, com o valor detalhado
  por natureza do débito.

Cada chamada tem custo (~R$0,10 + taxa base por consulta, cobrado do
saldo da conta InfoSimples) — por isso só roda quando a integração está
de fato configurada, e uma falha aqui não derruba a pré-análise inteira
(vira só um alerta no PDF).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

from src.fiscal_monitor.preanalise import only_digits

INFOSIMPLES_CND_URL = "https://api.infosimples.com/api/v2/consultas/receita-federal/pgfn/nova"
INFOSIMPLES_DEVEDORES_URL = "https://api.infosimples.com/api/v2/consultas/receita-federal/pgfn/devedores"

# Timeout que a própria InfoSimples usa pra esperar o site de origem (gov.br)
# responder — pode ser lento. Mantido bem abaixo do limite de function do
# Vercel pra não estourar o tempo de resposta de uma requisição interativa.
_INFOSIMPLES_TIMEOUT_PARAM = "60"
_REQUEST_TIMEOUT_SECONDS = 65


class ConsultaDebitosError(RuntimeError):
    """Erro ao consultar situação fiscal/dívida ativa na InfoSimples."""


@dataclass
class SituacaoFiscalPgfn:
    conseguiu_certidao_negativa: bool | None
    tipo_certidao: str | None
    debitos_pgfn: bool | None
    debitos_rfb: bool | None
    mensagem: str | None
    validade_data: str | None


@dataclass
class DebitoInscricao:
    inscricao: str
    valor_divida: float


@dataclass
class NaturezaDebito:
    descricao: str
    total: float
    debitos: list[DebitoInscricao] = field(default_factory=list)


@dataclass
class DividaAtivaPgfn:
    total_divida: float
    total_tributario: float
    total_nao_tributario: float
    naturezas: list[NaturezaDebito] = field(default_factory=list)


def _post_infosimples(url: str, cnpj: str, token: str, session: requests.Session | None = None) -> dict:
    session = session or requests.Session()
    try:
        response = session.post(
            url,
            data={"cnpj": only_digits(cnpj), "token": token, "timeout": _INFOSIMPLES_TIMEOUT_PARAM},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        raise ConsultaDebitosError(f"Falha de conexão ao consultar {url}: {exc}") from exc

    try:
        corpo = response.json()
    except ValueError as exc:
        raise ConsultaDebitosError(f"Resposta inválida da InfoSimples (HTTP {response.status_code}) em {url}") from exc

    if corpo.get("code") != 200:
        mensagem = corpo.get("code_message") or "; ".join(corpo.get("errors") or []) or "erro desconhecido"
        raise ConsultaDebitosError(f"Erro na consulta InfoSimples (código {corpo.get('code')}): {mensagem}")

    return corpo


def consultar_cnd_federal(cnpj: str, token: str, session: requests.Session | None = None) -> dict:
    """Consulta a CND Federal (situação de débitos PGFN/Receita Federal) na InfoSimples."""
    corpo = _post_infosimples(INFOSIMPLES_CND_URL, cnpj, token, session=session)
    dados = corpo.get("data") or []
    return dados[0] if dados else {}


def consultar_lista_devedores(cnpj: str, token: str, session: requests.Session | None = None) -> dict | None:
    """Consulta a Lista de Devedores da PGFN na InfoSimples.

    Retorna `None` quando o CNPJ não está inscrito em dívida ativa (a API
    devolve `data_count: 0` nesse caso).
    """
    corpo = _post_infosimples(INFOSIMPLES_DEVEDORES_URL, cnpj, token, session=session)
    dados = corpo.get("data") or []
    return dados[0] if dados else None


def montar_situacao_fiscal(dados: dict) -> SituacaoFiscalPgfn:
    return SituacaoFiscalPgfn(
        conseguiu_certidao_negativa=dados.get("conseguiu_emitir_certidao_negativa"),
        tipo_certidao=dados.get("tipo"),
        debitos_pgfn=dados.get("debitos_pgfn"),
        debitos_rfb=dados.get("debitos_rfb"),
        mensagem=dados.get("mensagem"),
        validade_data=dados.get("validade_data"),
    )


def montar_divida_ativa(dados: dict | None) -> DividaAtivaPgfn | None:
    if not dados:
        return None
    naturezas = [
        NaturezaDebito(
            descricao=natureza.get("descricao", ""),
            total=natureza.get("total", 0.0),
            debitos=[
                DebitoInscricao(inscricao=debito.get("inscricao", ""), valor_divida=debito.get("valor_divida", 0.0))
                for debito in natureza.get("debitos", [])
            ],
        )
        for natureza in dados.get("naturezas_debitos", [])
    ]
    return DividaAtivaPgfn(
        total_divida=dados.get("total_divida", 0.0),
        total_tributario=dados.get("total_tributario", 0.0),
        total_nao_tributario=dados.get("total_nao_tributario", 0.0),
        naturezas=naturezas,
    )


def formatar_valor_brl(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def gerar_alertas_fiscais(
    situacao_fiscal: SituacaoFiscalPgfn | None, divida_ativa: DividaAtivaPgfn | None
) -> list[str]:
    """Alertas com base em débito/dívida ativa real — complementa
    `preanalise.gerar_alertas`, que só olha dado cadastral.
    """
    alertas = []

    if situacao_fiscal and situacao_fiscal.debitos_pgfn:
        alertas.append("Débitos ativos identificados na PGFN (Dívida Ativa da União).")
    if situacao_fiscal and situacao_fiscal.debitos_rfb:
        alertas.append("Débitos ativos identificados na Receita Federal.")

    if divida_ativa and divida_ativa.total_divida:
        alertas.append(
            f"Inscrito na Lista de Devedores da PGFN — dívida ativa total de "
            f"R$ {formatar_valor_brl(divida_ativa.total_divida)}."
        )

    return alertas

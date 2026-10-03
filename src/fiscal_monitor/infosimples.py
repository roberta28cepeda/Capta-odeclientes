"""Situação fiscal e dívida ativa (PGFN/Receita Federal) via InfoSimples.

Complementa a pré-análise cadastral (`preanalise.py`, BrasilAPI/CNPJá) com
dado que só é público via consulta ativa à Receita Federal — não dá pra
puxar de um espelho gratuito como a BrasilAPI. A InfoSimples é uma
revendedora paga que automatiza essas consultas nos sites oficiais e
devolve JSON. Usada só quando `INFOSIMPLES_API_TOKEN` está configurada —
sem isso, a pré-análise segue funcionando normal, só sem essa seção.

Quatro produtos, mesma conta/token:

- CND Federal (`/receita-federal/pgfn/nova`): emite uma nova Certidão de
  Débitos Relativos a Créditos Tributários Federais e à Dívida Ativa da
  União — diz se a empresa tem débito ativo na Receita Federal e/ou PGFN.
- Lista de Devedores (`/receita-federal/pgfn/devedores`): consulta se o
  CNPJ está inscrito em dívida ativa da União/FGTS, com o valor detalhado
  por natureza do débito.
- Regularidade do FGTS (`/caixa/regularidade`): Certificado de
  Regularidade do FGTS (CRF) — diz se o empregador está regular perante a
  Caixa.
- CNDT (`/tst/cndt`): Certidão Negativa de Débitos Trabalhistas do TST —
  diz se há débito/processo trabalhista em aberto.

Cada chamada tem custo (~R$0,10 + taxa base por consulta, cobrado do
saldo da conta InfoSimples) — por isso só roda quando a integração está
de fato configurada, e uma falha em qualquer uma delas não derruba a
pré-análise inteira nem bloqueia as outras consultas (cada uma roda e
falha de forma independente; uma falha vira só um alerta no PDF).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

from src.fiscal_monitor.preanalise import only_digits

INFOSIMPLES_CND_URL = "https://api.infosimples.com/api/v2/consultas/receita-federal/pgfn/nova"
INFOSIMPLES_DEVEDORES_URL = "https://api.infosimples.com/api/v2/consultas/receita-federal/pgfn/devedores"
INFOSIMPLES_FGTS_URL = "https://api.infosimples.com/api/v2/consultas/caixa/regularidade"
INFOSIMPLES_CNDT_URL = "https://api.infosimples.com/api/v2/consultas/tst/cndt"

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
    # Preenchidos depois, via `enriquecer_com_dados_abertos`, cruzando com a
    # base dos Dados Abertos da PGFN (ver `pgfn_dados_abertos.py`) — a
    # consulta "Lista de Devedores" acima não traz essas duas informações.
    data_inscricao: str | None = None
    situacao_inscricao: str | None = None
    ajuizada: bool | None = None


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


@dataclass
class SituacaoFgts:
    situacao: str | None
    validade_inicio_data: str | None
    validade_fim_data: str | None


@dataclass
class SituacaoCndt:
    consta_debito: bool | None
    total_processos: int | None
    certidao_codigo: str | None
    validade_data: str | None


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


def consultar_regularidade_fgts(cnpj: str, token: str, session: requests.Session | None = None) -> dict:
    """Consulta o Certificado de Regularidade do FGTS (CRF) na InfoSimples."""
    corpo = _post_infosimples(INFOSIMPLES_FGTS_URL, cnpj, token, session=session)
    dados = corpo.get("data") or []
    return dados[0] if dados else {}


def consultar_cndt_trabalhista(cnpj: str, token: str, session: requests.Session | None = None) -> dict:
    """Consulta a CNDT (Certidão Negativa de Débitos Trabalhistas) na InfoSimples."""
    corpo = _post_infosimples(INFOSIMPLES_CNDT_URL, cnpj, token, session=session)
    dados = corpo.get("data") or []
    return dados[0] if dados else {}


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


def montar_situacao_fgts(dados: dict) -> SituacaoFgts:
    return SituacaoFgts(
        situacao=dados.get("situacao"),
        validade_inicio_data=dados.get("validade_inicio_data"),
        validade_fim_data=dados.get("validade_fim_data"),
    )


def montar_situacao_cndt(dados: dict) -> SituacaoCndt:
    return SituacaoCndt(
        consta_debito=dados.get("consta"),
        total_processos=dados.get("total_de_processos"),
        certidao_codigo=dados.get("certidao_codigo"),
        validade_data=dados.get("validade_data"),
    )


def formatar_valor_brl(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


# Situações da PGFN (campo `SITUACAO_INSCRICAO` dos Dados Abertos) que
# indicam execução fiscal já ajuizada — além do indicador binário
# `INDICADOR_AJUIZADO`, que já cobre a maioria dos casos.
_SITUACOES_AJUIZADAS = {"AJUIZADA", "AJUIZ PARCELADA", "OUTROS AJUIZADA"}
_SITUACOES_PROTESTADAS = {"PROTESTADA"}


def enriquecer_com_dados_abertos(conn, divida_ativa: DividaAtivaPgfn | None) -> DividaAtivaPgfn | None:
    """Completa cada `DebitoInscricao` da Lista de Devedores com data de
    inscrição e situação, cruzando pelo número de inscrição com a base dos
    Dados Abertos da PGFN já importada (ver `pgfn_dados_abertos.py`). Sem
    import feito ainda, ou sem bater nenhuma inscrição, não muda nada.
    """
    if divida_ativa is None:
        return None

    from src.fiscal_monitor import storage

    numeros = [debito.inscricao for natureza in divida_ativa.naturezas for debito in natureza.debitos]
    dados_por_inscricao = storage.buscar_dados_abertos_por_inscricoes(conn, numeros)
    if not dados_por_inscricao:
        return divida_ativa

    for natureza in divida_ativa.naturezas:
        for debito in natureza.debitos:
            dados = dados_por_inscricao.get(debito.inscricao)
            if dados:
                debito.data_inscricao = dados["data_inscricao"]
                debito.situacao_inscricao = dados["situacao_inscricao"]
                debito.ajuizada = bool(dados["indicador_ajuizado"]) or dados["situacao_inscricao"] in _SITUACOES_AJUIZADAS

    return divida_ativa


def gerar_alertas_fiscais(
    situacao_fiscal: SituacaoFiscalPgfn | None,
    divida_ativa: DividaAtivaPgfn | None,
    situacao_fgts: SituacaoFgts | None = None,
    situacao_cndt: SituacaoCndt | None = None,
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

    if divida_ativa:
        debitos = [debito for natureza in divida_ativa.naturezas for debito in natureza.debitos]
        ajuizadas = [d for d in debitos if d.ajuizada]
        protestadas = [d for d in debitos if d.situacao_inscricao in _SITUACOES_PROTESTADAS]
        if ajuizadas:
            alertas.append(
                f"{len(ajuizadas)} inscrição(ões) já ajuizada(s) (execução fiscal em curso) — "
                "cruzado com os Dados Abertos da PGFN."
            )
        if protestadas:
            alertas.append(
                f"{len(protestadas)} inscrição(ões) já protestada(s) em cartório pela PGFN — "
                "cruzado com os Dados Abertos da PGFN."
            )

    if situacao_fgts and situacao_fgts.situacao and situacao_fgts.situacao.strip().upper() != "REGULAR":
        alertas.append(f"Situação irregular perante o FGTS (CRF — Caixa): {situacao_fgts.situacao}.")

    if situacao_cndt and situacao_cndt.consta_debito:
        detalhe = f" ({situacao_cndt.total_processos} processo(s))" if situacao_cndt.total_processos else ""
        alertas.append(f"Débitos trabalhistas identificados na Justiça do Trabalho (CNDT/TST){detalhe}.")

    return alertas

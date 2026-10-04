"""Fonte de dados fiscais, plugável.

Não existe API oficial para consultar pendências/multas ou emitir guias
DAS em nome de terceiros — a Veri e concorrentes automatizam o
**e-CAC/DCTFWeb** usando o certificado digital (A1/A3) de cada cliente
contábil, algo sensível o bastante (acesso a sistemas do governo em nome
de terceiros) para não improvisar aqui sem definição jurídica e sem um
certificado real pra testar contra.

`FiscalDataProvider` é o ponto de extensão para quando essa integração
existir. Por enquanto o único provider é o `ManualFiscalProvider`, que lê
achados de um CSV — exportado manualmente do e-CAC pelo escritório, ou
gerado por qualquer scraper que ele já use. O sistema não assume a origem
do CSV, só organiza e valida os dados.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Protocol

ESFERAS = {"federal", "estadual", "municipal"}
TIPOS = {"pendencia", "multa", "notificacao", "das", "cnd", "parcelamento", "caixa_postal"}

# Para "cnd" e "parcelamento", o campo `vencimento` do RawFinding é a data de
# validade (CND) ou de vencimento da próxima parcela — mesmo campo, semântica
# um pouco diferente por tipo. Ver monitor.py para a lógica de alerta de cada um.


@dataclass
class RawFinding:
    cnpj: str
    esfera: str
    tipo: str
    descricao: str
    valor: float | None
    vencimento: str | None  # data ISO "YYYY-MM-DD", ou None
    pago: bool


class FiscalDataProvider(Protocol):
    name: str

    def fetch(self, cnpjs: list[str] | None = None) -> dict[str, list[RawFinding]]:
        """Retorna os achados fiscais por CNPJ. `cnpjs=None` busca todos os disponíveis."""
        ...


def _parse_optional_float(value: str | None) -> float | None:
    value = (value or "").strip()
    return float(value) if value else None


def _parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "sim", "s", "yes"}


class ManualFiscalProvider:
    """Lê achados fiscais de um CSV com colunas:
    cnpj,esfera,tipo,descricao,valor,vencimento,pago
    """

    name = "manual_csv"

    def __init__(self, csv_path: str):
        self.csv_path = csv_path

    def fetch(self, cnpjs: list[str] | None = None) -> dict[str, list[RawFinding]]:
        result: dict[str, list[RawFinding]] = {}
        with open(self.csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):  # linha 1 é o cabeçalho
                cnpj = (row.get("cnpj") or "").strip()
                if not cnpj:
                    continue
                if cnpjs is not None and cnpj not in cnpjs:
                    continue

                esfera = (row.get("esfera") or "").strip().lower()
                if esfera not in ESFERAS:
                    raise ValueError(
                        f"Linha {i}: esfera '{esfera}' inválida — use uma de {sorted(ESFERAS)}."
                    )
                tipo = (row.get("tipo") or "").strip().lower()
                if tipo not in TIPOS:
                    raise ValueError(f"Linha {i}: tipo '{tipo}' inválido — use um de {sorted(TIPOS)}.")

                result.setdefault(cnpj, []).append(
                    RawFinding(
                        cnpj=cnpj,
                        esfera=esfera,
                        tipo=tipo,
                        descricao=(row.get("descricao") or "").strip(),
                        valor=_parse_optional_float(row.get("valor")),
                        vencimento=(row.get("vencimento") or "").strip() or None,
                        pago=_parse_bool(row.get("pago")),
                    )
                )
        return result


def _parse_data_br(value: str | None) -> str | None:
    """Converte data no formato DD/MM/YYYY (como a InfoSimples devolve) pra
    ISO YYYY-MM-DD (formato que `monitor.days_until` espera). `None` se o
    valor estiver vazio ou num formato inesperado.
    """
    value = (value or "").strip()
    if not value:
        return None
    partes = value.split("/")
    if len(partes) != 3:
        return None
    dia, mes, ano = partes
    try:
        return f"{int(ano):04d}-{int(mes):02d}-{int(dia):02d}"
    except ValueError:
        return None


class InfoSimplesFiscalProvider:
    """Provider automático: consulta CND federal, dívida ativa (Lista de
    Devedores da PGFN), FGTS e CNDT via InfoSimples pra cada CNPJ — a
    mesma fonte usada na pré-análise de lead e no dossiê fiscal da
    carteira (`server.py`), mas aqui alimentando o motor de diff/alerta
    (`monitor.py`) como qualquer outro provider: um achado novo vira
    alerta de verdade (WhatsApp/e-mail) e some quando regularizado.

    Pensado pra rodar uma vez por semana (ver o gate em
    `cron.run_infosimples_semanal`/`server.cron_check_all`), não todo
    dia — cada consulta tem custo. Uma falha numa das quatro consultas
    pra um CNPJ não impede as outras três (mesmo padrão já usado na
    pré-análise e no dossiê fiscal).
    """

    name = "infosimples_semanal"

    def __init__(self, token: str):
        self.token = token

    def fetch(self, cnpjs: list[str] | None = None) -> dict[str, list[RawFinding]]:
        if not cnpjs:
            return {}

        from src.fiscal_monitor.infosimples import (
            ConsultaDebitosError,
            consultar_cnd_federal,
            consultar_cndt_trabalhista,
            consultar_lista_devedores,
            consultar_regularidade_fgts,
        )

        result: dict[str, list[RawFinding]] = {}
        for cnpj in cnpjs:
            findings: list[RawFinding] = []

            try:
                dados_cnd = consultar_cnd_federal(cnpj, self.token)
                if dados_cnd.get("debitos_pgfn") or dados_cnd.get("debitos_rfb"):
                    findings.append(
                        RawFinding(
                            cnpj=cnpj,
                            esfera="federal",
                            tipo="pendencia",
                            descricao="Débito ativo identificado na CND federal (Receita Federal/PGFN)",
                            valor=None,
                            vencimento=None,
                            pago=False,
                        )
                    )
                validade = _parse_data_br(dados_cnd.get("validade_data"))
                if validade:
                    findings.append(
                        RawFinding(
                            cnpj=cnpj,
                            esfera="federal",
                            tipo="cnd",
                            descricao=f"Certidão {dados_cnd.get('tipo') or 'federal'}",
                            valor=None,
                            vencimento=validade,
                            pago=False,
                        )
                    )
            except ConsultaDebitosError:
                pass

            try:
                dados_devedores = consultar_lista_devedores(cnpj, self.token)
                if dados_devedores:
                    for natureza in dados_devedores.get("naturezas_debitos", []) or []:
                        for debito in natureza.get("debitos", []) or []:
                            findings.append(
                                RawFinding(
                                    cnpj=cnpj,
                                    esfera="federal",
                                    tipo="pendencia",
                                    descricao=(
                                        f"Dívida ativa PGFN ({natureza.get('descricao', '')}) — "
                                        f"inscrição {debito.get('inscricao', '')}"
                                    ),
                                    valor=debito.get("valor_divida"),
                                    vencimento=None,
                                    pago=False,
                                )
                            )
            except ConsultaDebitosError:
                pass

            try:
                dados_fgts = consultar_regularidade_fgts(cnpj, self.token)
                situacao = (dados_fgts.get("situacao") or "").strip()
                if situacao and situacao.upper() != "REGULAR":
                    findings.append(
                        RawFinding(
                            cnpj=cnpj,
                            esfera="federal",
                            tipo="pendencia",
                            descricao=f"FGTS irregular (CRF — Caixa): {situacao}",
                            valor=None,
                            vencimento=None,
                            pago=False,
                        )
                    )
            except ConsultaDebitosError:
                pass

            try:
                dados_cndt = consultar_cndt_trabalhista(cnpj, self.token)
                if dados_cndt.get("consta"):
                    total = dados_cndt.get("total_de_processos")
                    descricao = "Débito trabalhista identificado (CNDT/TST)"
                    if total:
                        descricao += f" — {total} processo(s)"
                    findings.append(
                        RawFinding(
                            cnpj=cnpj,
                            esfera="federal",
                            tipo="pendencia",
                            descricao=descricao,
                            valor=None,
                            vencimento=None,
                            pago=False,
                        )
                    )
            except ConsultaDebitosError:
                pass

            result[cnpj] = findings

        return result


class SerproIntegraContadorProvider:
    """Ponto de extensão pra integração real — não implementado.

    A Veri e concorrentes puxam dado ao vivo do e-CAC via **Serpro Integra
    Contador**, o canal oficial homologado pela Receita Federal (não é
    scraping). Pra ativar isso de verdade falta:

    1. Contrato de consumo com o Serpro (é pago por chamada de API).
    2. Procuração eletrônica assinada pelo cliente contábil, autorizando o
       escritório a consultar os dados fiscais dele via essa API.
    3. Certificado digital (e-CNPJ) do escritório, usado pra autenticar as
       chamadas.

    Sem essas três coisas em mãos não dá pra implementar `fetch()` de forma
    testável — por isso ele levanta `NotImplementedError`. Use
    `ManualFiscalProvider` enquanto isso. Ver README.md.
    """

    name = "serpro_integra_contador"

    def __init__(self, *, consumer_key: str, consumer_secret: str, certificado_path: str):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.certificado_path = certificado_path

    def fetch(self, cnpjs: list[str] | None = None) -> dict[str, list[RawFinding]]:
        raise NotImplementedError(
            "Integração Serpro Integra Contador ainda não implementada — requer "
            "contrato de consumo com o Serpro, procuração eletrônica do cliente "
            "e certificado digital do escritório. Use ManualFiscalProvider "
            "enquanto isso. Ver README.md."
        )


def import_portfolio_csv(conn, tenant_id: int, csv_file) -> tuple[int, str | None]:
    """Importa a carteira de CNPJs de um arquivo CSV já aberto
    (colunas: cnpj,razao_social,nome_fantasia,regime_tributario,uf — as
    duas últimas são opcionais; `uf` define quais certidões estaduais são
    exigidas pra cada empresa, ver `risco.py`).

    Compartilhado entre o CLI (`--import-portfolio`) e o formulário web de
    cadastro de escritório, pra não duplicar a validação. Retorna
    (quantidade importada, mensagem de erro ou None — para na primeira
    linha inválida, sem importar o resto).
    """
    from src.fiscal_monitor import storage

    count = 0
    for row in csv.DictReader(csv_file):
        cnpj = (row.get("cnpj") or "").strip()
        if not cnpj:
            continue
        regime = (row.get("regime_tributario") or "").strip().lower() or None
        if regime is not None and regime not in storage.REGIMES_TRIBUTARIOS:
            return count, (
                f"regime_tributario '{regime}' inválido pro CNPJ {cnpj} — "
                f"use um de {sorted(storage.REGIMES_TRIBUTARIOS)}."
            )
        storage.upsert_cnpj(
            conn,
            tenant_id,
            cnpj,
            razao_social=(row.get("razao_social") or "").strip() or None,
            nome_fantasia=(row.get("nome_fantasia") or "").strip() or None,
            regime_tributario=regime,
            uf=(row.get("uf") or "").strip().upper() or None,
        )
        count += 1
    return count, None

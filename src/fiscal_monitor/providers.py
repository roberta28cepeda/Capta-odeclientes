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

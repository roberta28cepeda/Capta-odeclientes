"""Importa os Dados Abertos da PGFN (dívida ativa da União/FGTS) pra
enriquecer a pré-análise com informação que a consulta ao vivo (InfoSimples
"Lista de Devedores") não traz: data de inscrição e se já foi ajuizada ou
protestada.

É uma base diferente da "Lista de Devedores" (consulta pública por CNPJ,
ver `infosimples.py`) — os Dados Abertos são um arquivo bruto (CSV ou
XLSX), publicado trimestralmente pela PGFN sem exigir login, com uma linha
por **inscrição** em dívida ativa (não por empresa), em
`gov.br/pgfn` → Acesso à Informação → Dados Abertos. Confirmado contra um
arquivo real: as colunas usadas aqui existem de fato (`CPF_CNPJ`,
`NUMERO_INSCRICAO`, `DATA_INSCRICAO`, `SITUACAO_INSCRICAO`,
`INDICADOR_AJUIZADO`, `VALOR_CONSOLIDADO`, entre outras).

Não existe API — é download manual, repetido a cada trimestre quando a
PGFN publica uma base nova (ver `--import-pgfn-dados-abertos` no CLI).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import BinaryIO, Iterator

CABECALHO_ESPERADO = {
    "CPF_CNPJ",
    "TIPO_PESSOA",
    "NUMERO_INSCRICAO",
    "SITUACAO_INSCRICAO",
    "DATA_INSCRICAO",
    "INDICADOR_AJUIZADO",
    "VALOR_CONSOLIDADO",
}


class ArquivoDadosAbertosError(ValueError):
    """Arquivo de Dados Abertos da PGFN com formato inesperado."""


def only_digits(valor: str) -> str:
    return "".join(c for c in valor if c.isdigit())


def _parse_data(valor) -> str | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (date, datetime)):
        return valor.date().isoformat() if isinstance(valor, datetime) else valor.isoformat()
    texto = str(valor).strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_valor(valor) -> float | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _normalizar_linha(linha: dict) -> dict | None:
    """Converte uma linha crua (chaves = cabeçalho da PGFN) pro formato de
    upsert em `storage.upsert_dividas_abertas_pgfn`. Retorna `None` pra
    linhas de pessoa física (CPF) ou sem número de inscrição.
    """
    cnpj = only_digits(str(linha.get("CPF_CNPJ") or ""))
    numero_inscricao = str(linha.get("NUMERO_INSCRICAO") or "").strip()
    if len(cnpj) != 14 or not numero_inscricao:
        return None

    return {
        "numero_inscricao": numero_inscricao,
        "cnpj": cnpj,
        "uf": (str(linha.get("UF_DEVEDOR") or "").strip() or None),
        "receita_principal": (str(linha.get("RECEITA_PRINCIPAL") or "").strip() or None),
        "situacao_inscricao": str(linha.get("SITUACAO_INSCRICAO") or "").strip() or "DESCONHECIDA",
        "data_inscricao": _parse_data(linha.get("DATA_INSCRICAO")),
        "indicador_ajuizado": str(linha.get("INDICADOR_AJUIZADO") or "").strip().upper() == "SIM",
        "valor_consolidado": _parse_valor(linha.get("VALOR_CONSOLIDADO")),
    }


def _ler_linhas_xlsx(arquivo: BinaryIO) -> Iterator[dict]:
    import openpyxl

    workbook = openpyxl.load_workbook(arquivo, read_only=True, data_only=True)
    planilha = workbook.worksheets[0]
    linhas = planilha.iter_rows(values_only=True)
    cabecalho = next(linhas, None)
    if not cabecalho:
        raise ArquivoDadosAbertosError("Planilha vazia — sem linha de cabeçalho.")
    colunas = [str(c or "").strip().upper() for c in cabecalho]
    if not CABECALHO_ESPERADO.issubset(set(colunas)):
        faltando = CABECALHO_ESPERADO - set(colunas)
        raise ArquivoDadosAbertosError(
            f"Colunas esperadas não encontradas no arquivo: {sorted(faltando)}. "
            "Confira se é mesmo um arquivo de Dados Abertos da PGFN (não a 'Lista de Devedores')."
        )
    for linha in linhas:
        yield dict(zip(colunas, linha))


def _ler_linhas_csv(arquivo: BinaryIO) -> Iterator[dict]:
    bruto = arquivo.read()
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("latin1")
    delimitador = ";" if texto.split("\n", 1)[0].count(";") >= texto.split("\n", 1)[0].count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
    colunas = {str(c or "").strip().upper() for c in (leitor.fieldnames or [])}
    if not CABECALHO_ESPERADO.issubset(colunas):
        faltando = CABECALHO_ESPERADO - colunas
        raise ArquivoDadosAbertosError(
            f"Colunas esperadas não encontradas no arquivo: {sorted(faltando)}. "
            "Confira se é mesmo um arquivo de Dados Abertos da PGFN (não a 'Lista de Devedores')."
        )
    for linha in leitor:
        yield {str(k or "").strip().upper(): v for k, v in linha.items()}


def ler_registros(arquivo: BinaryIO, nome_arquivo: str) -> Iterator[dict]:
    """Lê um arquivo de Dados Abertos da PGFN (.xlsx ou .csv) e gera um dict
    normalizado por inscrição, já pronto pra `storage.upsert_dividas_abertas_pgfn`.
    Ignora linhas de pessoa física e sem número de inscrição.
    """
    leitor = _ler_linhas_xlsx if nome_arquivo.lower().endswith(".xlsx") else _ler_linhas_csv
    for linha in leitor(arquivo):
        registro = _normalizar_linha(linha)
        if registro is not None:
            yield registro


def importar_arquivo(conn, arquivo: BinaryIO, nome_arquivo: str, base_referencia: str) -> int:
    """Importa um arquivo de Dados Abertos da PGFN pro banco (upsert por
    número de inscrição — reimportar uma base mais nova atualiza o status).
    """
    from src.fiscal_monitor import storage

    registros = list(ler_registros(arquivo, nome_arquivo))
    if not registros:
        return 0
    return storage.upsert_dividas_abertas_pgfn(conn, registros, base_referencia)

import io
from datetime import date

import openpyxl
import pytest

from src.fiscal_monitor.pgfn_dados_abertos import (
    ArquivoDadosAbertosError,
    importar_arquivo,
    ler_registros,
)
from src.fiscal_monitor.storage import buscar_dados_abertos_por_inscricoes, connect

_CABECALHO = [
    "CPF_CNPJ", "TIPO_PESSOA", "TIPO_DEVEDOR", "NOME_DEVEDOR", "UF_DEVEDOR", "UNIDADE_RESPONSAVEL",
    "ENTIDADE_RESPONSAVEL", "UNIDADE_INSCRICAO", "NUMERO_INSCRICAO", "TIPO_SITUACAO_INSCRICAO",
    "SITUACAO_INSCRICAO", "RECEITA_PRINCIPAL", "DATA_INSCRICAO", "INDICADOR_AJUIZADO", "VALOR_CONSOLIDADO",
]


def _linha_pj(cnpj="08.612.624/0001-71", numero="FGAL202500237", situacao="INSCRITA", ajuizado="NAO",
              data_inscricao=date(2025, 1, 8), valor="7359.68"):
    return [
        cnpj, "Pessoa jurídica", "Principal", "EMPRESA EXEMPLO LTDA", "AL", "ALAGOAS", "PGFN", "ALAGOAS",
        numero, "Em cobrança", situacao, "Contribuições FGTS", data_inscricao, ajuizado, valor,
    ]


def _montar_xlsx_bytes(linhas: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(_CABECALHO)
    for linha in linhas:
        sheet.append(linha)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_ler_registros_xlsx_normaliza_cnpj_data_e_ajuizado():
    conteudo = _montar_xlsx_bytes([_linha_pj()])

    registros = list(ler_registros(io.BytesIO(conteudo), "arquivo_lai_FGTS_5_202603.xlsx"))

    assert len(registros) == 1
    registro = registros[0]
    assert registro["cnpj"] == "08612624000171"
    assert registro["numero_inscricao"] == "FGAL202500237"
    assert registro["data_inscricao"] == "2025-01-08"
    assert registro["indicador_ajuizado"] is False
    assert registro["situacao_inscricao"] == "INSCRITA"
    assert registro["valor_consolidado"] == pytest.approx(7359.68)


def test_ler_registros_xlsx_marca_ajuizado_sim():
    conteudo = _montar_xlsx_bytes([_linha_pj(ajuizado="SIM", situacao="AJUIZADA")])

    registros = list(ler_registros(io.BytesIO(conteudo), "arquivo.xlsx"))

    assert registros[0]["indicador_ajuizado"] is True
    assert registros[0]["situacao_inscricao"] == "AJUIZADA"


def test_ler_registros_xlsx_ignora_pessoa_fisica():
    conteudo = _montar_xlsx_bytes(
        [
            ["123.456.789-00", "Pessoa física", "Principal", "FULANO", "AL", "ALAGOAS", "PGFN", "ALAGOAS",
             "FGAL1", "Em cobrança", "INSCRITA", "FGTS", date(2025, 1, 1), "NAO", "100.00"],
            _linha_pj(numero="FGAL2"),
        ]
    )

    registros = list(ler_registros(io.BytesIO(conteudo), "arquivo.xlsx"))

    assert len(registros) == 1
    assert registros[0]["numero_inscricao"] == "FGAL2"


def test_ler_registros_xlsx_sem_colunas_esperadas_levanta_erro():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["CPF/CNPJ", "Nome", "Valor Total"])  # formato da "Lista de Devedores", não dos Dados Abertos
    sheet.append(["11.222.333/0001-44", "Empresa X", "1.000,00"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    with pytest.raises(ArquivoDadosAbertosError, match="Colunas esperadas"):
        list(ler_registros(io.BytesIO(buffer.getvalue()), "lista_devedores.xlsx"))


def test_ler_registros_csv_formato_pt_br():
    conteudo = (
        "CPF_CNPJ;TIPO_PESSOA;NUMERO_INSCRICAO;SITUACAO_INSCRICAO;DATA_INSCRICAO;INDICADOR_AJUIZADO;"
        "VALOR_CONSOLIDADO;UF_DEVEDOR;RECEITA_PRINCIPAL\n"
        "08.612.624/0001-71;Pessoa jurídica;FGAL1;PROTESTADA;07/07/2016;NAO;7.359,68;AL;Contribuições FGTS\n"
    ).encode("latin1")

    registros = list(ler_registros(io.BytesIO(conteudo), "arquivo.csv"))

    assert len(registros) == 1
    assert registros[0]["data_inscricao"] == "2016-07-07"
    assert registros[0]["valor_consolidado"] == pytest.approx(7359.68)
    assert registros[0]["situacao_inscricao"] == "PROTESTADA"


def test_importar_arquivo_grava_no_banco_e_fica_buscavel():
    conn = connect(":memory:")
    conteudo = _montar_xlsx_bytes([_linha_pj(numero="FGAL999")])

    quantidade = importar_arquivo(conn, io.BytesIO(conteudo), "arquivo.xlsx", "2026-03")

    assert quantidade == 1
    resultado = buscar_dados_abertos_por_inscricoes(conn, ["FGAL999"])
    assert resultado["FGAL999"]["situacao_inscricao"] == "INSCRITA"
    assert resultado["FGAL999"]["indicador_ajuizado"] is False


def test_importar_arquivo_upsert_atualiza_situacao_existente():
    conn = connect(":memory:")
    importar_arquivo(conn, io.BytesIO(_montar_xlsx_bytes([_linha_pj(numero="FGAL999")])), "arquivo.xlsx", "2025-12")

    importar_arquivo(
        conn,
        io.BytesIO(_montar_xlsx_bytes([_linha_pj(numero="FGAL999", situacao="AJUIZADA", ajuizado="SIM")])),
        "arquivo.xlsx",
        "2026-03",
    )

    resultado = buscar_dados_abertos_por_inscricoes(conn, ["FGAL999"])
    assert resultado["FGAL999"]["situacao_inscricao"] == "AJUIZADA"
    assert resultado["FGAL999"]["indicador_ajuizado"] is True

import io
import os
import tempfile

import pytest

from src.fiscal_monitor import storage
from unittest.mock import patch

from src.fiscal_monitor.infosimples import ConsultaDebitosError
from src.fiscal_monitor.providers import (
    InfoSimplesFiscalProvider,
    ManualFiscalProvider,
    SerproIntegraContadorProvider,
    import_portfolio_csv,
)

VALID_CSV = """cnpj,esfera,tipo,descricao,valor,vencimento,pago
11.222.333/0001-44,federal,das,DAS competência 08/2026,412.50,2026-09-25,false
55.666.777/0001-88,estadual,multa,Multa por atraso na GIA,1850.00,,false
55.666.777/0001-88,federal,pendencia,Pendência de regularização,,,true
11.222.333/0001-44,federal,cnd,CND Receita Federal,,2026-09-24,false
55.666.777/0001-88,federal,parcelamento,Parcela 4/60 PGFN,620.00,2026-09-30,false
55.666.777/0001-88,federal,caixa_postal,Intimação eletrônica,,,false
"""

INVALID_ESFERA_CSV = """cnpj,esfera,tipo,descricao,valor,vencimento,pago
11.222.333/0001-44,internacional,das,DAS,100,,false
"""

INVALID_TIPO_CSV = """cnpj,esfera,tipo,descricao,valor,vencimento,pago
11.222.333/0001-44,federal,auto-infracao,Algo,100,,false
"""


def _write_csv(tmp: str, content: str) -> str:
    path = os.path.join(tmp, "snapshot.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_fetch_parses_all_rows_grouped_by_cnpj():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_csv(tmp, VALID_CSV)
        result = ManualFiscalProvider(path).fetch()

    assert set(result.keys()) == {"11.222.333/0001-44", "55.666.777/0001-88"}
    das = result["11.222.333/0001-44"][0]
    assert das.esfera == "federal"
    assert das.tipo == "das"
    assert das.valor == 412.50
    assert das.vencimento == "2026-09-25"
    assert das.pago is False

    pendencia = result["55.666.777/0001-88"][1]
    assert pendencia.valor is None
    assert pendencia.vencimento is None
    assert pendencia.pago is True

    cnd = result["11.222.333/0001-44"][1]
    assert cnd.tipo == "cnd"
    assert cnd.vencimento == "2026-09-24"

    parcelamento = result["55.666.777/0001-88"][2]
    assert parcelamento.tipo == "parcelamento"
    assert parcelamento.valor == 620.0

    caixa_postal = result["55.666.777/0001-88"][3]
    assert caixa_postal.tipo == "caixa_postal"


def test_serpro_provider_raises_not_implemented():
    provider = SerproIntegraContadorProvider(
        consumer_key="key", consumer_secret="secret", certificado_path="/tmp/cert.pfx"
    )
    with pytest.raises(NotImplementedError, match="Serpro"):
        provider.fetch()


def test_fetch_filters_by_cnpjs_when_given():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_csv(tmp, VALID_CSV)
        result = ManualFiscalProvider(path).fetch(cnpjs=["11.222.333/0001-44"])

    assert set(result.keys()) == {"11.222.333/0001-44"}


def test_fetch_raises_on_invalid_esfera():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_csv(tmp, INVALID_ESFERA_CSV)
        with pytest.raises(ValueError, match="esfera"):
            ManualFiscalProvider(path).fetch()


def test_fetch_raises_on_invalid_tipo():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_csv(tmp, INVALID_TIPO_CSV)
        with pytest.raises(ValueError, match="tipo"):
            ManualFiscalProvider(path).fetch()


def test_fetch_raises_oserror_on_missing_file():
    with pytest.raises(OSError):
        ManualFiscalProvider("/nao/existe.csv").fetch()


def test_import_portfolio_csv_imports_valid_rows():
    conn = storage.connect(":memory:")
    tenant = storage.create_tenant(conn, "Escritório A")
    csv_file = io.StringIO(
        "cnpj,razao_social,nome_fantasia,regime_tributario\n"
        "11.222.333/0001-44,Contabil Exemplo,Fantasia,simples\n"
        "55.666.777/0001-88,Posto Boa Viagem,,\n"
    )

    count, erro = import_portfolio_csv(conn, tenant.id, csv_file)

    assert erro is None
    assert count == 2
    cnpjs = storage.list_cnpjs(conn, tenant.id)
    assert len(cnpjs) == 2
    assert cnpjs[0].regime_tributario == "simples"
    assert cnpjs[1].regime_tributario is None


def test_import_portfolio_csv_stops_on_invalid_regime():
    conn = storage.connect(":memory:")
    tenant = storage.create_tenant(conn, "Escritório A")
    csv_file = io.StringIO(
        "cnpj,razao_social,nome_fantasia,regime_tributario\n"
        "11.222.333/0001-44,Contabil Exemplo,,regime_invalido\n"
    )

    count, erro = import_portfolio_csv(conn, tenant.id, csv_file)

    assert count == 0
    assert "regime_invalido" in erro
    assert storage.list_cnpjs(conn, tenant.id) == []


def test_import_portfolio_csv_skips_blank_cnpj_rows():
    conn = storage.connect(":memory:")
    tenant = storage.create_tenant(conn, "Escritório A")
    csv_file = io.StringIO("cnpj,razao_social,nome_fantasia,regime_tributario\n,Sem CNPJ,,\n")

    count, erro = import_portfolio_csv(conn, tenant.id, csv_file)

    assert erro is None
    assert count == 0


def test_infosimples_provider_returns_empty_without_cnpjs():
    provider = InfoSimplesFiscalProvider("TOKEN123")
    assert provider.fetch(None) == {}
    assert provider.fetch([]) == {}


def test_infosimples_provider_flags_debitos_and_divida_ativa():
    provider = InfoSimplesFiscalProvider("TOKEN123")
    with patch(
        "src.fiscal_monitor.infosimples.consultar_cnd_federal",
        return_value={"debitos_pgfn": True, "debitos_rfb": False, "tipo": "Positiva", "validade_data": "11/11/2026"},
    ), patch(
        "src.fiscal_monitor.infosimples.consultar_lista_devedores",
        return_value={
            "naturezas_debitos": [
                {"descricao": "FGTS", "debitos": [{"inscricao": "FGAL1", "valor_divida": 7359.68}]}
            ]
        },
    ), patch("src.fiscal_monitor.infosimples.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}), patch(
        "src.fiscal_monitor.infosimples.consultar_cndt_trabalhista", return_value={"consta": False}
    ):
        resultado = provider.fetch(["11.222.333/0001-44"])

    findings = resultado["11.222.333/0001-44"]
    tipos_descricoes = [(f.tipo, f.descricao) for f in findings]
    assert ("pendencia", "Débito ativo identificado na CND federal (Receita Federal/PGFN)") in tipos_descricoes
    assert ("cnd", "Certidão Positiva") in tipos_descricoes
    cnd_finding = next(f for f in findings if f.tipo == "cnd")
    assert cnd_finding.vencimento == "2026-11-11"
    divida_finding = next(f for f in findings if "inscrição FGAL1" in f.descricao)
    assert divida_finding.valor == 7359.68


def test_infosimples_provider_flags_fgts_irregular_e_cndt_com_debito():
    provider = InfoSimplesFiscalProvider("TOKEN123")
    with patch(
        "src.fiscal_monitor.infosimples.consultar_cnd_federal",
        return_value={"debitos_pgfn": False, "debitos_rfb": False, "tipo": "Negativa", "validade_data": ""},
    ), patch("src.fiscal_monitor.infosimples.consultar_lista_devedores", return_value=None), patch(
        "src.fiscal_monitor.infosimples.consultar_regularidade_fgts", return_value={"situacao": "IRREGULAR"}
    ), patch(
        "src.fiscal_monitor.infosimples.consultar_cndt_trabalhista",
        return_value={"consta": True, "total_de_processos": 2},
    ):
        resultado = provider.fetch(["11.222.333/0001-44"])

    descricoes = [f.descricao for f in resultado["11.222.333/0001-44"]]
    assert any("FGTS irregular" in d for d in descricoes)
    assert any("CNDT/TST" in d and "2 processo" in d for d in descricoes)


def test_infosimples_provider_sem_achados_quando_tudo_regular():
    provider = InfoSimplesFiscalProvider("TOKEN123")
    with patch(
        "src.fiscal_monitor.infosimples.consultar_cnd_federal",
        return_value={"debitos_pgfn": False, "debitos_rfb": False, "tipo": "Negativa", "validade_data": ""},
    ), patch("src.fiscal_monitor.infosimples.consultar_lista_devedores", return_value=None), patch(
        "src.fiscal_monitor.infosimples.consultar_regularidade_fgts", return_value={"situacao": "REGULAR"}
    ), patch("src.fiscal_monitor.infosimples.consultar_cndt_trabalhista", return_value={"consta": False}):
        resultado = provider.fetch(["11.222.333/0001-44"])

    assert resultado["11.222.333/0001-44"] == []


def test_infosimples_provider_uma_consulta_falhar_nao_impede_as_outras():
    provider = InfoSimplesFiscalProvider("TOKEN123")
    with patch(
        "src.fiscal_monitor.infosimples.consultar_cnd_federal", side_effect=ConsultaDebitosError("saldo insuficiente")
    ), patch(
        "src.fiscal_monitor.infosimples.consultar_lista_devedores",
        return_value={"naturezas_debitos": [{"descricao": "FGTS", "debitos": [{"inscricao": "X1", "valor_divida": 100.0}]}]},
    ), patch("src.fiscal_monitor.infosimples.consultar_regularidade_fgts", side_effect=ConsultaDebitosError("erro")), patch(
        "src.fiscal_monitor.infosimples.consultar_cndt_trabalhista", return_value={"consta": False}
    ):
        resultado = provider.fetch(["11.222.333/0001-44"])

    findings = resultado["11.222.333/0001-44"]
    assert len(findings) == 1
    assert "inscrição X1" in findings[0].descricao

import io
import os
import tempfile

import pytest

from src.fiscal_monitor import storage
from src.fiscal_monitor.providers import (
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

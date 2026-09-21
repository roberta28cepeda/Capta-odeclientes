import os
import tempfile

import pytest

from src.fiscal_monitor.providers import ManualFiscalProvider

VALID_CSV = """cnpj,esfera,tipo,descricao,valor,vencimento,pago
11.222.333/0001-44,federal,das,DAS competência 08/2026,412.50,2026-09-25,false
55.666.777/0001-88,estadual,multa,Multa por atraso na GIA,1850.00,,false
55.666.777/0001-88,federal,pendencia,Pendência de regularização,,,true
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

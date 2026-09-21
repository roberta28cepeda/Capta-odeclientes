import os
import tempfile

from src.fiscal_monitor.pdf import render_portfolio_report
from src.fiscal_monitor.storage import Cnpj, Finding, Tenant

TENANT = Tenant(id=1, nome="Escritório A", contato_whatsapp=None, plano=None, criado_em="")
CNPJ_COM_ACHADO = Cnpj(id=1, tenant_id=1, cnpj="11.222.333/0001-44", razao_social="Contábil Exemplo", nome_fantasia=None, ativo=True)
CNPJ_SEM_ACHADO = Cnpj(id=2, tenant_id=1, cnpj="55.666.777/0001-88", razao_social="Posto Boa Viagem", nome_fantasia=None, ativo=True)
FINDING = Finding(1, 1, "federal", "das", "DAS 08/2026", 412.5, "2026-09-25", False, "nova")


def test_render_portfolio_report_creates_nonempty_pdf():
    findings_by_cnpj = [(CNPJ_COM_ACHADO, [FINDING]), (CNPJ_SEM_ACHADO, [])]

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "relatorio_fiscal.pdf")
        render_portfolio_report(TENANT, findings_by_cnpj, path)

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"


def test_render_portfolio_report_handles_empty_portfolio():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "relatorio_fiscal.pdf")
        render_portfolio_report(TENANT, [], path)

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0

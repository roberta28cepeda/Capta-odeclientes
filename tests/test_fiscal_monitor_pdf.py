import os
import tempfile

from src.fiscal_monitor.infosimples import (
    DebitoInscricao,
    DividaAtivaPgfn,
    NaturezaDebito,
    SituacaoCndt,
    SituacaoFgts,
    SituacaoFiscalPgfn,
)
from src.fiscal_monitor.pdf import render_dossie_fiscal_pdf, render_pre_analise_pdf, render_portfolio_report
from src.fiscal_monitor.preanalise import PreAnalise
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


PRE_ANALISE = PreAnalise(
    cnpj="11.222.333/0001-44",
    razao_social="Contábil Exemplo",
    nome_fantasia="Contabil",
    situacao_cadastral="ATIVA",
    data_situacao_cadastral="2010-01-01",
    natureza_juridica="Sociedade Empresária Limitada",
    cnae_principal="Atividades de contabilidade",
    porte="ME",
    uf="SP",
    municipio="SAO PAULO",
    data_inicio_atividade="2010-01-01",
    opcao_pelo_simples=True,
    opcao_pelo_mei=False,
    capital_social=50000.0,
    socios=["Fulano de Tal"],
)


def test_render_pre_analise_pdf_creates_nonempty_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "pre_analise.pdf")
        render_pre_analise_pdf(PRE_ANALISE, ["Nenhum alerta cadastral identificado."], path, escritorio_nome="Escritório X")

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"


def test_render_pre_analise_pdf_includes_debitos_enriquecidos_com_dados_abertos():
    divida_ativa = DividaAtivaPgfn(
        total_divida=7359.68,
        total_tributario=0.0,
        total_nao_tributario=7359.68,
        naturezas=[
            NaturezaDebito(
                descricao="FGTS",
                total=7359.68,
                debitos=[
                    DebitoInscricao(
                        inscricao="FGAL202500237",
                        valor_divida=7359.68,
                        data_inscricao="2025-01-08",
                        situacao_inscricao="AJUIZADA",
                        ajuizada=True,
                    )
                ],
            )
        ],
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "pre_analise_enriquecida.pdf")
        render_pre_analise_pdf(PRE_ANALISE, ["Inscrição já ajuizada."], path, divida_ativa=divida_ativa)

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"


def test_render_pre_analise_pdf_includes_fgts_e_cndt():
    situacao_fgts = SituacaoFgts(situacao="IRREGULAR", validade_inicio_data=None, validade_fim_data=None)
    situacao_cndt = SituacaoCndt(consta_debito=True, total_processos=3, certidao_codigo="123456", validade_data="11/11/2026")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "pre_analise_fgts_cndt.pdf")
        render_pre_analise_pdf(
            PRE_ANALISE,
            ["Situação irregular perante o FGTS.", "Débitos trabalhistas identificados."],
            path,
            situacao_fgts=situacao_fgts,
            situacao_cndt=situacao_cndt,
        )

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"


def test_render_dossie_fiscal_pdf_creates_nonempty_file():
    situacao_fiscal = SituacaoFiscalPgfn(
        conseguiu_certidao_negativa=True,
        tipo_certidao="Negativa",
        debitos_pgfn=False,
        debitos_rfb=False,
        mensagem="CERTIDÃO NEGATIVA...",
        validade_data="11/11/2026",
    )
    situacao_fgts = SituacaoFgts(situacao="REGULAR", validade_inicio_data="01/01/2026", validade_fim_data="31/01/2026")
    situacao_cndt = SituacaoCndt(consta_debito=False, total_processos=0, certidao_codigo="123456", validade_data="11/11/2026")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "dossie_fiscal.pdf")
        render_dossie_fiscal_pdf(
            CNPJ_COM_ACHADO,
            TENANT,
            [],
            path,
            gerado_em="2026-10-04",
            situacao_fiscal=situacao_fiscal,
            situacao_fgts=situacao_fgts,
            situacao_cndt=situacao_cndt,
        )

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"


def test_render_dossie_fiscal_pdf_with_alertas_and_divida_ativa():
    divida_ativa = DividaAtivaPgfn(
        total_divida=7359.68,
        total_tributario=7359.68,
        total_nao_tributario=0.0,
        naturezas=[NaturezaDebito(descricao="FGTS", total=7359.68, debitos=[])],
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "dossie_fiscal_divida.pdf")
        render_dossie_fiscal_pdf(
            CNPJ_COM_ACHADO,
            TENANT,
            ["Inscrito na Lista de Devedores da PGFN."],
            path,
            divida_ativa=divida_ativa,
        )

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"


def test_render_pre_analise_pdf_includes_situacao_fiscal_e_divida_ativa():
    situacao_fiscal = SituacaoFiscalPgfn(
        conseguiu_certidao_negativa=False,
        tipo_certidao="Positiva",
        debitos_pgfn=True,
        debitos_rfb=False,
        mensagem="CERTIDÃO POSITIVA...",
        validade_data="11/11/2026",
    )
    divida_ativa = DividaAtivaPgfn(
        total_divida=29544029.81,
        total_tributario=29535048.02,
        total_nao_tributario=8981.79,
        naturezas=[NaturezaDebito(descricao="FGTS", total=29535048.02, debitos=[])],
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "pre_analise_fiscal.pdf")
        render_pre_analise_pdf(
            PRE_ANALISE,
            ["Débitos ativos identificados na PGFN."],
            path,
            situacao_fiscal=situacao_fiscal,
            divida_ativa=divida_ativa,
        )

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"

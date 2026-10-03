"""Relatório de carteira fiscal em PDF — reusa o estilo compartilhado."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle

from src.common.pdf_styles import (
    ACCENT_COLOR,
    ALERT_HEADING_STYLE,
    BODY_STYLE,
    BULLET_STYLE,
    HEADING_STYLE,
    TITLE_STYLE,
    new_document,
)
from src.fiscal_monitor.infosimples import (
    DividaAtivaPgfn,
    SituacaoCndt,
    SituacaoFgts,
    SituacaoFiscalPgfn,
    formatar_valor_brl,
)
from src.fiscal_monitor.preanalise import PreAnalise
from src.fiscal_monitor.storage import Cnpj, Finding, Tenant

_TABLE_COLS = [2.2 * cm, 2 * cm, 6 * cm, 2.5 * cm, 2.5 * cm, 2.3 * cm]


def render_portfolio_report(
    tenant: Tenant, findings_by_cnpj: list[tuple[Cnpj, list[Finding]]], output_path: str
) -> None:
    total_abertos = sum(len(findings) for _, findings in findings_by_cnpj)
    story = [
        Paragraph(f"Relatório fiscal — {tenant.nome}", TITLE_STYLE),
        Spacer(1, 12),
        Paragraph(
            f"{len(findings_by_cnpj)} CNPJ(s) monitorado(s) — {total_abertos} achado(s) em aberto.",
            BODY_STYLE,
        ),
    ]

    for cnpj, findings in findings_by_cnpj:
        heading_style = ALERT_HEADING_STYLE if findings else HEADING_STYLE
        story.append(Paragraph(f"{cnpj.razao_social or cnpj.cnpj} ({cnpj.cnpj})", heading_style))

        if not findings:
            story.append(Paragraph("Nenhum achado em aberto.", BODY_STYLE))
            continue

        table_data = [["Esfera", "Tipo", "Descrição", "Valor", "Vencimento", "Status"]]
        for finding in findings:
            table_data.append(
                [
                    finding.esfera,
                    finding.tipo,
                    finding.descricao,
                    f"R$ {finding.valor:,.2f}" if finding.valor else "-",
                    finding.vencimento or "-",
                    finding.status,
                ]
            )
        table = Table(table_data, colWidths=_TABLE_COLS)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), ACCENT_COLOR),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 10))

    new_document(output_path).build(story)


def render_pre_analise_pdf(
    analise: PreAnalise,
    alertas: list[str],
    output_path: str,
    escritorio_nome: str | None = None,
    logo_path: str | None = None,
    situacao_fiscal: SituacaoFiscalPgfn | None = None,
    divida_ativa: DividaAtivaPgfn | None = None,
    situacao_fgts: SituacaoFgts | None = None,
    situacao_cndt: SituacaoCndt | None = None,
) -> None:
    story = []
    if logo_path:
        story.append(Image(logo_path, width=3 * cm, height=3 * cm, kind="proportional"))
        story.append(Spacer(1, 8))

    story.append(Paragraph("Pré-Análise Fiscal", TITLE_STYLE))
    if escritorio_nome:
        story.append(Paragraph(f"Preparado por {escritorio_nome}", BODY_STYLE))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"{analise.razao_social} ({analise.cnpj})", HEADING_STYLE))
    if analise.nome_fantasia:
        story.append(Paragraph(f"Nome fantasia: {analise.nome_fantasia}", BODY_STYLE))
    story.append(Paragraph(f"Situação cadastral: {analise.situacao_cadastral or '-'}", BODY_STYLE))
    story.append(Paragraph(f"Natureza jurídica: {analise.natureza_juridica or '-'}", BODY_STYLE))
    story.append(Paragraph(f"CNAE principal: {analise.cnae_principal or '-'}", BODY_STYLE))
    story.append(Paragraph(f"Porte: {analise.porte or '-'}", BODY_STYLE))
    story.append(Paragraph(f"Município/UF: {analise.municipio or '-'}/{analise.uf or '-'}", BODY_STYLE))
    story.append(Paragraph(f"Início de atividade: {analise.data_inicio_atividade or '-'}", BODY_STYLE))

    def _sim_nao(valor: bool | None) -> str:
        if valor is None:
            return "não informado"
        return "sim" if valor else "não"

    story.append(Paragraph(f"Optante pelo Simples Nacional: {_sim_nao(analise.opcao_pelo_simples)}", BODY_STYLE))
    story.append(Paragraph(f"Optante pelo MEI: {_sim_nao(analise.opcao_pelo_mei)}", BODY_STYLE))
    if analise.socios:
        story.append(Paragraph(f"Sócios: {', '.join(analise.socios)}", BODY_STYLE))

    if situacao_fiscal is not None:
        story.append(Paragraph("Situação Fiscal (Receita Federal/PGFN)", HEADING_STYLE))
        story.append(Paragraph(f"Certidão: {situacao_fiscal.tipo_certidao or '-'}", BODY_STYLE))
        story.append(Paragraph(f"Débitos na Receita Federal: {_sim_nao(situacao_fiscal.debitos_rfb)}", BODY_STYLE))
        story.append(Paragraph(f"Débitos na PGFN: {_sim_nao(situacao_fiscal.debitos_pgfn)}", BODY_STYLE))
        if situacao_fiscal.validade_data:
            story.append(Paragraph(f"Validade da certidão: {situacao_fiscal.validade_data}", BODY_STYLE))

    if divida_ativa is not None:
        story.append(Paragraph("Dívida Ativa da União (Lista de Devedores PGFN)", HEADING_STYLE))
        story.append(Paragraph(f"Total da dívida: R$ {formatar_valor_brl(divida_ativa.total_divida)}", BODY_STYLE))
        story.append(
            Paragraph(
                f"Tributário: R$ {formatar_valor_brl(divida_ativa.total_tributario)} · "
                f"Não tributário: R$ {formatar_valor_brl(divida_ativa.total_nao_tributario)}",
                BODY_STYLE,
            )
        )
        for natureza in divida_ativa.naturezas:
            story.append(Paragraph(f"• {natureza.descricao}: R$ {formatar_valor_brl(natureza.total)}", BULLET_STYLE))
            for debito in natureza.debitos:
                detalhe = f"Inscrição {debito.inscricao}: R$ {formatar_valor_brl(debito.valor_divida)}"
                if debito.data_inscricao:
                    detalhe += f" · inscrita em {debito.data_inscricao} · {debito.situacao_inscricao}"
                story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;- {detalhe}", BULLET_STYLE))

    if situacao_fgts is not None:
        story.append(Paragraph("Regularidade do FGTS (Caixa)", HEADING_STYLE))
        story.append(Paragraph(f"Situação: {situacao_fgts.situacao or '-'}", BODY_STYLE))
        if situacao_fgts.validade_fim_data:
            story.append(
                Paragraph(
                    f"Validade: {situacao_fgts.validade_inicio_data or '-'} a {situacao_fgts.validade_fim_data}",
                    BODY_STYLE,
                )
            )

    if situacao_cndt is not None:
        story.append(Paragraph("Débitos Trabalhistas (CNDT/TST)", HEADING_STYLE))
        story.append(Paragraph(f"Consta débito/processo trabalhista: {_sim_nao(situacao_cndt.consta_debito)}", BODY_STYLE))
        if situacao_cndt.total_processos:
            story.append(Paragraph(f"Total de processos: {situacao_cndt.total_processos}", BODY_STYLE))

    story.append(Paragraph("Alertas da pré-análise", ALERT_HEADING_STYLE))
    for alerta in alertas:
        story.append(Paragraph(f"• {alerta}", BULLET_STYLE))

    story.append(Spacer(1, 16))
    consultou_infosimples = any(
        dado is not None for dado in (situacao_fiscal, divida_ativa, situacao_fgts, situacao_cndt)
    )
    nota_final = (
        "Esta pré-análise usa apenas dados públicos (situação cadastral, enquadramento "
        "tributário e, quando disponível, situação fiscal/dívida ativa na Receita Federal, "
        "PGFN, regularidade do FGTS e débitos trabalhistas na Justiça do Trabalho). Multas, "
        "parcelamentos e o histórico completo de pendências exigem procuração eletrônica e "
        "acesso ao e-CAC para uma verificação completa."
        if consultou_infosimples
        else
        "Esta pré-análise usa apenas dados públicos (situação cadastral e "
        "enquadramento tributário). Pendências, multas e débitos fiscais exigem "
        "procuração eletrônica e acesso ao e-CAC para uma verificação completa."
    )
    story.append(
        Paragraph(
            nota_final,
            BODY_STYLE,
        )
    )

    new_document(output_path).build(story)

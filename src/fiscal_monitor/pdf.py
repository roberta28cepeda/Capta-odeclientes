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

    story.append(Paragraph("Alertas da pré-análise", ALERT_HEADING_STYLE))
    for alerta in alertas:
        story.append(Paragraph(f"• {alerta}", BULLET_STYLE))

    story.append(Spacer(1, 16))
    story.append(
        Paragraph(
            "Esta pré-análise usa apenas dados públicos (situação cadastral e "
            "enquadramento tributário). Pendências, multas e débitos fiscais exigem "
            "procuração eletrônica e acesso ao e-CAC para uma verificação completa.",
            BODY_STYLE,
        )
    )

    new_document(output_path).build(story)

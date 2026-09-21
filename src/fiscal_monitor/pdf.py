"""Relatório de carteira fiscal em PDF — reusa o estilo compartilhado."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from src.common.pdf_styles import ACCENT_COLOR, ALERT_HEADING_STYLE, BODY_STYLE, HEADING_STYLE, TITLE_STYLE, new_document
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

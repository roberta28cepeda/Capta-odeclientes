"""Renders a CallAnalysis into a styled PDF report."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from src.call_analysis.schema import CallAnalysis
from src.common.pdf_styles import (
    ACCENT_COLOR,
    ALERT_HEADING_STYLE,
    BODY_STYLE,
    BULLET_STYLE,
    HEADING_STYLE,
    TITLE_STYLE,
    new_document,
)


def render_call_analysis_pdf(analysis: CallAnalysis, output_path: str) -> None:
    story = [
        Paragraph("Análise pós-call", TITLE_STYLE),
        Paragraph(f"Nota geral: {analysis.overall_score}/10", BODY_STYLE),
        Spacer(1, 8),
        Paragraph(analysis.summary, BODY_STYLE),
        Paragraph("Pontos fortes", HEADING_STYLE),
    ]
    for item in analysis.strengths:
        story.append(Paragraph(f"• {item}", BULLET_STYLE))

    story.append(Paragraph("O bug que mais custou a call", ALERT_HEADING_STYLE))
    story.append(Paragraph(analysis.critical_issue, BODY_STYLE))
    story.append(Paragraph("Como corrigir", HEADING_STYLE))
    story.append(Paragraph(analysis.critical_issue_fix, BODY_STYLE))

    story.append(Paragraph("Momentos-chave", HEADING_STYLE))
    table_data = [["Trecho", "Categoria", "Comentário"]]
    table_data += [
        [moment.quote, moment.category, moment.comment] for moment in analysis.key_moments
    ]
    table = Table(table_data, colWidths=[6.5 * cm, 3 * cm, 5.5 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT_COLOR),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)

    story.append(Paragraph("Próximo passo sugerido", HEADING_STYLE))
    story.append(Paragraph(analysis.next_step_suggestion, BODY_STYLE))

    new_document(output_path).build(story)

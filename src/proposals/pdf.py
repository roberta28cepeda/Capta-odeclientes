"""Renders Proposal/Contract data into styled PDFs — no Canva needed."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.proposals.schema import Contract, Proposal

ACCENT_COLOR = colors.HexColor("#1F3A5F")

_styles = getSampleStyleSheet()

TITLE_STYLE = ParagraphStyle(
    "DocTitle",
    parent=_styles["Title"],
    textColor=ACCENT_COLOR,
    spaceAfter=6,
)
HEADING_STYLE = ParagraphStyle(
    "SectionHeading",
    parent=_styles["Heading2"],
    textColor=ACCENT_COLOR,
    spaceBefore=14,
    spaceAfter=6,
)
BODY_STYLE = ParagraphStyle("Body", parent=_styles["BodyText"], leading=15)
BULLET_STYLE = ParagraphStyle(
    "Bullet", parent=_styles["BodyText"], leftIndent=14, bulletIndent=0, leading=15
)


def _doc(output_path: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )


def render_proposal_pdf(proposal: Proposal, output_path: str) -> None:
    story = [
        Paragraph(proposal.title, TITLE_STYLE),
        Paragraph(f"Para: {proposal.client_name}", BODY_STYLE),
        Spacer(1, 12),
        Paragraph(proposal.intro, BODY_STYLE),
        Paragraph("Escopo", HEADING_STYLE),
    ]
    for item in proposal.scope_items:
        story.append(Paragraph(f"• {item}", BULLET_STYLE))

    story.append(Paragraph("Cronograma", HEADING_STYLE))
    for item in proposal.timeline_items:
        story.append(Paragraph(f"• {item}", BULLET_STYLE))

    story.append(Paragraph("Investimento", HEADING_STYLE))
    table_data = [["Item", "Valor"]]
    table_data += [[item.description, item.price] for item in proposal.pricing_items]
    table_data.append(["Total", proposal.total_price])

    table = Table(table_data, colWidths=[11 * cm, 4 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT_COLOR),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)

    story.append(Paragraph("Forma de pagamento", HEADING_STYLE))
    story.append(Paragraph(proposal.payment_terms, BODY_STYLE))

    story.append(Paragraph("Próximos passos", HEADING_STYLE))
    story.append(Paragraph(proposal.closing, BODY_STYLE))

    _doc(output_path).build(story)


def render_contract_pdf(contract: Contract, output_path: str) -> None:
    story = [
        Paragraph(contract.title, TITLE_STYLE),
        Paragraph(f"Contratante: {contract.client_name}", BODY_STYLE),
        Paragraph(f"Contratado(a): {contract.contractor_name}", BODY_STYLE),
        Spacer(1, 12),
    ]
    for i, clause in enumerate(contract.clauses, start=1):
        story.append(Paragraph(f"{i}. {clause.heading}", HEADING_STYLE))
        story.append(Paragraph(clause.body, BODY_STYLE))

    story.append(Spacer(1, 24))
    story.append(Paragraph(contract.signature_line, BODY_STYLE))

    _doc(output_path).build(story)

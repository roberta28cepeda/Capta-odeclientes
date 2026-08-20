"""Shared report styling so every generated PDF looks like one product."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate

ACCENT_COLOR = colors.HexColor("#1F3A5F")
ALERT_COLOR = colors.HexColor("#B23A48")

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
ALERT_HEADING_STYLE = ParagraphStyle(
    "AlertHeading",
    parent=_styles["Heading2"],
    textColor=ALERT_COLOR,
    spaceBefore=14,
    spaceAfter=6,
)
BODY_STYLE = ParagraphStyle("Body", parent=_styles["BodyText"], leading=15)
BULLET_STYLE = ParagraphStyle(
    "Bullet", parent=_styles["BodyText"], leftIndent=14, bulletIndent=0, leading=15
)


def new_document(output_path: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

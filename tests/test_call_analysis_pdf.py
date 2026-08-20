import os
import tempfile

from src.call_analysis.pdf import render_call_analysis_pdf
from src.call_analysis.schema import CallAnalysis, KeyMoment


def test_render_call_analysis_pdf_creates_nonempty_file():
    analysis = CallAnalysis(
        overall_score=7,
        summary="Resumo da call.",
        strengths=["Bom rapport"],
        critical_issue="Não ancorou valor antes do preço.",
        critical_issue_fix="Perguntar sobre o impacto do problema primeiro.",
        key_moments=[KeyMoment(quote="Achei salgado.", category="precificação", comment="Faltou valor.")],
        next_step_suggestion="Enviar um case parecido.",
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "analise_call.pdf")
        render_call_analysis_pdf(analysis, path)

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"

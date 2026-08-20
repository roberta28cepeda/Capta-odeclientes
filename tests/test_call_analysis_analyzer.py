from unittest.mock import MagicMock

from src.call_analysis.analyzer import build_system_prompt, generate_call_analysis
from src.call_analysis.schema import CallAnalysis, KeyMoment


def _sample_analysis() -> CallAnalysis:
    return CallAnalysis(
        overall_score=6,
        summary="Boa abertura, mas travou na objeção de preço.",
        strengths=["Rapport inicial bom"],
        critical_issue="Não fez descoberta de valor antes de falar o preço.",
        critical_issue_fix="Perguntar sobre impacto do problema antes de apresentar valor.",
        key_moments=[
            KeyMoment(quote="Achei salgado.", category="precificação", comment="Reação à falta de ancoragem de valor.")
        ],
        next_step_suggestion="Enviar case de outro cliente similar antes de retomar contato.",
    )


def test_build_system_prompt_includes_language():
    prompt = build_system_prompt(language="português do Brasil")
    assert "português do Brasil" in prompt
    assert "bug" in prompt.lower()


def test_generate_call_analysis_calls_claude_with_transcript_and_context():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.parsed_output = _sample_analysis()
    fake_client.messages.parse.return_value = fake_response

    result = generate_call_analysis(
        "Vendedor: oi...", context="Venda de site para padaria.", client=fake_client
    )

    assert result.overall_score == 6
    assert result.critical_issue.startswith("Não fez descoberta")

    _, call_kwargs = fake_client.messages.parse.call_args
    assert call_kwargs["output_format"] is CallAnalysis
    user_content = call_kwargs["messages"][0]["content"]
    assert "Venda de site para padaria." in user_content
    assert "Vendedor: oi..." in user_content


def test_generate_call_analysis_without_context():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.parsed_output = _sample_analysis()
    fake_client.messages.parse.return_value = fake_response

    generate_call_analysis("Transcrição simples.", client=fake_client)

    _, call_kwargs = fake_client.messages.parse.call_args
    user_content = call_kwargs["messages"][0]["content"]
    assert "Contexto adicional" not in user_content

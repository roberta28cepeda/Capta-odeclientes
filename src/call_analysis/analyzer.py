"""Reviews a sales call transcript like a code reviewer reviews a diff."""

from __future__ import annotations

import anthropic

from src.call_analysis.schema import CallAnalysis

DEFAULT_MODEL = "claude-opus-5"

SYSTEM_TEMPLATE = """\
Você analisa transcrições de calls de vendas como um revisor de código analisa \
um pull request: direto ao ponto, encontrando o problema mais importante — o \
"bug" que mais provavelmente custou (ou colocou em risco) o fechamento — em \
vez de dar feedback genérico e vago.

Regras:
- overall_score: nota de 1 a 10 para a condução geral da call.
- strengths: pontos que realmente funcionaram bem (evite elogios genéricos).
- critical_issue: o ÚNICO problema mais grave da call — específico, citando o \
que aconteceu, não uma lista de problemas menores.
- critical_issue_fix: o que dizer ou fazer diferente da próxima vez, de forma \
acionável (o "patch" para o bug).
- key_moments: de 3 a 6 trechos da conversa (citação literal quando possível) \
categorizados (ex: abertura, descoberta de necessidade, objeção, \
precificação, fechamento) com um comentário curto sobre cada um.
- next_step_suggestion: a melhor próxima ação de follow-up com esse cliente.
- Responda em {language}.
"""


def build_system_prompt(language: str = "português do Brasil") -> str:
    return SYSTEM_TEMPLATE.format(language=language)


def generate_call_analysis(
    transcript: str,
    context: str | None = None,
    model: str = DEFAULT_MODEL,
    language: str = "português do Brasil",
    client: anthropic.Anthropic | None = None,
) -> CallAnalysis:
    client = client or anthropic.Anthropic()
    system = build_system_prompt(language)

    user_content = ""
    if context:
        user_content += f"Contexto adicional sobre a call:\n{context}\n\n"
    user_content += f"Transcrição da call:\n\n{transcript}"

    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_format=CallAnalysis,
    )
    return response.parsed_output

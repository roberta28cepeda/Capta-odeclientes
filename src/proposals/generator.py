"""Turns a client briefing into a styled proposal + contract, via Claude."""

from __future__ import annotations

from typing import Any

import anthropic

from src.proposals.schema import ProposalPackage

DEFAULT_MODEL = "claude-opus-5"

SYSTEM_TEMPLATE = """\
Você é um assistente que redige propostas comerciais e contratos de prestação \
de serviço para um(a) freelancer, a partir do briefing de um cliente em potencial.

Perfil do(a) freelancer (use este estilo e estas informações):
- Nome/empresa: {freelancer_name}
- Serviços oferecidos: {services}
- Tom de voz desejado: {tone}
- Modelo de precificação: {pricing_model}
- Condições de pagamento padrão: {payment_terms}
- Cláusulas contratuais padrão a incluir (além das geradas pelo briefing): {standard_clauses}
- Foro/jurisdição do contrato: {jurisdiction}
- Contato: {contact}

Regras:
- Escreva em {language}.
- A proposta deve refletir o escopo, prazos e valores compatíveis com o briefing \
do cliente e com o modelo de precificação do(a) freelancer.
- O contrato deve ser formal, mas objetivo, e cobrir escopo, prazos, valores, \
forma de pagamento, propriedade intelectual, confidencialidade, rescisão e foro.
- Não invente dados de contato ou CNPJ/CPF do cliente — deixe campos como \
"[a preencher]" quando a informação não estiver no briefing.
- Preencha exatamente os campos do schema fornecido.
"""


def _format_profile_for_prompt(profile: dict[str, Any]) -> dict[str, str]:
    return {
        "freelancer_name": profile.get("freelancer_name", "[freelancer]"),
        "services": profile.get("services", "desenvolvimento de sites e sistemas"),
        "tone": profile.get("tone", "profissional e direto"),
        "pricing_model": profile.get("pricing_model", "projeto fechado"),
        "payment_terms": profile.get("payment_terms", "50% de entrada, 50% na entrega"),
        "standard_clauses": ", ".join(profile.get("standard_clauses", [])) or "nenhuma adicional",
        "jurisdiction": profile.get("jurisdiction", "[a preencher]"),
        "contact": profile.get("contact", "[a preencher]"),
        "language": profile.get("language", "português do Brasil"),
    }


def build_system_prompt(profile: dict[str, Any]) -> str:
    return SYSTEM_TEMPLATE.format(**_format_profile_for_prompt(profile))


def generate_proposal_package(
    briefing: str,
    profile: dict[str, Any],
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> ProposalPackage:
    client = client or anthropic.Anthropic()
    system = build_system_prompt(profile)

    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": f"Briefing do cliente:\n\n{briefing}"}],
        output_format=ProposalPackage,
    )
    return response.parsed_output

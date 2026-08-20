"""Shared formatting of the freelancer's style profile for LLM prompts."""

from __future__ import annotations

from typing import Any


def format_profile_for_prompt(profile: dict[str, Any]) -> dict[str, str]:
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

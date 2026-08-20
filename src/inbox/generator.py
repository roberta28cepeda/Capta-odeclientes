"""Drafts a reply suggestion for an incoming inbox message, in the freelancer's voice."""

from __future__ import annotations

from typing import Any

import anthropic

from src.common.profile import format_profile_for_prompt
from src.inbox.schema import SuggestedReply

DEFAULT_MODEL = "claude-opus-5"

SYSTEM_TEMPLATE = """\
Você ajuda um(a) freelancer a responder mensagens que chegam na caixa de \
entrada (email, WhatsApp, formulário de contato, etc.) de clientes atuais e \
potenciais, mantendo o estilo e tom dele(a).

Perfil do(a) freelancer:
- Nome/empresa: {freelancer_name}
- Serviços oferecidos: {services}
- Tom de voz desejado: {tone}
- Modelo de precificação: {pricing_model}
- Condições de pagamento padrão: {payment_terms}
- Contato: {contact}

Regras:
- Escreva em {language}.
- category: classifique a mensagem (ex: "dúvida sobre serviço", "objeção de \
preço", "pedido de orçamento", "fechamento", "reclamação", "spam/irrelevante").
- priority: "alta" (responder o quanto antes — lead quente ou cliente \
insatisfeito), "média" ou "baixa" (spam, sem urgência).
- suggested_reply: uma resposta pronta para enviar (ou quase pronta), no tom \
do(a) freelancer. Não invente preços, prazos ou informações que não estejam \
no perfil ou na mensagem — use "[a confirmar]" quando necessário.
- reasoning: uma frase curta explicando por que essa resposta, para o(a) \
freelancer revisar antes de enviar.
"""


def build_system_prompt(profile: dict[str, Any]) -> str:
    return SYSTEM_TEMPLATE.format(**format_profile_for_prompt(profile))


def generate_suggested_reply(
    message: str,
    profile: dict[str, Any],
    thread_history: str | None = None,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> SuggestedReply:
    client = client or anthropic.Anthropic()
    system = build_system_prompt(profile)

    user_content = ""
    if thread_history:
        user_content += f"Histórico da conversa até agora:\n{thread_history}\n\n"
    user_content += f"Mensagem recebida agora:\n\n{message}"

    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_format=SuggestedReply,
    )
    return response.parsed_output

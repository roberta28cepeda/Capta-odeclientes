from unittest.mock import MagicMock

from src.inbox.generator import build_system_prompt, generate_suggested_reply
from src.inbox.schema import SuggestedReply

PROFILE = {
    "freelancer_name": "Ana Dev",
    "services": "sites institucionais",
    "tone": "direto e amigável",
    "contact": "ana@example.com",
}


def _sample_reply() -> SuggestedReply:
    return SuggestedReply(
        category="pedido de orçamento",
        priority="alta",
        suggested_reply="Oi! Consigo te passar um orçamento, me conta mais sobre o projeto?",
        reasoning="Lead quente pedindo preço direto — vale responder rápido.",
    )


def test_build_system_prompt_includes_profile_fields():
    prompt = build_system_prompt(PROFILE)

    assert "Ana Dev" in prompt
    assert "sites institucionais" in prompt


def test_generate_suggested_reply_includes_thread_history_when_given():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.parsed_output = _sample_reply()
    fake_client.messages.parse.return_value = fake_response

    result = generate_suggested_reply(
        "Quanto custa um site?",
        PROFILE,
        thread_history="Cliente perguntou sobre prazo ontem.",
        client=fake_client,
    )

    assert result.category == "pedido de orçamento"

    _, call_kwargs = fake_client.messages.parse.call_args
    assert call_kwargs["output_format"] is SuggestedReply
    user_content = call_kwargs["messages"][0]["content"]
    assert "Cliente perguntou sobre prazo ontem." in user_content
    assert "Quanto custa um site?" in user_content


def test_generate_suggested_reply_without_thread_history():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.parsed_output = _sample_reply()
    fake_client.messages.parse.return_value = fake_response

    generate_suggested_reply("Quanto custa um site?", PROFILE, client=fake_client)

    _, call_kwargs = fake_client.messages.parse.call_args
    user_content = call_kwargs["messages"][0]["content"]
    assert "Histórico da conversa" not in user_content

from unittest.mock import MagicMock

from src.proposals.generator import build_system_prompt, generate_proposal_package
from src.proposals.schema import Contract, ContractClause, PricingItem, Proposal, ProposalPackage

PROFILE = {
    "freelancer_name": "Ana Dev",
    "services": "sites institucionais",
    "tone": "direto",
    "pricing_model": "projeto fechado",
    "payment_terms": "50/50",
    "standard_clauses": ["2 rodadas de ajuste"],
    "jurisdiction": "São Paulo, SP",
    "contact": "ana@example.com",
    "language": "português do Brasil",
}


def _sample_package() -> ProposalPackage:
    return ProposalPackage(
        proposal=Proposal(
            title="Proposta - Site institucional",
            client_name="Padaria Central",
            intro="Segue nossa proposta.",
            scope_items=["Página inicial", "Página de contato"],
            timeline_items=["Semana 1-2: design"],
            pricing_items=[PricingItem(description="Desenvolvimento", price="R$ 2.500")],
            total_price="R$ 2.500",
            payment_terms="50/50",
            closing="Aguardo retorno.",
        ),
        contract=Contract(
            title="Contrato de Prestação de Serviço",
            contractor_name="Ana Dev",
            client_name="Padaria Central",
            clauses=[ContractClause(heading="Objeto", body="Desenvolvimento de site.")],
            signature_line="Assinaturas: ______",
        ),
    )


def test_build_system_prompt_includes_profile_fields():
    prompt = build_system_prompt(PROFILE)

    assert "Ana Dev" in prompt
    assert "sites institucionais" in prompt
    assert "português do Brasil" in prompt


def test_build_system_prompt_uses_defaults_for_missing_fields():
    prompt = build_system_prompt({})

    assert "[freelancer]" in prompt
    assert "nenhuma adicional" in prompt


def test_generate_proposal_package_calls_claude_with_parsed_output():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.parsed_output = _sample_package()
    fake_client.messages.parse.return_value = fake_response

    result = generate_proposal_package("Preciso de um site.", PROFILE, client=fake_client)

    assert result.proposal.client_name == "Padaria Central"
    assert result.contract.contractor_name == "Ana Dev"

    _, call_kwargs = fake_client.messages.parse.call_args
    assert call_kwargs["output_format"] is ProposalPackage
    assert "Preciso de um site." in call_kwargs["messages"][0]["content"]

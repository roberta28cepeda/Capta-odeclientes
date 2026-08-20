import os
import tempfile

from src.proposals.pdf import render_contract_pdf, render_proposal_pdf
from src.proposals.schema import Contract, ContractClause, PricingItem, Proposal


def test_render_proposal_pdf_creates_nonempty_file():
    proposal = Proposal(
        title="Proposta",
        client_name="Cliente X",
        intro="Intro",
        scope_items=["Item 1"],
        timeline_items=["Semana 1"],
        pricing_items=[PricingItem(description="Item", price="R$ 100")],
        total_price="R$ 100",
        payment_terms="À vista",
        closing="Obrigado",
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "proposta.pdf")
        render_proposal_pdf(proposal, path)

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"


def test_render_contract_pdf_creates_nonempty_file():
    contract = Contract(
        title="Contrato",
        contractor_name="Freelancer",
        client_name="Cliente X",
        clauses=[ContractClause(heading="Objeto", body="Descrição do serviço.")],
        signature_line="Assinaturas",
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "contrato.pdf")
        render_contract_pdf(contract, path)

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"

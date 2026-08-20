"""CLI: turn a client briefing into a proposal.pdf + contrato.pdf.

Usage:
    python -m src.proposals.cli --briefing briefing.txt --profile profiles/freelancer_profile.yaml
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml
from dotenv import load_dotenv

from src.proposals.generator import generate_proposal_package
from src.proposals.pdf import render_contract_pdf, render_proposal_pdf


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera proposta e contrato em PDF a partir do briefing de um cliente."
    )
    parser.add_argument("--briefing", required=True, help="Caminho para o arquivo de briefing (.txt)")
    parser.add_argument(
        "--profile",
        default="profiles/freelancer_profile.yaml",
        help="Caminho para o perfil do freelancer (.yaml)",
    )
    parser.add_argument("--output-dir", default="output", help="Diretório de saída dos PDFs")
    parser.add_argument("--model", default=None, help="Sobrescreve o modelo Claude usado")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)

    if not os.path.exists(args.briefing):
        print(f"Briefing não encontrado: {args.briefing}", file=sys.stderr)
        return 1
    if not os.path.exists(args.profile):
        print(
            f"Perfil não encontrado: {args.profile}. "
            "Copie profiles/freelancer_profile.example.yaml e edite.",
            file=sys.stderr,
        )
        return 1

    with open(args.briefing, encoding="utf-8") as f:
        briefing = f.read()
    with open(args.profile, encoding="utf-8") as f:
        profile = yaml.safe_load(f) or {}

    kwargs = {}
    if args.model:
        kwargs["model"] = args.model

    print("Gerando proposta e contrato com Claude...")
    package = generate_proposal_package(briefing, profile, **kwargs)

    os.makedirs(args.output_dir, exist_ok=True)
    proposal_path = os.path.join(args.output_dir, "proposta.pdf")
    contract_path = os.path.join(args.output_dir, "contrato.pdf")

    render_proposal_pdf(package.proposal, proposal_path)
    render_contract_pdf(package.contract, contract_path)

    print(f"Proposta salva em {proposal_path}")
    print(f"Contrato salvo em {contract_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

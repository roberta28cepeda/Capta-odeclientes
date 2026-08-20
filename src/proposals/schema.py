"""Structured output schema for LLM-generated proposals and contracts."""

from __future__ import annotations

from pydantic import BaseModel


class PricingItem(BaseModel):
    description: str
    price: str


class Proposal(BaseModel):
    title: str
    client_name: str
    intro: str
    scope_items: list[str]
    timeline_items: list[str]
    pricing_items: list[PricingItem]
    total_price: str
    payment_terms: str
    closing: str


class ContractClause(BaseModel):
    heading: str
    body: str


class Contract(BaseModel):
    title: str
    contractor_name: str
    client_name: str
    clauses: list[ContractClause]
    signature_line: str


class ProposalPackage(BaseModel):
    proposal: Proposal
    contract: Contract

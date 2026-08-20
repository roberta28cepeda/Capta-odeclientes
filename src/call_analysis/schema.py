"""Structured output schema for LLM-generated call analysis."""

from __future__ import annotations

from pydantic import BaseModel


class KeyMoment(BaseModel):
    quote: str
    category: str
    comment: str


class CallAnalysis(BaseModel):
    overall_score: int
    summary: str
    strengths: list[str]
    critical_issue: str
    critical_issue_fix: str
    key_moments: list[KeyMoment]
    next_step_suggestion: str

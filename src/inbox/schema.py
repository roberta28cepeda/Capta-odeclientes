"""Structured output schema for LLM-suggested inbox replies."""

from __future__ import annotations

from pydantic import BaseModel


class SuggestedReply(BaseModel):
    category: str
    priority: str
    suggested_reply: str
    reasoning: str

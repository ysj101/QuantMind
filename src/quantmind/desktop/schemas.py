"""Pydantic schemas shared by desktop read models and RPC."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

PipelineStatus = Literal["success", "skipped", "failed", "running", "missing"]


class PipelineStepView(BaseModel):
    name: str
    status: PipelineStatus | str
    detail: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PipelineRunSummary(BaseModel):
    date: date
    latest_status: PipelineStatus | str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: list[PipelineStepView] = Field(default_factory=list)


class ExtractedSymbol(BaseModel):
    date: date
    code: str
    rank: int | None = None
    score: float | None = None
    rules_hit: list[str] = Field(default_factory=list)
    recommendation: str | None = None
    confidence: float | None = None
    summary: str | None = None


class DebateMessage(BaseModel):
    role: str
    model: str | None = None
    system_prompt: str | None = None
    prompt: str | None = None
    output: str
    confidence: float | None = None
    duration_sec: float | None = None
    error: str | None = None
    created_at: datetime | None = None


class DebateTranscript(BaseModel):
    date: date
    code: str
    conversation_id: str | None = None
    messages: list[DebateMessage] = Field(default_factory=list)


class SymbolDetail(BaseModel):
    date: date
    code: str
    extracted: ExtractedSymbol | None = None
    debate: DebateTranscript
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    alerts: list[dict[str, Any]] = Field(default_factory=list)


class DailySummary(BaseModel):
    date: date
    latest_status: PipelineStatus | str
    steps: list[PipelineStepView] = Field(default_factory=list)
    extracted_count: int = 0
    debate_count: int = 0
    regime: dict[str, Any] | None = None

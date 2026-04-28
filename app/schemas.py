"""Pydantic schemas for API I/O."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StrandOut(_Base):
    id: int
    key: str
    name: str
    description: str = ""
    icon: str = ""
    sort_order: int = 0


class ChildIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    grade: str = "K"
    age: Optional[int] = None
    interests: str = ""
    avatar: str = "🦊"
    color: str = "#f4a261"


class ChildOut(_Base):
    id: int
    name: str
    grade: str
    age: Optional[int]
    interests: str
    avatar: str
    color: str
    created_at: datetime


class ProblemOut(_Base):
    id: int
    slug: str
    strand_id: int
    level: int
    grade_band: str
    kind: str
    title: str
    prompt: str
    answer: str
    answer_type: str
    hints: list = []
    strategies: list = []
    materials: list = []
    tags: list = []
    explain_prompt: str = ""
    parent_extension: str = ""
    minutes: int = 3


class AttemptIn(BaseModel):
    problem_id: int
    session_id: Optional[int] = None
    answer_given: str = ""
    correct: Optional[bool] = None
    hint_count: int = 0
    parent_rating: Optional[str] = None
    strategy_note: str = ""
    time_seconds: int = 0


class AttemptOut(_Base):
    id: int
    child_id: int
    problem_id: int
    session_id: Optional[int]
    answer_given: str
    correct: Optional[bool]
    hint_count: int
    parent_rating: Optional[str]
    strategy_note: str
    time_seconds: int
    created_at: datetime


class SessionPlanItem(BaseModel):
    kind: str
    problem_id: int
    position: int
    strand_key: str
    title: str
    minutes: int


class SessionOut(_Base):
    id: int
    child_id: int
    mode: str
    plan: list[Any] = []
    started_at: datetime
    completed_at: Optional[datetime] = None
    parent_summary: str = ""


class NoteIn(BaseModel):
    kind: str = "parent"
    body: str


class NoteOut(_Base):
    id: int
    child_id: int
    kind: str
    body: str
    created_at: datetime


class SkillOut(_Base):
    id: int
    child_id: int
    strand_id: int
    level: int
    rolling_accuracy: float
    streak: int
    last_practiced: Optional[datetime]
    mastery_notes: str

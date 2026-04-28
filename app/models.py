"""ORM models for Math Circle Home."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class Strand(Base):
    __tablename__ = "strands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(8), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    problems: Mapped[list["Problem"]] = relationship(back_populates="strand")


class Child(Base):
    __tablename__ = "children"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    grade: Mapped[str] = mapped_column(String(16), default="K")  # "K", "1", "2"
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    interests: Mapped[str] = mapped_column(Text, default="")  # comma-list
    avatar: Mapped[str] = mapped_column(String(8), default="🦊")
    color: Mapped[str] = mapped_column(String(16), default="#f4a261")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # AI digests opt-in. None = never asked; True/False = explicit choice.
    ai_digests_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    ai_digests_decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    skills: Mapped[list["Skill"]] = relationship(
        back_populates="child", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="child", cascade="all, delete-orphan"
    )
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="child", cascade="all, delete-orphan"
    )
    notes: Mapped[list["Note"]] = relationship(
        back_populates="child", cascade="all, delete-orphan"
    )


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    strand_id: Mapped[int] = mapped_column(ForeignKey("strands.id"), index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)  # 1..5
    grade_band: Mapped[str] = mapped_column(String(16), default="K-1")
    kind: Mapped[str] = mapped_column(String(32), default="story")
    # kinds: warm_up | rich_puzzle | visual | story | explain | game | parent_extension
    title: Mapped[str] = mapped_column(String(160))
    prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    answer_type: Mapped[str] = mapped_column(String(24), default="open")
    # answer_type: number | text | multi | open | set
    hints: Mapped[list] = mapped_column(JSON, default=list)
    strategies: Mapped[list] = mapped_column(JSON, default=list)
    materials: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    explain_prompt: Mapped[str] = mapped_column(Text, default="")
    parent_extension: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    minutes: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    strand: Mapped[Strand] = relationship(back_populates="problems")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="problem")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="solo")  # solo | circle
    plan: Mapped[list] = mapped_column(JSON, default=list)
    # plan items: {kind, problem_id, position}
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    parent_summary: Mapped[str] = mapped_column(Text, default="")

    child: Mapped[Child] = relationship(back_populates="sessions")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="session")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sessions.id"), nullable=True
    )
    answer_given: Mapped[str] = mapped_column(Text, default="")
    correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    hint_count: Mapped[int] = mapped_column(Integer, default=0)
    parent_rating: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # easy | good_struggle | too_hard
    strategy_note: Mapped[str] = mapped_column(Text, default="")
    time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    child: Mapped[Child] = relationship(back_populates="attempts")
    problem: Mapped[Problem] = relationship(back_populates="attempts")
    session: Mapped[Optional[Session]] = relationship(back_populates="attempts")


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("child_id", "strand_id", name="uq_child_strand"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    strand_id: Mapped[int] = mapped_column(ForeignKey("strands.id"), index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    rolling_accuracy: Mapped[float] = mapped_column(default=0.0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    last_practiced: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    mastery_notes: Mapped[str] = mapped_column(Text, default="")

    child: Mapped[Child] = relationship(back_populates="skills")
    strand: Mapped[Strand] = relationship()


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="parent")
    # parent | observation | win | concern | strategy
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    child: Mapped[Child] = relationship(back_populates="notes")


class Digest(Base):
    """Daily AI-generated summary of a child's math practice."""
    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime)
    period_label: Mapped[str] = mapped_column(String(32), default="daily")  # daily|weekly|adhoc
    # Structured summary the model returns; rendered in the UI.
    summary: Mapped[dict] = mapped_column(JSON)
    # Full raw model response for debugging / auditing.
    raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_id: Mapped[str] = mapped_column(String(80), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    child: Mapped[Child] = relationship()


class GeneratedTemplate(Base):
    __tablename__ = "generated_problem_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strand_id: Mapped[int] = mapped_column(ForeignKey("strands.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    level: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(32), default="story")
    template: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    strand: Mapped[Strand] = relationship()

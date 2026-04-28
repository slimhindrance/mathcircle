"""JSON API routes."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..ai_digest import generate_and_persist as ai_generate_and_persist
from ..database import get_db
from ..models import (
    Attempt,
    Child,
    Digest,
    Note,
    Problem,
    Session as SessionRow,
    Skill,
    Strand,
)
from ..session_generator import (
    build_session_plan,
    circle_night_plan,
    generate_template_problem,
    update_skill_from_attempt,
)

router = APIRouter(prefix="/api", tags=["api"])


# ---------- Children ----------
@router.get("/children", response_model=list[schemas.ChildOut])
def list_children(db: Session = Depends(get_db)):
    return db.execute(select(Child).order_by(Child.created_at)).scalars().all()


@router.post("/children", response_model=schemas.ChildOut, status_code=201)
def create_child(payload: schemas.ChildIn, db: Session = Depends(get_db)):
    c = Child(**payload.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.get("/children/{child_id}", response_model=schemas.ChildOut)
def get_child(child_id: int, db: Session = Depends(get_db)):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404, "Child not found")
    return c


@router.put("/children/{child_id}", response_model=schemas.ChildOut)
def update_child(child_id: int, payload: schemas.ChildIn, db: Session = Depends(get_db)):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404, "Child not found")
    for k, v in payload.model_dump().items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/children/{child_id}", status_code=204)
def delete_child(child_id: int, db: Session = Depends(get_db)):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404, "Child not found")
    db.delete(c)
    db.commit()


# ---------- Strands ----------
@router.get("/strands", response_model=list[schemas.StrandOut])
def list_strands(db: Session = Depends(get_db)):
    return db.execute(select(Strand).order_by(Strand.sort_order)).scalars().all()


# ---------- Problems ----------
@router.get("/problems", response_model=list[schemas.ProblemOut])
def list_problems(
    strand: Optional[str] = None,
    level: Optional[int] = None,
    kind: Optional[str] = None,
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(Problem)
    if strand:
        stmt = stmt.join(Strand).where(Strand.key == strand)
    if level:
        stmt = stmt.where(Problem.level == level)
    if kind:
        stmt = stmt.where(Problem.kind == kind)
    stmt = stmt.order_by(Problem.id).limit(limit)
    return db.execute(stmt).scalars().all()


@router.get("/problems/{problem_id}", response_model=schemas.ProblemOut)
def get_problem(problem_id: int, db: Session = Depends(get_db)):
    p = db.get(Problem, problem_id)
    if p is None:
        raise HTTPException(404)
    return p


@router.get("/problems/generated/new")
def generated_problem(strand: Optional[str] = None, seed: Optional[int] = None, db: Session = Depends(get_db)):
    out = generate_template_problem(db, strand_key=strand, seed=seed)
    if out is None:
        raise HTTPException(404, "No templates available")
    return out


# ---------- Sessions ----------
@router.post("/children/{child_id}/sessions", status_code=201)
def start_session(
    child_id: int,
    mode: str = "solo",
    seed: Optional[int] = None,
    db: Session = Depends(get_db),
):
    child = db.get(Child, child_id)
    if child is None:
        raise HTTPException(404, "Child not found")
    plan = build_session_plan(db, child, mode=mode, seed=seed)
    s = SessionRow(child_id=child.id, mode=mode, plan=plan)
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "child_id": s.child_id, "mode": s.mode, "plan": s.plan}


@router.get("/sessions/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)):
    s = db.get(SessionRow, session_id)
    if s is None:
        raise HTTPException(404)
    return {
        "id": s.id,
        "child_id": s.child_id,
        "mode": s.mode,
        "plan": s.plan,
        "started_at": s.started_at,
        "completed_at": s.completed_at,
        "parent_summary": s.parent_summary,
    }


class _CompleteIn(BaseModel):
    summary: str = ""


@router.post("/sessions/{session_id}/complete")
def complete_session(
    session_id: int,
    payload: _CompleteIn = Body(default=_CompleteIn()),
    db: Session = Depends(get_db),
):
    s = db.get(SessionRow, session_id)
    if s is None:
        raise HTTPException(404)
    s.completed_at = datetime.utcnow()
    s.parent_summary = payload.summary
    db.commit()
    return {"ok": True, "completed_at": s.completed_at}


# ---------- Attempts ----------
@router.post("/children/{child_id}/attempts", response_model=schemas.AttemptOut, status_code=201)
def record_attempt(
    child_id: int,
    payload: schemas.AttemptIn,
    db: Session = Depends(get_db),
):
    child = db.get(Child, child_id)
    if child is None:
        raise HTTPException(404, "Child not found")
    prob = db.get(Problem, payload.problem_id)
    if prob is None:
        raise HTTPException(404, "Problem not found")
    a = Attempt(child_id=child.id, **payload.model_dump())
    db.add(a)
    db.flush()
    update_skill_from_attempt(db, attempt=a)
    db.commit()
    db.refresh(a)
    return a


@router.get("/children/{child_id}/attempts", response_model=list[schemas.AttemptOut])
def list_attempts(child_id: int, limit: int = Query(50, le=500), db: Session = Depends(get_db)):
    rows = (
        db.execute(
            select(Attempt)
            .where(Attempt.child_id == child_id)
            .order_by(Attempt.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return rows


# ---------- Skills / Mastery ----------
@router.get("/children/{child_id}/skills", response_model=list[schemas.SkillOut])
def list_skills(child_id: int, db: Session = Depends(get_db)):
    return (
        db.execute(select(Skill).where(Skill.child_id == child_id))
        .scalars()
        .all()
    )


# ---------- Notes ----------
@router.post("/children/{child_id}/notes", response_model=schemas.NoteOut, status_code=201)
def create_note(child_id: int, payload: schemas.NoteIn, db: Session = Depends(get_db)):
    child = db.get(Child, child_id)
    if child is None:
        raise HTTPException(404, "Child not found")
    n = Note(child_id=child_id, **payload.model_dump())
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


@router.get("/children/{child_id}/notes", response_model=list[schemas.NoteOut])
def list_notes(child_id: int, db: Session = Depends(get_db)):
    return (
        db.execute(
            select(Note).where(Note.child_id == child_id).order_by(Note.created_at.desc())
        )
        .scalars()
        .all()
    )


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db)):
    n = db.get(Note, note_id)
    if n is None:
        raise HTTPException(404)
    db.delete(n)
    db.commit()


# ---------- Circle mode ----------
@router.post("/circle/sessions", status_code=201)
def start_circle_session(child_ids: list[int], db: Session = Depends(get_db)):
    children = [db.get(Child, cid) for cid in child_ids]
    children = [c for c in children if c is not None]
    if not children:
        raise HTTPException(400, "No valid children supplied")
    plan = circle_night_plan(db, children)
    # We attach to the first child for tracking; but it's a shared plan.
    s = SessionRow(child_id=children[0].id, mode="circle", plan=plan)
    db.add(s)
    db.commit()
    db.refresh(s)
    return {
        "id": s.id,
        "child_ids": [c.id for c in children],
        "mode": "circle",
        "plan": s.plan,
    }


# ---------- Export ----------
@router.put("/children/{child_id}/ai-digests")
def set_ai_digests(
    child_id: int,
    payload: schemas.AiOptIn,
    db: Session = Depends(get_db),
):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404)
    c.ai_digests_enabled = payload.enabled
    c.ai_digests_decided_at = datetime.utcnow()
    db.commit()
    return {"child_id": c.id, "ai_digests_enabled": c.ai_digests_enabled}


@router.get("/children/{child_id}/digests", response_model=list[schemas.DigestOut])
def list_digests(child_id: int, limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    rows = (
        db.execute(
            select(Digest)
            .where(Digest.child_id == child_id)
            .order_by(Digest.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return rows


@router.post("/children/{child_id}/digests/run")
def run_digest(
    child_id: int,
    hours: int = Query(24, ge=1, le=168),
    period_label: str = "adhoc",
    db: Session = Depends(get_db),
):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404)
    if not c.ai_digests_enabled:
        raise HTTPException(403, "AI digests are not enabled for this child")
    row = ai_generate_and_persist(db, c, hours=hours, period_label=period_label)
    return {
        "id": row.id,
        "summary": row.summary,
        "model_id": row.model_id,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "cost_usd": row.cost_usd,
        "error": row.error,
    }


@router.get("/children/{child_id}/export.json")
def export_json(child_id: int, db: Session = Depends(get_db)):
    child = db.get(Child, child_id)
    if child is None:
        raise HTTPException(404)
    attempts = (
        db.execute(select(Attempt).where(Attempt.child_id == child_id)).scalars().all()
    )
    skills = (
        db.execute(select(Skill).where(Skill.child_id == child_id)).scalars().all()
    )
    notes = (
        db.execute(select(Note).where(Note.child_id == child_id)).scalars().all()
    )
    sessions = (
        db.execute(select(SessionRow).where(SessionRow.child_id == child_id))
        .scalars()
        .all()
    )
    payload = {
        "child": {
            "id": child.id,
            "name": child.name,
            "grade": child.grade,
            "age": child.age,
            "interests": child.interests,
            "avatar": child.avatar,
            "color": child.color,
            "created_at": child.created_at.isoformat(),
        },
        "skills": [
            {
                "strand_id": s.strand_id,
                "level": s.level,
                "rolling_accuracy": s.rolling_accuracy,
                "streak": s.streak,
                "last_practiced": s.last_practiced.isoformat() if s.last_practiced else None,
                "mastery_notes": s.mastery_notes,
            }
            for s in skills
        ],
        "sessions": [
            {
                "id": s.id,
                "mode": s.mode,
                "plan": s.plan,
                "started_at": s.started_at.isoformat(),
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "parent_summary": s.parent_summary,
            }
            for s in sessions
        ],
        "attempts": [
            {
                "id": a.id,
                "problem_id": a.problem_id,
                "session_id": a.session_id,
                "answer_given": a.answer_given,
                "correct": a.correct,
                "hint_count": a.hint_count,
                "parent_rating": a.parent_rating,
                "strategy_note": a.strategy_note,
                "time_seconds": a.time_seconds,
                "created_at": a.created_at.isoformat(),
            }
            for a in attempts
        ],
        "notes": [
            {
                "id": n.id,
                "kind": n.kind,
                "body": n.body,
                "created_at": n.created_at.isoformat(),
            }
            for n in notes
        ],
        "exported_at": datetime.utcnow().isoformat(),
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="mathcircle_{child.name}.json"'},
    )


@router.get("/children/{child_id}/export.csv")
def export_csv(child_id: int, db: Session = Depends(get_db)):
    child = db.get(Child, child_id)
    if child is None:
        raise HTTPException(404)
    attempts = (
        db.execute(
            select(Attempt).where(Attempt.child_id == child_id).order_by(Attempt.created_at)
        )
        .scalars()
        .all()
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "created_at", "session_id", "problem_id", "problem_title",
        "strand", "kind", "level",
        "answer_given", "correct", "hint_count", "parent_rating",
        "strategy_note", "time_seconds",
    ])
    for a in attempts:
        prob = a.problem
        w.writerow([
            a.created_at.isoformat(),
            a.session_id or "",
            a.problem_id,
            prob.title if prob else "",
            prob.strand.key if prob and prob.strand else "",
            prob.kind if prob else "",
            prob.level if prob else "",
            a.answer_given,
            a.correct,
            a.hint_count,
            a.parent_rating or "",
            a.strategy_note,
            a.time_seconds,
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="mathcircle_{child.name}.csv"'},
    )

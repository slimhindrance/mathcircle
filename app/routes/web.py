"""Web UI routes (Jinja-rendered pages)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Attempt, Child, Digest, Note, Problem, Session as SessionRow, Skill, Strand
from ..ai_digest import generate_and_persist as ai_generate_and_persist
from ..session_generator import build_preview_session, build_session_plan, circle_night_plan

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _strand_lookup(db: Session) -> dict[int, Strand]:
    return {s.id: s for s in db.execute(select(Strand)).scalars().all()}


def _children(db: Session) -> list[Child]:
    return db.execute(select(Child).order_by(Child.created_at)).scalars().all()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    children = _children(db)
    strand_count = db.execute(select(func.count(Strand.id))).scalar_one()
    problem_count = db.execute(select(func.count(Problem.id))).scalar_one()
    return _templates(request).TemplateResponse(request, "home.html", {
            "children": children,
            "strand_count": strand_count,
            "problem_count": problem_count,
        })


@router.get("/children/new", response_class=HTMLResponse)
def child_new_form(request: Request):
    return _templates(request).TemplateResponse(request, "child_form.html", {"child": None})


@router.post("/children")
async def child_create(
    name: str = Form(...),
    grade: str = Form("K"),
    age: Optional[int] = Form(None),
    interests: str = Form(""),
    avatar: str = Form("🦊"),
    color: str = Form("#f4a261"),
    db: Session = Depends(get_db),
):
    c = Child(
        name=name.strip() or "Friend",
        grade=grade,
        age=age,
        interests=interests,
        avatar=avatar,
        color=color,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return RedirectResponse(f"/child/{c.id}", status_code=303)


@router.get("/child/{child_id}/edit", response_class=HTMLResponse)
def child_edit_form(child_id: int, request: Request, db: Session = Depends(get_db)):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404)
    return _templates(request).TemplateResponse(request, "child_form.html", {"child": c})


@router.post("/child/{child_id}/edit")
async def child_edit(
    child_id: int,
    name: str = Form(...),
    grade: str = Form("K"),
    age: Optional[int] = Form(None),
    interests: str = Form(""),
    avatar: str = Form("🦊"),
    color: str = Form("#f4a261"),
    db: Session = Depends(get_db),
):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404)
    c.name = name.strip() or c.name
    c.grade = grade
    c.age = age if age is not None else c.age
    c.interests = interests
    c.avatar = avatar
    c.color = color
    db.commit()
    return RedirectResponse(f"/child/{c.id}", status_code=303)


@router.get("/child/{child_id}", response_class=HTMLResponse)
def child_dashboard(child_id: int, request: Request, db: Session = Depends(get_db)):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404)
    strands = db.execute(select(Strand).order_by(Strand.sort_order)).scalars().all()
    skills = {
        s.strand_id: s
        for s in db.execute(select(Skill).where(Skill.child_id == child_id)).scalars().all()
    }
    sessions = (
        db.execute(
            select(SessionRow)
            .where(SessionRow.child_id == child_id)
            .order_by(desc(SessionRow.started_at))
            .limit(10)
        )
        .scalars()
        .all()
    )
    attempts = (
        db.execute(
            select(Attempt)
            .where(Attempt.child_id == child_id)
            .order_by(desc(Attempt.created_at))
            .limit(20)
        )
        .scalars()
        .all()
    )
    notes = (
        db.execute(
            select(Note).where(Note.child_id == child_id).order_by(desc(Note.created_at)).limit(10)
        )
        .scalars()
        .all()
    )
    total_attempts = db.execute(
        select(func.count(Attempt.id)).where(Attempt.child_id == child_id)
    ).scalar_one()
    total_correct = db.execute(
        select(func.count(Attempt.id)).where(
            Attempt.child_id == child_id, Attempt.correct.is_(True)
        )
    ).scalar_one()
    latest_digest = (
        db.execute(
            select(Digest).where(Digest.child_id == child_id).order_by(desc(Digest.created_at)).limit(1)
        )
        .scalars()
        .first()
    )
    return _templates(request).TemplateResponse(request, "child_dashboard.html", {
            "child": c,
            "strands": strands,
            "skills": skills,
            "sessions": sessions,
            "attempts": attempts,
            "notes": notes,
            "total_attempts": total_attempts,
            "total_correct": total_correct,
            "latest_digest": latest_digest,
        })


@router.post("/child/{child_id}/start_session")
def child_start_session(child_id: int, db: Session = Depends(get_db)):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404)
    plan = build_session_plan(db, c)
    s = SessionRow(child_id=child_id, mode="solo", plan=plan)
    db.add(s)
    db.commit()
    db.refresh(s)
    return RedirectResponse(f"/child/{child_id}/session/{s.id}", status_code=303)


@router.get("/child/{child_id}/session/{session_id}", response_class=HTMLResponse)
def session_view(
    child_id: int, session_id: int, request: Request, db: Session = Depends(get_db)
):
    c = db.get(Child, child_id)
    s = db.get(SessionRow, session_id)
    if c is None or s is None or s.child_id != child_id:
        raise HTTPException(404)
    plan = s.plan or []
    problems_by_id = {
        p.id: p
        for p in db.execute(
            select(Problem).where(Problem.id.in_([item["problem_id"] for item in plan]))
        )
        .scalars()
        .all()
    }
    strand_lookup = _strand_lookup(db)
    items = []
    for item in plan:
        prob = problems_by_id.get(item["problem_id"])
        if prob is None:
            continue
        items.append(
            {
                "kind": item["kind"],
                "position": item["position"],
                "problem": prob,
                "strand": strand_lookup.get(prob.strand_id),
                "explain_only": item.get("explain_prompt", False),
            }
        )
    items.sort(key=lambda it: it["position"])
    attempts = (
        db.execute(select(Attempt).where(Attempt.session_id == session_id))
        .scalars()
        .all()
    )
    attempts_by_problem = {a.problem_id: a for a in attempts}
    return _templates(request).TemplateResponse(request, "session.html", {
            "child": c,
            "session": s,
            "items": items,
            "attempts_by_problem": attempts_by_problem,
        })


@router.get("/strands", response_class=HTMLResponse)
def strand_browser(request: Request, db: Session = Depends(get_db)):
    strands = db.execute(select(Strand).order_by(Strand.sort_order)).scalars().all()
    counts = {
        sid: cnt
        for sid, cnt in db.execute(
            select(Problem.strand_id, func.count(Problem.id)).group_by(Problem.strand_id)
        ).all()
    }
    return _templates(request).TemplateResponse(request, "strands.html", {"strands": strands, "counts": counts})


@router.get("/strands/{strand_key}", response_class=HTMLResponse)
def strand_detail(
    strand_key: str,
    request: Request,
    level: Optional[int] = None,
    kind: Optional[str] = None,
    db: Session = Depends(get_db),
):
    strand = db.execute(select(Strand).where(Strand.key == strand_key)).scalar_one_or_none()
    if strand is None:
        raise HTTPException(404)
    stmt = select(Problem).where(Problem.strand_id == strand.id)
    if level:
        stmt = stmt.where(Problem.level == level)
    if kind:
        stmt = stmt.where(Problem.kind == kind)
    problems = db.execute(stmt.order_by(Problem.level, Problem.id)).scalars().all()
    return _templates(request).TemplateResponse(request, "strand_detail.html", {
            "strand": strand,
            "problems": problems,
            "level": level,
            "kind": kind,
        })


@router.get("/puzzles", response_class=HTMLResponse)
def puzzle_bank(
    request: Request,
    q: Optional[str] = None,
    strand: Optional[str] = None,
    level: Optional[int] = None,
    kind: Optional[str] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Problem)
    if strand:
        stmt = stmt.join(Strand).where(Strand.key == strand)
    if level:
        stmt = stmt.where(Problem.level == level)
    if kind:
        stmt = stmt.where(Problem.kind == kind)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            (func.lower(Problem.title).like(like))
            | (func.lower(Problem.prompt).like(like))
        )
    problems = db.execute(stmt.order_by(Problem.level, Problem.id).limit(200)).scalars().all()
    strands = db.execute(select(Strand).order_by(Strand.sort_order)).scalars().all()
    return _templates(request).TemplateResponse(request, "puzzles.html", {
            "problems": problems,
            "strands": strands,
            "q": q or "",
            "current_strand": strand,
            "current_level": level,
            "current_kind": kind,
        })


@router.get("/problem/{problem_id}", response_class=HTMLResponse)
def problem_detail(problem_id: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Problem, problem_id)
    if p is None:
        raise HTTPException(404)
    return _templates(request).TemplateResponse(request, "problem.html", {"problem": p, "strand": p.strand})


@router.get("/problem/{problem_id}/print", response_class=HTMLResponse)
def problem_print(problem_id: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Problem, problem_id)
    if p is None:
        raise HTTPException(404)
    return _templates(request).TemplateResponse(request, "problem_print.html", {"problem": p, "strand": p.strand})


@router.get("/parent/guide", response_class=HTMLResponse)
def parent_guide(request: Request):
    return _templates(request).TemplateResponse(request, "parent_guide.html")


@router.post("/child/{child_id}/ai-optin")
async def child_ai_optin(
    child_id: int,
    enabled: str = Form("false"),
    db: Session = Depends(get_db),
):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404)
    c.ai_digests_enabled = enabled.lower() == "true"
    from datetime import datetime as _dt
    c.ai_digests_decided_at = _dt.utcnow()
    db.commit()
    return RedirectResponse(f"/child/{child_id}", status_code=303)


@router.post("/child/{child_id}/digest/run")
def child_digest_run(child_id: int, db: Session = Depends(get_db)):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404)
    if not c.ai_digests_enabled:
        raise HTTPException(403, "AI digests not enabled")
    ai_generate_and_persist(db, c, hours=24, period_label="adhoc")
    return RedirectResponse(f"/child/{child_id}", status_code=303)


@router.get("/about", response_class=HTMLResponse)
def about(request: Request, db: Session = Depends(get_db)):
    """Public-facing pitch page. Caddy is configured to bypass basic-auth here."""
    strand_count = db.execute(select(func.count(Strand.id))).scalar_one()
    problem_count = db.execute(select(func.count(Problem.id))).scalar_one()
    return _templates(request).TemplateResponse(
        request,
        "about.html",
        {"problem_count": problem_count, "strand_count": strand_count},
    )


@router.get("/about/sample", response_class=HTMLResponse)
def about_sample(request: Request, db: Session = Depends(get_db)):
    """Read-only preview: one full sample session per grade (K, 1, 2). No auth."""
    grade_specs = [
        {"grade": "K", "label": "Kindergarten", "age": "5–6", "blurb": "Subitizing, ten-frames, AB patterns, position words. Counting confidently to 20."},
        {"grade": "1", "label": "Grade 1", "age": "6–7", "blurb": "Sums and differences within 20, missing addends, mystery numbers, balance thinking."},
        {"grade": "2", "label": "Grade 2", "age": "7–8", "blurb": "Place value to 100, two-step problems, growing patterns, early combinatorics."},
    ]
    samples = []
    for spec in grade_specs:
        plan = build_preview_session(db, grade=spec["grade"], seed=42)
        problems_by_id = {
            p.id: p
            for p in db.execute(
                select(Problem).where(
                    Problem.id.in_([item["problem_id"] for item in plan])
                )
            ).scalars().all()
        }
        strand_lookup = _strand_lookup(db)
        plan_items = []
        for item in plan:
            prob = problems_by_id.get(item["problem_id"])
            if prob is None:
                continue
            plan_items.append({
                "kind": item["kind"],
                "position": item["position"],
                "problem": prob,
                "strand": strand_lookup.get(prob.strand_id),
            })
        plan_items.sort(key=lambda it: it["position"])
        total_minutes = sum(it["problem"].minutes for it in plan_items)
        samples.append({**spec, "plan_items": plan_items, "total_minutes": total_minutes})
    return _templates(request).TemplateResponse(
        request, "about_sample.html", {"samples": samples}
    )


@router.get("/parent/notes/{child_id}", response_class=HTMLResponse)
def parent_notes(child_id: int, request: Request, db: Session = Depends(get_db)):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404)
    notes = (
        db.execute(
            select(Note).where(Note.child_id == child_id).order_by(desc(Note.created_at))
        )
        .scalars()
        .all()
    )
    return _templates(request).TemplateResponse(request, "notes.html", {"child": c, "notes": notes})


@router.post("/parent/notes/{child_id}")
async def parent_notes_post(
    child_id: int,
    body: str = Form(""),
    kind: str = Form("parent"),
    db: Session = Depends(get_db),
):
    c = db.get(Child, child_id)
    if c is None:
        raise HTTPException(404)
    if body.strip():
        db.add(Note(child_id=child_id, kind=kind, body=body.strip()))
        db.commit()
    return RedirectResponse(f"/parent/notes/{child_id}", status_code=303)


@router.post("/parent/notes/{note_id}/delete")
def parent_note_delete(note_id: int, db: Session = Depends(get_db)):
    n = db.get(Note, note_id)
    if n is None:
        raise HTTPException(404)
    cid = n.child_id
    db.delete(n)
    db.commit()
    return RedirectResponse(f"/parent/notes/{cid}", status_code=303)


@router.get("/circle", response_class=HTMLResponse)
def circle_index(request: Request, db: Session = Depends(get_db)):
    children = _children(db)
    return _templates(request).TemplateResponse(request, "circle.html", {"children": children, "session": None, "items": None})


@router.post("/circle/start")
async def circle_start(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    raw_ids = form.getlist("child_ids") if hasattr(form, "getlist") else [form.get("child_ids")]
    ids: list[int] = []
    for v in raw_ids:
        try:
            if v is not None:
                ids.append(int(v))
        except (TypeError, ValueError):
            pass
    children = [c for c in (db.get(Child, i) for i in ids) if c is not None]
    if not children:
        children = _children(db)
    if not children:
        raise HTTPException(400, "No children to run circle for")
    plan = circle_night_plan(db, children)
    s = SessionRow(child_id=children[0].id, mode="circle", plan=plan)
    db.add(s)
    db.commit()
    db.refresh(s)
    return RedirectResponse(f"/circle/session/{s.id}", status_code=303)


@router.get("/circle/session/{session_id}", response_class=HTMLResponse)
def circle_view(session_id: int, request: Request, db: Session = Depends(get_db)):
    s = db.get(SessionRow, session_id)
    if s is None or s.mode != "circle":
        raise HTTPException(404)
    plan = s.plan or []
    problems_by_id = {
        p.id: p
        for p in db.execute(
            select(Problem).where(Problem.id.in_([it["problem_id"] for it in plan]))
        )
        .scalars()
        .all()
    }
    strand_lookup = _strand_lookup(db)
    items = []
    for item in plan:
        prob = problems_by_id.get(item["problem_id"])
        if prob is None:
            continue
        items.append(
            {
                "kind": item["kind"],
                "position": item["position"],
                "problem": prob,
                "strand": strand_lookup.get(prob.strand_id),
            }
        )
    items.sort(key=lambda it: it["position"])
    children = _children(db)
    return _templates(request).TemplateResponse(request, "circle.html", {"children": children, "session": s, "items": items})

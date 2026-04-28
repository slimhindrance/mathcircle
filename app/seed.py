"""Load seed_problems.json into the database (idempotent)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import FORCE_RESEED, SEED_FILE
from .models import Child, GeneratedTemplate, Problem, Strand


def _load_json() -> dict[str, Any]:
    if not SEED_FILE.exists():
        raise FileNotFoundError(
            f"Seed file missing: {SEED_FILE}. Run `python data/build_seed.py` first."
        )
    return json.loads(SEED_FILE.read_text())


def _ensure_strands(db: Session, data: dict) -> dict[str, int]:
    """Insert/update strand metadata. Returns key -> id map."""
    by_key = {s.key: s for s in db.execute(select(Strand)).scalars().all()}
    for entry in data["strands"]:
        existing = by_key.get(entry["key"])
        if existing is None:
            existing = Strand(
                key=entry["key"],
                name=entry["name"],
                description=entry.get("description", ""),
                icon=entry.get("icon", ""),
                sort_order=entry.get("sort_order", 0),
            )
            db.add(existing)
            by_key[entry["key"]] = existing
        else:
            existing.name = entry["name"]
            existing.description = entry.get("description", "")
            existing.icon = entry.get("icon", "")
            existing.sort_order = entry.get("sort_order", 0)
    db.flush()
    return {s.key: s.id for s in by_key.values()}


def _ensure_problems(db: Session, data: dict, strand_ids: dict[str, int]) -> int:
    existing_slugs = {
        slug for (slug,) in db.execute(select(Problem.slug)).all()
    }
    added = 0
    for prob in data["problems"]:
        if prob["slug"] in existing_slugs and not FORCE_RESEED:
            continue
        sid = strand_ids.get(prob["strand"])
        if sid is None:
            continue
        if prob["slug"] in existing_slugs:
            row = db.execute(
                select(Problem).where(Problem.slug == prob["slug"])
            ).scalar_one()
            row.level = prob.get("level", 1)
            row.grade_band = prob.get("grade_band", "K-1")
            row.kind = prob.get("kind", "story")
            row.title = prob.get("title", "")
            row.prompt = prob.get("prompt", "")
            row.answer = str(prob.get("answer", ""))
            row.answer_type = prob.get("answer_type", "open")
            row.hints = prob.get("hints", [])
            row.strategies = prob.get("strategies", [])
            row.materials = prob.get("materials", [])
            row.tags = prob.get("tags", [])
            row.explain_prompt = prob.get("explain_prompt", "")
            row.parent_extension = prob.get("parent_extension", "")
            row.minutes = prob.get("minutes", 3)
            row.template = prob.get("template")
        else:
            row = Problem(
                slug=prob["slug"],
                strand_id=sid,
                level=prob.get("level", 1),
                grade_band=prob.get("grade_band", "K-1"),
                kind=prob.get("kind", "story"),
                title=prob.get("title", ""),
                prompt=prob.get("prompt", ""),
                answer=str(prob.get("answer", "")),
                answer_type=prob.get("answer_type", "open"),
                hints=prob.get("hints", []),
                strategies=prob.get("strategies", []),
                materials=prob.get("materials", []),
                tags=prob.get("tags", []),
                explain_prompt=prob.get("explain_prompt", ""),
                parent_extension=prob.get("parent_extension", ""),
                minutes=prob.get("minutes", 3),
                template=prob.get("template"),
            )
            db.add(row)
            added += 1
    return added


def _ensure_templates(db: Session, data: dict, strand_ids: dict[str, int]) -> None:
    existing = {name for (name,) in db.execute(select(GeneratedTemplate.name)).all()}
    for entry in data.get("templates", []):
        if entry["name"] in existing:
            continue
        sid = strand_ids.get(entry["strand"])
        if sid is None:
            continue
        db.add(
            GeneratedTemplate(
                name=entry["name"],
                strand_id=sid,
                level=entry.get("level", 1),
                kind=entry.get("kind", "story"),
                template=entry["template"],
            )
        )


def seed_database(db: Session) -> dict[str, int]:
    """Seed strands, problems, templates. Returns {added, total}."""
    data = _load_json()
    strand_ids = _ensure_strands(db, data)
    added = _ensure_problems(db, data, strand_ids)
    _ensure_templates(db, data, strand_ids)
    db.flush()
    total = db.execute(select(Problem)).scalars().all()
    return {"added": added, "total": len(total)}


def ensure_default_children(db: Session) -> None:
    """Create two starter children if none exist."""
    existing = db.execute(select(Child)).scalars().first()
    if existing is not None:
        return
    db.add_all(
        [
            Child(
                name="Danica",
                grade="K",
                age=6,
                interests="",
                avatar="🦊",
                color="#f4a261",
            ),
            Child(
                name="Mila",
                grade="1",
                age=7,
                interests="",
                avatar="🐝",
                color="#e9c46a",
            ),
        ]
    )

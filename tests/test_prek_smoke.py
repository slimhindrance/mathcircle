"""End-to-end smoke tests for the Pre-K flow.

Covers everything the Pre-K work touched:

  - Data integrity: 62+62 PK problems, all carry the new fields cleanly.
  - Helpers: _prek_ready_to_graduate threshold logic.
  - Session generator: PK child gets a level-aware parent-led plan; K-2 kids
    still get the K-2 pipeline.
  - Skill engine: PK attempts feed Skill rows, levels promote on mastery.
  - Routes: /child/{id}/promote-to-k flips grade; /about renders with the
    Living Curriculum copy; /admin/captures requires auth.
  - Template render: a parent-led session item renders the new parent-script
    UI without Jinja errors.
"""
from __future__ import annotations

from datetime import datetime

import pytest


# ---------- 1. Data integrity ----------

def test_prek_problems_present(client):
    r = client.get("/api/problems?limit=500")
    assert r.status_code == 200
    problems = r.json()
    pk = [p for p in problems if p.get("grade_band") == "PK"]
    by_level = {}
    for p in pk:
        by_level.setdefault(p["level"], 0)
        by_level[p["level"]] += 1
    assert by_level.get(1, 0) >= 60, f"Expected ~62 PK Level 1, got {by_level.get(1)}"
    assert by_level.get(2, 0) >= 60, f"Expected ~62 PK Level 2, got {by_level.get(2)}"


def test_all_prek_problems_have_required_fields():
    from app.database import SessionLocal
    from app.models import Problem
    from sqlalchemy import select

    with SessionLocal() as db:
        pk_problems = db.execute(
            select(Problem).where(Problem.grade_band == "PK")
        ).scalars().all()

    assert len(pk_problems) >= 120, f"Got only {len(pk_problems)} PK problems in DB"
    bad: list[str] = []
    valid_tags = {"how_why", "another_way", "what_if", "what_noticed"}
    for p in pk_problems:
        if not p.parent_script or len(p.parent_script.strip()) < 20:
            bad.append(f"{p.slug}: empty/tiny parent_script")
        if p.magic_prompt_tag not in valid_tags:
            bad.append(f"{p.slug}: invalid magic_prompt_tag={p.magic_prompt_tag!r}")
        if p.kind != "parent_led":
            bad.append(f"{p.slug}: kind={p.kind!r}, expected parent_led")
        if not p.materials and "None" not in (p.parent_script or ""):
            # Some problems legitimately need no materials, but most should list them.
            pass  # don't fail on this
        if p.level not in (1, 2):
            bad.append(f"{p.slug}: level={p.level}, expected 1 or 2")
    assert not bad, "PK problem field issues:\n  " + "\n  ".join(bad[:10])


def test_prek_covers_all_strands():
    from app.database import SessionLocal
    from app.models import Problem, Strand
    from sqlalchemy import select

    with SessionLocal() as db:
        strand_keys = {s.key for s in db.execute(select(Strand)).scalars().all()}
        pk_problems = db.execute(
            select(Problem).where(Problem.grade_band == "PK")
        ).scalars().all()
        strands_with_pk: set[str] = set()
        for p in pk_problems:
            strand = db.get(Strand, p.strand_id)
            if strand:
                strands_with_pk.add(strand.key)

    assert strands_with_pk == strand_keys, (
        f"PK missing strands: {strand_keys - strands_with_pk}"
    )


def test_prek_slugs_unique():
    from app.database import SessionLocal
    from app.models import Problem
    from sqlalchemy import select

    with SessionLocal() as db:
        pk = db.execute(
            select(Problem.slug).where(Problem.grade_band == "PK")
        ).all()
    slugs = [s[0] for s in pk]
    assert len(slugs) == len(set(slugs)), "Duplicate PK slugs detected"


# ---------- 2. Helper logic (no DB) ----------

def test_starting_level_pk_returns_one():
    from app.session_generator import _starting_level
    assert _starting_level("PK") == 1
    assert _starting_level("PreK") == 1
    assert _starting_level("pk") == 1
    assert _starting_level("K") == 1
    assert _starting_level("1") == 2
    assert _starting_level("2") == 3


class _FakeChild:
    def __init__(self, grade: str):
        self.grade = grade


class _FakeSkill:
    def __init__(self, level: int = 1, last_practiced: datetime | None = None):
        self.level = level
        self.last_practiced = last_practiced or datetime.utcnow()


class _FakeAttempt:
    def __init__(self, rating: str | None):
        self.parent_rating = rating


def test_prek_ready_to_graduate_rejects_non_pk():
    from app.routes.web import _prek_ready_to_graduate
    child = _FakeChild("K")
    skills = {i: _FakeSkill(2) for i in range(10)}
    assert not _prek_ready_to_graduate(child, skills, total_attempts=100, recent=[])


def test_prek_ready_to_graduate_rejects_low_attempts():
    from app.routes.web import _prek_ready_to_graduate
    child = _FakeChild("PK")
    skills = {i: _FakeSkill(2) for i in range(10)}
    # 8 attempts (old threshold) — must NOT graduate
    assert not _prek_ready_to_graduate(child, skills, total_attempts=8, recent=[])
    # 24 attempts — still below the 25 threshold
    assert not _prek_ready_to_graduate(child, skills, total_attempts=24, recent=[])


def test_prek_ready_to_graduate_rejects_insufficient_level_2_strands():
    from app.routes.web import _prek_ready_to_graduate
    child = _FakeChild("PK")
    # 6 at L2, 4 at L1 — below the 7-strand bar
    skills = {i: _FakeSkill(2) for i in range(6)}
    skills.update({i: _FakeSkill(1) for i in range(6, 10)})
    assert not _prek_ready_to_graduate(child, skills, total_attempts=30, recent=[])


def test_prek_ready_to_graduate_accepts_l2_mastery():
    from app.routes.web import _prek_ready_to_graduate
    child = _FakeChild("PK")
    skills = {i: _FakeSkill(2) for i in range(7)}  # 7 strands at L2
    skills.update({i: _FakeSkill(1) for i in range(7, 10)})  # 3 at L1
    recent = [_FakeAttempt("easy")] * 5
    assert _prek_ready_to_graduate(child, skills, total_attempts=30, recent=recent)


def test_prek_ready_to_graduate_rejects_recent_struggle():
    from app.routes.web import _prek_ready_to_graduate
    child = _FakeChild("PK")
    skills = {i: _FakeSkill(2) for i in range(8)}
    skills.update({i: _FakeSkill(1) for i in range(8, 10)})
    # Two "too_hard" in last 5 — should kill the signal
    recent = [_FakeAttempt("too_hard"), _FakeAttempt("too_hard"), _FakeAttempt("easy"),
              _FakeAttempt("good_struggle"), _FakeAttempt("easy")]
    assert not _prek_ready_to_graduate(child, skills, total_attempts=30, recent=recent)


# ---------- 3. Session generator (real DB, real PK problems) ----------

def _make_child(client, grade: str, name: str = "Tot") -> int:
    """Helper: create a child via the API and return its id."""
    r = client.post(
        "/api/children",
        json={"name": name, "grade": grade, "age": 4 if grade == "PK" else 6, "interests": ""},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_pk_session_returns_two_parent_led_problems(client):
    cid = _make_child(client, "PK", "PKtest1")
    r = client.post(f"/api/children/{cid}/sessions")
    assert r.status_code == 201, r.text
    plan = r.json()["plan"]
    assert len(plan) == 2, f"Expected 2-item PK plan, got {len(plan)}: {plan}"
    for item in plan:
        assert item["kind"] == "parent_led", f"PK plan should be all parent_led, got {item}"
    # All picked problems should be PK Level 1 (no skill data yet)
    from app.database import SessionLocal
    from app.models import Problem
    with SessionLocal() as db:
        for item in plan:
            p = db.get(Problem, item["problem_id"])
            assert p.grade_band == "PK"
            assert p.level == 1, f"Fresh PK child should get L1, got L{p.level}"


def test_k2_session_does_not_serve_pk_problems(client):
    """Regression: a K kid must not get parent_led PK problems mixed in."""
    cid = _make_child(client, "K", "Ktest1")
    r = client.post(f"/api/children/{cid}/sessions")
    assert r.status_code == 201, r.text
    plan = r.json()["plan"]
    assert len(plan) >= 3
    from app.database import SessionLocal
    from app.models import Problem
    with SessionLocal() as db:
        for item in plan:
            p = db.get(Problem, item["problem_id"])
            assert p.kind != "parent_led", (
                f"K kid got a parent_led PK problem: {p.slug}"
            )
            assert p.grade_band != "PK", (
                f"K kid got a PK-banded problem: {p.slug}"
            )


def test_pk_session_picks_level_2_when_skill_advanced(client):
    """If the child has skill.level==2 in a strand, picks should land in L2 for that strand."""
    from app.database import SessionLocal
    from app.models import Child, Skill, Strand
    from sqlalchemy import select

    cid = _make_child(client, "PK", "PKadvanced")
    with SessionLocal() as db:
        # Force-set every strand skill to level 2 for this child
        strands = db.execute(select(Strand)).scalars().all()
        for s in strands:
            db.add(Skill(child_id=cid, strand_id=s.id, level=2))
        db.commit()

    r = client.post(f"/api/children/{cid}/sessions")
    assert r.status_code == 201, r.text
    plan = r.json()["plan"]
    assert len(plan) == 2
    from app.database import SessionLocal
    from app.models import Problem
    with SessionLocal() as db:
        for item in plan:
            p = db.get(Problem, item["problem_id"])
            assert p.grade_band == "PK"
            assert p.level == 2, (
                f"L2-advanced PK child should get L2 problems, got L{p.level} ({p.slug})"
            )


# ---------- 4. Skill engine ----------

def test_pk_attempt_creates_skill_row(client):
    """A PK attempt should populate Skill rows the same way K-2 does."""
    from app.database import SessionLocal
    from app.models import Skill
    from sqlalchemy import select

    cid = _make_child(client, "PK", "PKskill1")
    r = client.post(f"/api/children/{cid}/sessions")
    plan = r.json()["plan"]
    sid = r.json()["id"]
    first = plan[0]
    client.post(
        f"/api/children/{cid}/attempts",
        json={
            "problem_id": first["problem_id"],
            "session_id": sid,
            "answer_given": "",
            "correct": True,
            "parent_rating": "easy",
            "strategy_note": "test",
            "time_seconds": 60,
        },
    )
    with SessionLocal() as db:
        skills = db.execute(select(Skill).where(Skill.child_id == cid)).scalars().all()
    assert skills, "No Skill row created after PK attempt"


def test_pk_easy_streak_promotes_to_level_2(client):
    """Two 'easy' attempts in the same strand should promote that strand to L2."""
    from app.database import SessionLocal
    from app.models import Child, Problem, Skill, Strand
    from sqlalchemy import select

    cid = _make_child(client, "PK", "PKpromote")
    # Pick a known PK L1 problem in number_sense and submit two easy attempts.
    with SessionLocal() as db:
        ns = db.execute(select(Strand).where(Strand.key == "number_sense")).scalar_one()
        prob = db.execute(
            select(Problem)
            .where(Problem.grade_band == "PK", Problem.level == 1, Problem.strand_id == ns.id)
            .limit(1)
        ).scalar_one()
        pid = prob.id
        ns_id = ns.id

    # Start a session so we have a session_id to attach attempts to
    r = client.post(f"/api/children/{cid}/sessions")
    sid = r.json()["id"]

    for _ in range(3):  # three easy attempts; streak >= 2 triggers promote
        client.post(
            f"/api/children/{cid}/attempts",
            json={
                "problem_id": pid,
                "session_id": sid,
                "answer_given": "",
                "correct": True,
                "parent_rating": "easy",
                "strategy_note": "easy streak",
                "time_seconds": 60,
            },
        )

    with SessionLocal() as db:
        sk = db.execute(
            select(Skill).where(Skill.child_id == cid, Skill.strand_id == ns_id)
        ).scalar_one()
    assert sk.level >= 2, f"Expected level >= 2 after easy streak, got {sk.level}"


def test_pk_too_hard_drops_level(client):
    from app.database import SessionLocal
    from app.models import Problem, Skill, Strand
    from sqlalchemy import select

    cid = _make_child(client, "PK", "PKdrop")

    with SessionLocal() as db:
        ns = db.execute(select(Strand).where(Strand.key == "number_sense")).scalar_one()
        # Start the child at level 2 for this strand so we can see a drop to 1.
        db.add(Skill(child_id=cid, strand_id=ns.id, level=2))
        db.commit()
        prob = db.execute(
            select(Problem)
            .where(Problem.grade_band == "PK", Problem.strand_id == ns.id)
            .limit(1)
        ).scalar_one()
        pid = prob.id
        ns_id = ns.id

    r = client.post(f"/api/children/{cid}/sessions")
    sid = r.json()["id"]
    client.post(
        f"/api/children/{cid}/attempts",
        json={
            "problem_id": pid,
            "session_id": sid,
            "answer_given": "",
            "correct": False,
            "parent_rating": "too_hard",
            "strategy_note": "",
            "time_seconds": 30,
        },
    )

    with SessionLocal() as db:
        sk = db.execute(
            select(Skill).where(Skill.child_id == cid, Skill.strand_id == ns_id)
        ).scalar_one()
    assert sk.level == 1, f"Expected drop from 2 → 1, got {sk.level}"


# ---------- 5. Promotion route ----------

def test_promote_to_k_route_flips_grade(client):
    from app.database import SessionLocal
    from app.models import Child

    cid = _make_child(client, "PK", "PKpromoter")
    r = client.post(f"/child/{cid}/promote-to-k", follow_redirects=False)
    assert r.status_code in (303, 307)
    with SessionLocal() as db:
        c = db.get(Child, cid)
    assert c.grade == "K"


def test_promote_to_k_route_noop_for_non_pk(client):
    from app.database import SessionLocal
    from app.models import Child

    cid = _make_child(client, "1", "FirstGrader")
    r = client.post(f"/child/{cid}/promote-to-k", follow_redirects=False)
    # Route returns redirect either way; the grade just shouldn't change.
    assert r.status_code in (303, 307)
    with SessionLocal() as db:
        c = db.get(Child, cid)
    assert c.grade == "1", "Non-PK child shouldn't be flipped to K"


# ---------- 6. HTTP / template smoke ----------

def test_about_page_renders_with_living_curriculum_copy(client):
    r = client.get("/about")
    assert r.status_code == 200
    body = r.text
    assert "Living curriculum" in body or "living curriculum" in body
    assert "grows with the child" in body
    assert "Pre-K" in body
    # The Pre-K depth claim — make sure we didn't accidentally delete it
    assert "Level 2" in body or "level 2" in body


def test_admin_captures_requires_auth(client):
    r = client.get("/admin/captures")
    # require_admin → 401 unauthenticated
    assert r.status_code in (401, 403), f"Admin route returned {r.status_code}"


def test_signin_form_renders(client):
    r = client.get("/auth/sign-in")
    assert r.status_code == 200
    assert "Sign in" in r.text or "sign in" in r.text


def test_landing_page_advertises_pk(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Pre-K" in r.text, "Landing page should advertise Pre-K now that it's live"


# ---------- 7. Template render for a parent_led problem ----------

def test_session_template_renders_parent_led(client):
    """End-to-end: PK child → start session → fetch session page → contains parent script."""
    cid = _make_child(client, "PK", "PKrender")
    r = client.post(f"/api/children/{cid}/sessions")
    assert r.status_code == 201
    sid = r.json()["id"]

    # Render the actual session HTML page.
    r = client.get(f"/child/{cid}/session/{sid}")
    assert r.status_code == 200, r.text[:500]
    body = r.text
    # The parent-led layout markers we added in session.html:
    assert "Parent script" in body, "parent-script card not in rendered HTML"
    assert "Magic prompt" in body, "magic-prompt card not in rendered HTML"
    # Optional capture field is part of the layout
    assert "what your kid said" in body.lower() or "capture" in body.lower()

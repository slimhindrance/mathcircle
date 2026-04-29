"""Adaptive session composer.

Builds a 15–25 minute session in the requested shape:

    - 3 warm-up mental-math questions
    - 1 rich puzzle
    - 1 visual / manipulative task
    - 1 story problem
    - 1 "explain your thinking" prompt (attached to the rich puzzle)
    - 1 optional parent extension

Adaptive logic
--------------
Per (child, strand) we keep a Skill row with rolling accuracy and a level
1..7. The composer:

* Reads each child's skill levels.
* For each slot, picks problems near the relevant level (preferring level
  matches, then ±1) across a balanced rotation of strands.
* Avoids problems the child has attempted in the last `cooldown` sessions
  (default = 4) so they don't loop.
* Rotates strands across days so all 10 get touched over a week.
* For warm-ups and selected slots, mixes in **parametric problems** from
  the template generators — these never repeat, so the bank is effectively
  infinite for those slots.

Adaptation runs after attempts are recorded (`update_skill_from_attempt`):
- correct + low hints + parent_rating != "too_hard" → bump streak/accuracy
- 3 in a row correct at current level → consider level-up
- "too_hard" or accuracy < 40% over last 5 → level-down
- "good_struggle" parent rating → keep level (sweet spot)
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import SESSION_SHAPE, STRAND_KEYS
from .materials import normalize as normalize_materials
from .models import (
    Attempt,
    Child,
    GeneratedTemplate,
    Problem,
    Session as SessionRow,
    Skill,
    Strand,
)
from .problem_generator import GeneratedProblem, generate_from_template

# Probability that a slot pulls from a generator (vs the curated bank) when
# both are available. Slots NOT in this map use only curated problems.
_GENERATOR_PROBABILITY = {
    "warm_up": 0.6,        # warm-ups benefit most from infinite variety
    "rich_puzzle": 0.35,   # mix curated gems with parametric
    "story": 0.4,
    "visual": 0.2,         # visual problems mostly need handcrafted artwork prompts
    "game": 0.0,           # games are inherently re-playable; keep curated
    "explain": 0.0,        # attached to existing rich puzzle, no generation
    "parent_extension": 0.0,
}

# Strand rotation per "day of session" — picks 4 strands focus per session.
_DAILY_FOCUS = [
    ["number_sense", "add_sub_structures", "patterns", "geometry_spatial"],
    ["number_sense", "missing_number_stories", "logic_classification", "math_games"],
    ["number_sense", "equality_balance", "combinatorics_counting", "measurement"],
    ["add_sub_structures", "patterns", "logic_classification", "geometry_spatial"],
    ["missing_number_stories", "equality_balance", "combinatorics_counting", "math_games"],
    ["number_sense", "add_sub_structures", "missing_number_stories", "geometry_spatial"],
    ["patterns", "logic_classification", "measurement", "math_games"],
]


def _today_focus(child: Child, today: datetime | None = None) -> list[str]:
    """Pick the strand rotation for today, deterministic per (child, day)."""
    today = today or datetime.utcnow()
    day_of_year = today.timetuple().tm_yday
    idx = (day_of_year + (child.id or 0)) % len(_DAILY_FOCUS)
    return _DAILY_FOCUS[idx]


def _strand_id_map(db: Session) -> dict[str, int]:
    rows = db.execute(select(Strand)).scalars().all()
    return {s.key: s.id for s in rows}


def _ensure_skills(db: Session, child: Child) -> dict[str, Skill]:
    """Make sure every strand has a Skill row for the child; return key -> Skill."""
    strand_rows = db.execute(select(Strand)).scalars().all()
    existing = db.execute(
        select(Skill).where(Skill.child_id == child.id)
    ).scalars().all()
    by_key = {s.strand.key: s for s in existing if s.strand}
    for strand in strand_rows:
        if strand.key not in by_key:
            sk = Skill(
                child_id=child.id,
                strand_id=strand.id,
                level=_starting_level(child.grade),
            )
            db.add(sk)
            by_key[strand.key] = sk
    db.flush()
    return by_key


def _starting_level(grade: str) -> int:
    g = (grade or "").upper()
    if g in ("PK", "K"):
        return 1
    if g == "1":
        return 2
    if g == "2":
        return 3
    return 2


def _recent_attempted_problem_ids(
    db: Session, child_id: int, since_sessions: int = 4
) -> set[int]:
    """Problems already used in the child's last N sessions."""
    last = (
        db.execute(
            select(SessionRow.id)
            .where(SessionRow.child_id == child_id)
            .order_by(SessionRow.started_at.desc())
            .limit(since_sessions)
        )
        .scalars()
        .all()
    )
    if not last:
        return set()
    rows = db.execute(
        select(Attempt.problem_id).where(Attempt.session_id.in_(last))
    ).all()
    return {r[0] for r in rows}


def _materials_ok(prob: Problem, excluded_materials: set[str] | None) -> bool:
    """True if this problem's materials don't intersect the excluded set."""
    if not excluded_materials:
        return True
    needed = normalize_materials(prob.materials or [])
    return needed.isdisjoint(excluded_materials)


def _pick_problem(
    db: Session,
    *,
    kind: str,
    strand_keys: list[str],
    target_level: int,
    avoid: set[int],
    rng: random.Random,
    excluded_materials: set[str] | None = None,
) -> Problem | None:
    """Pick a problem matching the slot. Tries strict match → relaxes.

    May return a freshly-generated parametric problem (persisted into the DB)
    when one of the requested strands has a matching template and the
    per-kind generator probability fires.

    `excluded_materials`: canonical material keys the parent says they DON'T
    have. Any candidate whose materials intersect this set is filtered out.
    """
    # 1) Try the generator path first for kinds that benefit from it.
    gen_prob = _GENERATOR_PROBABILITY.get(kind, 0.0)
    if gen_prob > 0 and rng.random() < gen_prob:
        gen_problem = _generate_and_persist(
            db,
            preferred_strands=strand_keys,
            preferred_kind=kind,
            target_level=target_level,
            rng=rng,
        )
        if gen_problem is not None and _materials_ok(gen_problem, excluded_materials):
            return gen_problem

    # 2) Fall back to the curated bank, with progressive relaxation.
    strand_ids = _strand_id_map(db)
    strand_filter = [strand_ids[k] for k in strand_keys if k in strand_ids]

    # Progressive relaxation: respect avoid + materials first, then drop avoid
    # (allow recent-session repeats) before dropping the materials filter.
    for ignore_avoid in [False, True]:
        for relax_kind in [False, True]:
            for level_radius in [0, 1, 2]:
                stmt = select(Problem).where(
                    Problem.strand_id.in_(strand_filter),
                    Problem.level >= max(1, target_level - level_radius),
                    Problem.level <= min(7, target_level + level_radius),
                )
                if not relax_kind:
                    stmt = stmt.where(Problem.kind == kind)
                rows = db.execute(stmt).scalars().all()
                if not ignore_avoid:
                    rows = [r for r in rows if r.id not in avoid]
                rows = [r for r in rows if _materials_ok(r, excluded_materials)]
                if rows:
                    return rng.choice(rows)
    # Last resort: any strand, any kind, materials-permitting
    rows = db.execute(select(Problem).where(Problem.level == target_level)).scalars().all()
    rows = [r for r in rows if _materials_ok(r, excluded_materials)]
    rows = [r for r in rows if r.id not in avoid] or rows
    return rng.choice(rows) if rows else None


def _generate_and_persist(
    db: Session,
    *,
    preferred_strands: list[str],
    preferred_kind: str,
    target_level: int,
    rng: random.Random,
) -> Problem | None:
    """Pick a matching template, generate a fresh problem, persist as a Problem row."""
    # Find templates matching the preferred strands & kind & level (radius 1).
    stmt = (
        select(GeneratedTemplate)
        .join(Strand, GeneratedTemplate.strand_id == Strand.id)
        .where(Strand.key.in_(preferred_strands))
    )
    candidates = db.execute(stmt).scalars().all()
    if not candidates:
        return None

    def _score(t: GeneratedTemplate) -> int:
        kind_match = 0 if t.kind == preferred_kind else 2
        level_match = abs((t.level or 1) - target_level)
        return kind_match + level_match

    candidates.sort(key=_score)
    # Pick from the best-scoring tier with some randomness
    best_score = _score(candidates[0])
    tier = [t for t in candidates if _score(t) <= best_score + 1]
    template = rng.choice(tier)

    seed = rng.randint(1, 1_000_000_000)
    gen = generate_from_template(template, seed=seed)

    # Strand id for the generated problem
    strand_row = (
        db.execute(select(Strand).where(Strand.key == gen.strand))
        .scalar_one_or_none()
    )
    if strand_row is None:
        return None

    # Each generated problem gets a unique slug (seed-based) — collision-safe.
    existing = db.execute(
        select(Problem).where(Problem.slug == gen.slug)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = Problem(
        slug=gen.slug,
        strand_id=strand_row.id,
        level=gen.level,
        grade_band="K-2",
        kind=gen.kind,
        title=gen.title,
        prompt=gen.prompt,
        answer=gen.answer,
        answer_type=gen.answer_type,
        hints=gen.hints,
        strategies=gen.strategies,
        materials=gen.materials,
        tags=gen.tags + ["auto"],
        explain_prompt=gen.explain_prompt,
        parent_extension=gen.parent_extension,
        minutes=gen.minutes,
        template={"source_template": template.name, "seed": seed},
    )
    db.add(row)
    db.flush()
    return row


def _choose_warmup_strands(focus: list[str], skills: dict[str, Skill]) -> list[str]:
    """Three strands for warm-ups, biased toward number_sense + add_sub."""
    base = ["number_sense", "add_sub_structures"]
    extra = [s for s in focus if s not in base]
    return base + extra[:1]


def build_session_plan(
    db: Session,
    child: Child,
    *,
    mode: str = "solo",
    seed: int | None = None,
    excluded_materials: set[str] | None = None,
) -> list[dict]:
    """Compose today's session plan for a child.

    `excluded_materials`: canonical material keys (from app.materials) that
    the parent says they DON'T have available. Composer filters candidates
    accordingly; cooldown is loosened silently if the filtered pool runs thin.
    """
    rng = random.Random(seed)
    skills = _ensure_skills(db, child)
    focus = _today_focus(child)
    avoid = _recent_attempted_problem_ids(db, child.id)

    plan: list[dict] = []
    pos = 1

    # warm-up x N (3 by default), drawn from biased strands
    warmup_strands = _choose_warmup_strands(focus, skills)
    for _ in range(SESSION_SHAPE["warm_up"]):
        strand = rng.choice(warmup_strands)
        sk = skills.get(strand)
        target = sk.level if sk else _starting_level(child.grade)
        prob = _pick_problem(
            db,
            kind="warm_up",
            strand_keys=[strand],
            target_level=max(1, target - 1),  # warm-ups slightly easier
            avoid=avoid,
            rng=rng,
            excluded_materials=excluded_materials,
        )
        if prob:
            avoid.add(prob.id)
            plan.append(_plan_item(prob, "warm_up", pos))
            pos += 1

    # rich puzzle
    for _ in range(SESSION_SHAPE["rich_puzzle"]):
        strand = rng.choice(focus)
        sk = skills.get(strand)
        target = sk.level if sk else _starting_level(child.grade)
        prob = _pick_problem(
            db,
            kind="rich_puzzle",
            strand_keys=focus,
            target_level=target,
            avoid=avoid,
            rng=rng,
            excluded_materials=excluded_materials,
        )
        if prob:
            avoid.add(prob.id)
            plan.append(_plan_item(prob, "rich_puzzle", pos))
            pos += 1

    # visual / manipulative
    for _ in range(SESSION_SHAPE["visual"]):
        prob = _pick_problem(
            db,
            kind="visual",
            strand_keys=focus,
            target_level=_avg_level(skills, focus),
            avoid=avoid,
            rng=rng,
            excluded_materials=excluded_materials,
        )
        if prob:
            avoid.add(prob.id)
            plan.append(_plan_item(prob, "visual", pos))
            pos += 1

    # story problem
    for _ in range(SESSION_SHAPE["story"]):
        prob = _pick_problem(
            db,
            kind="story",
            strand_keys=["add_sub_structures", "missing_number_stories", "measurement"],
            target_level=_avg_level(skills, ["add_sub_structures", "missing_number_stories"]),
            avoid=avoid,
            rng=rng,
            excluded_materials=excluded_materials,
        )
        if prob:
            avoid.add(prob.id)
            plan.append(_plan_item(prob, "story", pos))
            pos += 1

    # explain prompt — attached to the rich puzzle if present
    rich_items = [it for it in plan if it["kind"] == "rich_puzzle"]
    if rich_items:
        plan.append(
            {
                "kind": "explain",
                "problem_id": rich_items[0]["problem_id"],
                "position": pos,
                "strand_key": rich_items[0]["strand_key"],
                "title": "Explain your thinking",
                "minutes": 3,
                "explain_prompt": True,
            }
        )
        pos += 1

    # parent extension — pick a problem with a parent_extension
    ext_prob = _pick_problem_with_extension(db, focus, excluded_materials)
    if ext_prob:
        plan.append(
            {
                "kind": "parent_extension",
                "problem_id": ext_prob.id,
                "position": pos,
                "strand_key": ext_prob.strand.key if ext_prob.strand else "",
                "title": ext_prob.title,
                "minutes": 5,
            }
        )

    return plan


def _avg_level(skills: dict[str, Skill], keys: Iterable[str]) -> int:
    vals = [skills[k].level for k in keys if k in skills]
    return max(1, round(sum(vals) / len(vals))) if vals else 2


def _plan_item(prob: Problem, kind: str, pos: int) -> dict:
    return {
        "kind": kind,
        "problem_id": prob.id,
        "position": pos,
        "strand_key": prob.strand.key if prob.strand else "",
        "title": prob.title,
        "minutes": prob.minutes,
    }


def _pick_problem_with_extension(
    db: Session, focus: list[str], excluded_materials: set[str] | None = None
) -> Problem | None:
    strand_ids = _strand_id_map(db)
    sids = [strand_ids[k] for k in focus if k in strand_ids]
    rows = (
        db.execute(
            select(Problem)
            .where(Problem.strand_id.in_(sids))
            .where(Problem.parent_extension != "")
        )
        .scalars()
        .all()
    )
    rows = [r for r in rows if _materials_ok(r, excluded_materials)]
    return random.choice(rows) if rows else None


def update_skill_from_attempt(
    db: Session,
    *,
    attempt: Attempt,
) -> Skill | None:
    """Apply the attempt to the matching Skill row; return updated row."""
    if attempt.problem is None:
        return None
    strand_id = attempt.problem.strand_id
    sk = db.execute(
        select(Skill).where(
            Skill.child_id == attempt.child_id,
            Skill.strand_id == strand_id,
        )
    ).scalar_one_or_none()
    if sk is None:
        sk = Skill(
            child_id=attempt.child_id,
            strand_id=strand_id,
            level=attempt.problem.level,
        )
        db.add(sk)
        db.flush()

    correct = bool(attempt.correct)
    rating = attempt.parent_rating

    # Rolling accuracy across last 5 attempts in this strand
    recent = (
        db.execute(
            select(Attempt)
            .where(Attempt.child_id == attempt.child_id)
            .where(Attempt.problem_id == Attempt.problem_id)  # placeholder, see below
            .order_by(Attempt.created_at.desc())
            .limit(5)
        )
        .scalars()
        .all()
    )
    # filter to same strand
    recent = [
        a for a in recent
        if a.problem and a.problem.strand_id == strand_id
    ][:5]
    if recent:
        ratio = sum(1 for a in recent if a.correct) / len(recent)
        sk.rolling_accuracy = round(ratio, 2)
    else:
        sk.rolling_accuracy = 1.0 if correct else 0.0

    if correct and rating != "too_hard":
        sk.streak = (sk.streak or 0) + 1
    else:
        sk.streak = 0

    # Level changes
    if rating == "too_hard":
        sk.level = max(1, sk.level - 1)
        sk.streak = 0
    elif rating == "easy" and sk.streak >= 2:
        sk.level = min(7, sk.level + 1)
    elif sk.streak >= 3 and sk.rolling_accuracy >= 0.8:
        sk.level = min(7, sk.level + 1)
        sk.streak = 0
    elif sk.rolling_accuracy < 0.4 and len(recent) >= 3:
        sk.level = max(1, sk.level - 1)

    sk.last_practiced = datetime.utcnow()
    return sk


def generate_template_problem(
    db: Session,
    *,
    strand_key: str | None = None,
    seed: int | None = None,
) -> dict | None:
    """Pick a template (optionally for a specific strand) and emit a problem."""
    stmt = select(GeneratedTemplate).join(Strand)
    if strand_key:
        stmt = stmt.where(Strand.key == strand_key)
    rows = db.execute(stmt).scalars().all()
    if not rows:
        return None
    rng = random.Random(seed)
    template_row = rng.choice(rows)
    return generate_from_template(template_row, seed=seed).to_dict()


def build_preview_session(
    db: Session,
    *,
    grade: str,
    seed: int = 42,
) -> list[dict]:
    """Build a deterministic, read-only preview session for the public /about page.

    Reads only from the curated bank (no generators, no DB writes, no skills).
    Same shape as a real session so the preview feels accurate.
    """
    rng = random.Random(seed + (hash(grade) % 1_000))
    target_level = _starting_level(grade)
    strand_ids = _strand_id_map(db)
    strand_lookup = {sid: key for key, sid in strand_ids.items()}

    def _pick(kinds: list[str], strand_keys: list[str], lvl: int) -> Problem | None:
        sids = [strand_ids[k] for k in strand_keys if k in strand_ids]
        if not sids:
            return None
        for radius in [0, 1, 2]:
            stmt = select(Problem).where(
                Problem.strand_id.in_(sids),
                Problem.kind.in_(kinds),
                Problem.level >= max(1, lvl - radius),
                Problem.level <= min(7, lvl + radius),
            )
            rows = db.execute(stmt).scalars().all()
            if rows:
                return rng.choice(rows)
        return None

    plan: list[dict] = []
    pos = 1

    def _emit(prob: Problem | None, kind: str) -> None:
        nonlocal pos
        if prob is None:
            return
        plan.append({
            "kind": kind,
            "problem_id": prob.id,
            "position": pos,
            "strand_key": strand_lookup.get(prob.strand_id, ""),
            "title": prob.title,
            "minutes": prob.minutes,
        })
        pos += 1

    # 3 warm-ups — number sense + add/sub
    for _ in range(3):
        _emit(
            _pick(["warm_up"], ["number_sense", "add_sub_structures", "patterns"], max(1, target_level - 1)),
            "warm_up",
        )
    # rich puzzle — pull from the more interesting strands
    _emit(
        _pick(
            ["rich_puzzle"],
            ["missing_number_stories", "logic_classification", "patterns", "combinatorics_counting", "equality_balance"],
            target_level,
        ),
        "rich_puzzle",
    )
    # visual / hands-on
    _emit(
        _pick(["visual"], ["geometry_spatial", "number_sense", "patterns"], target_level),
        "visual",
    )
    # story problem
    _emit(
        _pick(["story"], ["add_sub_structures", "missing_number_stories", "measurement"], target_level),
        "story",
    )
    return plan


def circle_night_plan(db: Session, children: list[Child]) -> list[dict]:
    """A shared plan for math-circle-night mode (cooperative, mixed levels)."""
    if not children:
        return []
    rng = random.Random()
    avg_level = max(1, round(sum(_avg_level(_ensure_skills(db, c), STRAND_KEYS) for c in children) / len(children)))
    plan: list[dict] = []
    pos = 1
    # 1) warm-up dice game
    games = (
        db.execute(select(Problem).where(Problem.kind == "game"))
        .scalars()
        .all()
    )
    if games:
        g = rng.choice(games)
        plan.append(_plan_item(g, "game", pos))
        pos += 1
    # 2) rich puzzle (logic / combinatorics — group reasoning)
    rich = (
        db.execute(
            select(Problem)
            .where(Problem.kind == "rich_puzzle")
            .where(Problem.level <= avg_level + 1)
        )
        .scalars()
        .all()
    )
    if rich:
        r = rng.choice(rich)
        plan.append(_plan_item(r, "rich_puzzle", pos))
        pos += 1
    # 3) visual / manipulative (geometry/symmetry — hands-on together)
    vis = (
        db.execute(
            select(Problem)
            .where(Problem.kind == "visual")
            .where(Problem.level <= avg_level + 1)
        )
        .scalars()
        .all()
    )
    if vis:
        v = rng.choice(vis)
        plan.append(_plan_item(v, "visual", pos))
        pos += 1
    # 4) story problem (everyone solves)
    stories = (
        db.execute(
            select(Problem)
            .where(Problem.kind == "story")
            .where(Problem.level <= avg_level + 1)
        )
        .scalars()
        .all()
    )
    if stories:
        s = rng.choice(stories)
        plan.append(_plan_item(s, "story", pos))
        pos += 1
    return plan

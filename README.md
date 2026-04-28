# Math Circle Home

A local-first web app that brings the Soviet/Russian/Chinese math-circle tradition to a kindergartner and a first-grader at home. Depth before acceleration. Strategies before answers. Conversation before quizzes.

> _"How do you know?"_ — the most important question in math.

## Why this exists

A Romanian high-school graduate at 18 has covered single-variable calculus with proofs, linear algebra, abstract algebra, complex numbers, combinatorics, probability and analytic geometry. A US student finishing AP Calculus BC has done single-variable calculus, no proofs, and that's it. Linear algebra, abstract algebra, and rigorous proof-based mathematics are entirely absent from US K–12 for nearly all students.

The gap doesn't open in 11th grade. It opens in kindergarten — when one tradition is teaching arithmetic drill while the other is teaching structure, decomposition, parity, invariance, systematic listing, and reasoning under constraints.

This app is one small tool to do that work at home, joyfully, 15–25 minutes a day.

## What's in the box

- **209+ hand-curated puzzles** across **10 strands**: number sense, addition/subtraction structures, mystery numbers, equality & balance, patterns, logic & sorting, geometry & space, measurement, counting ways, and math games.
- **Adaptive sessions**: a level-aware composer that builds a 15–25 minute session of warm-up + rich puzzle + visual + story + explain prompt + parent extension. Rotates strands across the week.
- **Progressive hints**: each problem ships 3 levels of scaffolding so you can dose help, not give it.
- **Strategy tracking**: the system records *how* a child solved something, not just whether.
- **Parent ratings**: easy / good struggle / too hard — drives the adaptive loop directly.
- **Math Circle Night mode**: a shared session for both kids together, mixed-level with games.
- **Parent guide**, **printable activity cards**, **JSON/CSV export**, **strand browser**, **puzzle bank**, **parent notes journal**.

## Quick start

```bash
# 1. Create a virtualenv and install
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. (Re-)build the seed bank (already checked in, but to regenerate)
.venv/bin/python data/build_seed.py

# 3. Run
.venv/bin/uvicorn app.main:app --reload
# → open http://127.0.0.1:8000
```

The first run creates `data/mathcircle.db`, seeds 209 problems and 10 strands, and creates two starter children (Wren — K, Hazel — Grade 1) you can rename or delete. Subsequent runs are fully local — no network, no telemetry.

## Tests

```bash
.venv/bin/pytest
```

22 tests cover the parametric problem generator and a full HTTP flow (start session → record attempts → complete → mastery → export → circle).

## Project layout

```
app/
  main.py                   FastAPI app, lifespan seeds the DB on first run
  config.py                 paths + session shape + strand keys
  database.py               SQLAlchemy engine, Base, get_db
  models.py                 ORM: Child / Strand / Problem / Session / Attempt / Skill / Note / GeneratedTemplate
  schemas.py                Pydantic I/O
  seed.py                   Idempotent DB seeder from JSON
  problem_generator.py      10 parametric variant generators
  session_generator.py      Adaptive composer + skill update + circle-mode plan
  routes/
    web.py                  HTML pages
    api.py                  JSON API + JSON/CSV export
  templates/                Jinja2 (warm, parent-friendly UI)
  static/
    css/app.css             single hand-tuned stylesheet
    js/session.js           hint reveal, answer check, parent rating, attempt POST
data/
  build_seed.py             produces seed_problems.json (run once after edits)
  seed_problems.json        canonical seed bank
tests/
  test_problem_generator.py
  test_session_flow.py
```

## Architecture notes

- **SQLite + SQLAlchemy 2.x** — local-first by design. Promotion path to Postgres is one connection-string change; no schema port needed.
- **JSON columns** for hints/strategies/tags/plan — keep the relational core small, let pedagogy data flex.
- **Lifespan-seeded** — the DB self-bootstraps on app start; nothing to install or configure.
- **Skills as derived state** — every attempt updates a per-strand `Skill` row (rolling accuracy, streak, level). Adaptation lives in one function (`update_skill_from_attempt`) so it's easy to tune.
- **Templates persisted, generators pure** — the parametric generators are pure functions seeded by an int, so any "generated" problem is reproducible from its slug. Useful for printable cards and tests.
- **No build step** — vanilla HTML/CSS/JS. The whole UI is server-rendered Jinja with one ~150-line JS file for interactivity.

### Promoting to the cloud

The app is intentionally cheap to host: a single Python container with a 200KB SQLite DB. To go multi-user:

1. Switch `MATHCIRCLE_DATABASE_URL` to Postgres; SQLAlchemy stays the same.
2. Add an auth layer in front (today there's none — it's a single household). The `Child` model is the natural tenant key; add a `User` parent for membership.
3. Move `data/seed_problems.json` to S3/GCS; the seeder reads it on boot.
4. Cache rendered pages with a CDN — pages are mostly read-mostly per child.
5. Offline mode: the app already runs fully offline once seeded. Wrapping it in Tauri/PWA is a small step.

## Pedagogy at a glance

- **Strands rotate** across the week — no child sits in arithmetic drills for 5 days running.
- **Levels 1–5** map roughly to PK / late-K / G1 / late-G1 / G2 enrichment. The system bumps up after 3 strong attempts; steps back on "too hard"; holds on "good struggle".
- **Every problem has an explain prompt** — the most reliably underused tool in early math.
- **Manipulatives are first-class** — a long `materials` list (counters, ten-frames, dominoes, tangram, paper) per applicable problem.
- **Parent extensions** map screen activities to kitchen-table follow-ups so the math leaves the device.

See `/parent/guide` (in-app) for the longer parent-facing primer.

## Roadmap (open ideas)

- More problem-generator templates (path-counting on grids, trade equivalent coins, more balance-scale puzzles).
- A "weekly progress" digest email for parents.
- Support for **drawn answers** (HTML5 canvas) — kids should be able to *show* with a picture, not just type.
- A "make your own puzzle" creator for older kids.
- Voice-only mode for the warm-up phase.

## License & attribution

Built for one specific household (a parent and two K–1 children) but written portably. Feel free to fork, rename, and adapt.

The math-circle tradition this app draws from is built on the work of Alexander Zvonkin (_Math from Three to Seven_), Boris Kordemsky (_The Moscow Puzzles_), and the broader Soviet/Russian school. The pedagogical framing is influenced by Tracy Zager, Jo Boaler, James Tanton, and Phil Daro.

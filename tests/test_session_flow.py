"""End-to-end smoke through the API: child → session → attempt → mastery → export."""
from __future__ import annotations


def test_home_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Math Circle Home" in r.text


def test_seed_populated(client):
    r = client.get("/api/strands")
    assert r.status_code == 200
    strands = r.json()
    assert len(strands) == 10
    keys = {s["key"] for s in strands}
    assert "number_sense" in keys
    assert "math_games" in keys

    r = client.get("/api/problems?limit=500")
    assert r.status_code == 200
    problems = r.json()
    assert len(problems) >= 200


def test_default_children_seeded(client):
    r = client.get("/api/children")
    assert r.status_code == 200
    kids = r.json()
    assert len(kids) >= 2
    names = {k["name"] for k in kids}
    assert {"Danica", "Mila"}.issubset(names)


def test_full_session_flow(client):
    # pick first child
    kids = client.get("/api/children").json()
    cid = kids[0]["id"]

    # start a session
    r = client.post(f"/api/children/{cid}/sessions")
    assert r.status_code == 201, r.text
    s = r.json()
    sid = s["id"]
    assert s["plan"], "session plan empty"
    # plan must include warm_up, rich_puzzle, story (visual sometimes optional)
    kinds = {item["kind"] for item in s["plan"]}
    assert "warm_up" in kinds
    assert "rich_puzzle" in kinds
    assert "story" in kinds

    # record an attempt for each problem
    for item in s["plan"]:
        if item["kind"] == "explain":
            continue
        r = client.post(
            f"/api/children/{cid}/attempts",
            json={
                "problem_id": item["problem_id"],
                "session_id": sid,
                "answer_given": "6",
                "correct": True,
                "hint_count": 0,
                "parent_rating": "good_struggle",
                "strategy_note": "counted up",
                "time_seconds": 30,
            },
        )
        assert r.status_code == 201, r.text

    # complete the session
    r = client.post(f"/api/sessions/{sid}/complete", json={"summary": "great session"})
    assert r.status_code == 200

    # mastery should reflect activity
    r = client.get(f"/api/children/{cid}/skills")
    assert r.status_code == 200
    skills = r.json()
    assert any(s["last_practiced"] is not None for s in skills)

    # export JSON
    r = client.get(f"/api/children/{cid}/export.json")
    assert r.status_code == 200
    payload = r.json()
    assert payload["child"]["id"] == cid
    assert payload["attempts"], "expected attempts in export"

    # export CSV
    r = client.get(f"/api/children/{cid}/export.csv")
    assert r.status_code == 200
    assert "created_at" in r.text


def test_circle_session(client):
    kids = client.get("/api/children").json()
    ids = [k["id"] for k in kids]
    r = client.post("/api/circle/sessions", json=ids)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["mode"] == "circle"
    assert s["plan"]


def test_child_dashboard_renders(client):
    kids = client.get("/api/children").json()
    cid = kids[0]["id"]
    r = client.get(f"/child/{cid}")
    assert r.status_code == 200
    assert kids[0]["name"] in r.text


def test_strand_pages_render(client):
    r = client.get("/strands")
    assert r.status_code == 200
    assert "Number Sense" in r.text
    r = client.get("/strands/number_sense")
    assert r.status_code == 200


def test_puzzle_search(client):
    r = client.get("/puzzles?q=secret")
    assert r.status_code == 200
    assert "secret" in r.text.lower()


def test_parent_guide(client):
    r = client.get("/parent/guide")
    assert r.status_code == 200
    assert "How do you know" in r.text


def test_notes_create_and_delete(client):
    kids = client.get("/api/children").json()
    cid = kids[0]["id"]
    r = client.post(f"/api/children/{cid}/notes", json={"kind": "win", "body": "Solved it her own way!"})
    assert r.status_code == 201
    nid = r.json()["id"]
    r = client.get(f"/api/children/{cid}/notes")
    assert any(n["id"] == nid for n in r.json())
    r = client.delete(f"/api/notes/{nid}")
    assert r.status_code == 204


def test_generated_problem(client):
    r = client.get("/api/problems/generated/new?seed=1")
    assert r.status_code == 200
    body = r.json()
    assert body["prompt"]
    assert body["answer"]

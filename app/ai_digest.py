"""AI-powered daily digest of a child's math practice via Amazon Bedrock.

Uses **Claude Haiku 4.5** through Bedrock's cross-region inference profile.
Designed for tiny, focused summaries — not deep reasoning. Runs on the
EC2 instance role; no API keys.

Privacy & safety
----------------
- Child names are anonymized to "Child" in the prompt so the model never
  sees PII. The render-side restores the actual name.
- Strategy notes and parent ratings are sent verbatim — these can contain
  free-text the parent typed. Parents must opt in (Child.ai_digests_enabled)
  before any data is sent.
- We send only the LAST 24 HOURS of activity by default for daily digests.
- Each digest stores the full raw response + token counts + cost so you can
  audit every call.
- Bedrock's standard contract: prompts/completions don't train models and
  don't leave the AWS region they're invoked in.

Cost (Claude Haiku 4.5, us-east-1, prompt-caching-eligible):
    $0.80 per million input tokens
    $4.00 per million output tokens
A typical daily digest is ~1,500 input tokens + ~250 output tokens
≈ $0.0022 per digest. For 2 kids × 365 days = ~$1.60/year.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attempt, Child, Digest, Note, Problem, Strand

log = logging.getLogger("mathcircle.ai_digest")

# Cross-region inference profile is required (model isn't on-demand on its own).
MODEL_ID = os.getenv(
    "MATHCIRCLE_BEDROCK_MODEL_ID",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)
REGION = os.getenv("MATHCIRCLE_BEDROCK_REGION", "us-east-1")

# Pricing (USD per million tokens). Update if AWS changes the rate card.
INPUT_PRICE_PER_M = 0.80
OUTPUT_PRICE_PER_M = 4.00


@dataclass
class DigestResult:
    summary: dict
    raw: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    error: str | None = None


class BedrockUnavailable(RuntimeError):
    """Raised when Bedrock client init or invocation fails."""


def _get_client():
    """Return a boto3 bedrock-runtime client. Lazy import so the rest of the app
    doesn't pull boto3 unless the digest feature is actually used."""
    try:
        import boto3  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise BedrockUnavailable("boto3 not installed") from e
    return boto3.client("bedrock-runtime", region_name=REGION)


def _gather_window(
    db: Session, child: Child, *, hours: int
) -> dict[str, Any]:
    """Pull the activity window we'll feed the model."""
    since = datetime.utcnow() - timedelta(hours=hours)

    attempts = (
        db.execute(
            select(Attempt)
            .where(Attempt.child_id == child.id)
            .where(Attempt.created_at >= since)
            .order_by(Attempt.created_at)
        )
        .scalars()
        .all()
    )

    notes = (
        db.execute(
            select(Note)
            .where(Note.child_id == child.id)
            .where(Note.created_at >= since)
            .order_by(Note.created_at)
        )
        .scalars()
        .all()
    )

    rows: list[dict] = []
    for a in attempts:
        prob = a.problem
        rows.append({
            "when": a.created_at.isoformat(timespec="minutes"),
            "strand": prob.strand.key if prob and prob.strand else "",
            "kind": prob.kind if prob else "",
            "title": prob.title if prob else "",
            "level": prob.level if prob else None,
            "expected_strategies": prob.strategies if prob else [],
            "answer_given": (a.answer_given or "")[:200],
            "correct": a.correct,
            "hint_count": a.hint_count,
            "parent_rating": a.parent_rating,
            "strategy_note": (a.strategy_note or "")[:300],
            "time_seconds": a.time_seconds,
        })

    return {
        "grade": child.grade,
        "since": since.isoformat(timespec="minutes"),
        "now": datetime.utcnow().isoformat(timespec="minutes"),
        "attempts": rows,
        "parent_notes": [
            {
                "when": n.created_at.isoformat(timespec="minutes"),
                "kind": n.kind,
                "body": (n.body or "")[:500],
            }
            for n in notes
        ],
    }


def _build_messages(window: dict, *, anonymized_name: str = "Child") -> list[dict]:
    """Compose the Bedrock messages payload."""
    system = (
        "You are an experienced K-2 math educator with deep familiarity with the "
        "Soviet/Russian math-circle tradition. You write short, parent-facing "
        "digests of a single child's math practice. You focus on STRATEGIES, "
        "REASONING SHIFTS, and PRODUCTIVE STRUGGLE — never on speed, accuracy, "
        "or comparative ranking. You are warm, specific, and honest. Avoid "
        "praise inflation. If the data is thin, say so directly. "
        "Output strictly valid JSON matching the schema the user describes."
    )
    user = f"""Below is the recent math practice for {anonymized_name} (grade {window['grade']}).

Time window: {window['since']} → {window['now']} UTC.

Activity (newest last):
{json.dumps(window['attempts'], indent=2)}

Parent notes recorded in this window:
{json.dumps(window['parent_notes'], indent=2)}

Produce a JSON object with EXACTLY these keys:

{{
  "headline": "<one short sentence — what's the most interesting thing about today>",
  "what_we_noticed": [
    "<2-4 bullets about strategies, reasoning shifts, productive struggle>",
    "<be specific — quote strategy notes when useful>"
  ],
  "strand_notes": {{
    "<strand_key>": "<one sentence per active strand>"
  }},
  "try_next": [
    "<1-3 concrete suggestions for tomorrow's session or kitchen-table follow-up>"
  ],
  "celebrate": "<one specific thing worth telling {anonymized_name} they did well>",
  "watch": "<one specific thing the parent might pay attention to next week>"
}}

Rules:
- Refer to the child as "{anonymized_name}" throughout.
- If the window has fewer than 3 attempts, return a digest that says so honestly in `headline` and keeps other fields empty or with one-item placeholder text.
- NEVER invent attempts, strategies, or notes. Ground every claim in the data above.
- Strands available: number_sense, add_sub_structures, missing_number_stories, equality_balance, patterns, logic_classification, geometry_spatial, measurement, combinatorics_counting, math_games. Only mention strands that appear in the data.
- Output ONLY the JSON. No prose around it.
"""
    return [
        {"role": "user", "content": [{"type": "text", "text": user}]},
    ], system


def generate_digest(
    db: Session,
    child: Child,
    *,
    hours: int = 24,
    period_label: str = "daily",
) -> DigestResult:
    """Call Bedrock and return a structured digest. Persists nothing — the
    caller decides whether to save."""
    if not child.ai_digests_enabled:
        raise PermissionError(
            f"AI digests not enabled for child {child.id} ({child.name})"
        )

    window = _gather_window(db, child, hours=hours)
    if len(window["attempts"]) == 0:
        # No activity in window — return a stub without calling Bedrock.
        return DigestResult(
            summary={
                "headline": "No practice in this window yet.",
                "what_we_noticed": [],
                "strand_notes": {},
                "try_next": ["Start a session today to seed the next digest."],
                "celebrate": "",
                "watch": "",
            },
            raw="(no-call: empty window)",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )

    messages, system = _build_messages(window)

    client = _get_client()
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 700,
        "system": system,
        "messages": messages,
        "temperature": 0.4,
    }

    log.info("bedrock invoke child=%s window-attempts=%s", child.id, len(window["attempts"]))
    try:
        resp = client.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
    except Exception as e:
        log.exception("bedrock invoke failed")
        return DigestResult(
            summary={"headline": "Could not reach the AI service today.", "what_we_noticed": [], "strand_notes": {}, "try_next": [], "celebrate": "", "watch": ""},
            raw=str(e),
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            error=str(e),
        )

    payload = json.loads(resp["body"].read())
    usage = payload.get("usage", {})
    in_toks = int(usage.get("input_tokens", 0))
    out_toks = int(usage.get("output_tokens", 0))
    cost = (in_toks * INPUT_PRICE_PER_M + out_toks * OUTPUT_PRICE_PER_M) / 1_000_000

    text = ""
    for block in payload.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")

    summary: dict
    err: str | None = None
    try:
        # Sometimes models add fences; strip them defensively.
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        summary = json.loads(cleaned)
    except Exception as e:
        summary = {
            "headline": "Could not parse model output.",
            "what_we_noticed": [],
            "strand_notes": {},
            "try_next": [],
            "celebrate": "",
            "watch": text[:500],
        }
        err = f"parse-error: {e}"

    return DigestResult(
        summary=summary,
        raw=text,
        input_tokens=in_toks,
        output_tokens=out_toks,
        cost_usd=cost,
        error=err,
    )


def generate_and_persist(
    db: Session,
    child: Child,
    *,
    hours: int = 24,
    period_label: str = "daily",
) -> Digest:
    """Generate a digest and persist it to the digests table."""
    result = generate_digest(db, child, hours=hours, period_label=period_label)
    end = datetime.utcnow()
    start = end - timedelta(hours=hours)
    row = Digest(
        child_id=child.id,
        period_start=start,
        period_end=end,
        period_label=period_label,
        summary=result.summary,
        raw=result.raw,
        model_id=MODEL_ID,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        error=result.error,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

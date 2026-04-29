"""Canonical materials taxonomy + normalization for session prep.

Why this exists
---------------
The curated bank's `materials` field is hand-authored and slightly inconsistent
("counters" vs "red and blue counters" vs "20 counters"). For the parent
materials checklist we want a small, clean list of ~15-20 categories with
de-duplicated counts and helpful suggested-swaps.

This module:
  - Defines the canonical materials list (`CANONICAL`)
  - Maps raw seed-bank strings to canonical names (`normalize`)
  - Provides suggested-swap text for each canonical category
  - Quietly drops "always-available" items (fingers, paper, pencil) from the
    checklist UI — parents shouldn't have to confirm they own a pencil
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Material:
    key: str          # canonical key (used in storage / filtering)
    label: str        # human-friendly label for the checklist
    swap: str         # what to use if you don't have it
    always_have: bool = False  # if True, skipped from the UI checklist


# The canonical set, ordered roughly by likelihood of having at home.
CANONICAL: list[Material] = [
    Material("fingers", "Fingers", "", always_have=True),
    Material("paper", "Paper / scratch space", "", always_have=True),
    Material("pencil", "Pencil", "", always_have=True),
    Material("scissors", "Kid-safe scissors", "Tearing paper works for most cuts", always_have=True),

    Material("counters", "Counters / small objects (~20+)",
             "Cereal pieces, paper clips, pennies, dried beans — anything small and countable"),
    Material("crayons", "Crayons or markers (a few colors)",
             "Any pens or pencils that come in colors"),
    Material("dice", "Standard 6-sided dice (1 or 2)",
             "An app on your phone, or write 1–6 on six paper slips and pull from a hat"),
    Material("playing_cards", "Deck of playing cards",
             "Index cards numbered 1–10 with face cards as 11–13"),
    Material("dominoes", "Set of dominoes",
             "Two dice rolled together produce the same numbers; cards work too"),
    Material("coins", "A handful of coins",
             "Cut paper circles labeled 1¢, 5¢, 10¢, 25¢"),

    Material("ten_frame", "Ten-frame (printable)",
             "Draw 2 rows of 5 squares on paper — takes 30 seconds"),
    Material("hundred_chart", "Hundred chart (printable)",
             "Sketch a 10×10 grid with numbers 1–100"),
    Material("number_line", "Number line (printable)",
             "Draw a long line and mark evenly-spaced numbers"),
    Material("dot_card", "Dot card (for subitizing)",
             "Sketch dots on an index card"),
    Material("graph_paper", "Graph paper",
             "Print free graph paper or use lined paper turned 90°"),

    Material("base10_blocks", "Base-10 blocks",
             "Stack 10 pennies for a 'ten'; single pennies for ones — works perfectly"),
    Material("square_tiles", "Square tiles or unit cubes",
             "LEGO bricks work great. Or 1-inch squares cut from index cards"),
    Material("tangram", "Tangram set",
             "Print and cut a paper tangram; takes 5 min one time and lasts forever"),

    Material("balance", "Balance scale",
             "Pretend-balance: use a coat hanger with two cups, or just imagine it on paper"),
    Material("clock", "Analog clock",
             "Draw a clock face on paper — kids actually learn better when they draw it themselves"),
    Material("hole_punch", "Hole punch",
             "Scissors with a small snip works for paper-folding puzzles"),
]

# index by key for fast lookup
_BY_KEY = {m.key: m for m in CANONICAL}


# Map raw strings (lowercased) to canonical keys.
# Anything not in this map is silently treated as "always have" so we don't
# blow up on unexpected materials in the bank.
_RAW_TO_CANONICAL: dict[str, str] = {
    # always-haves
    "fingers": "fingers",
    "hands": "fingers",
    "paper": "paper",
    "pencil": "pencil",
    "pencils": "pencil",
    "scissors": "scissors",
    "marker": "pencil",
    "paper for tree": "paper",
    "paper for total": "paper",

    # counters
    "counters": "counters",
    "red and blue counters": "counters",
    "marbles": "counters",
    "buttons": "counters",
    "shapes": "counters",
    "cookies": "counters",
    "socks": "counters",
    "shoes": "counters",
    "21 stones / pennies": "counters",
    "tokens 1-9": "counters",
    "jar, items": "counters",
    "counters / cookies": "counters",
    "counters, cookies": "counters",

    # crayons
    "crayons": "crayons",
    "hundred chart, crayons": "crayons",  # rare combo

    # dice
    "die": "dice",
    "2 dice": "dice",
    "dice": "dice",

    # cards
    "deck of cards": "playing_cards",
    "playing cards": "playing_cards",

    # dominoes
    "dominoes": "dominoes",

    # coins
    "coin": "coins",
    "coins": "coins",

    # printables
    "ten-frame": "ten_frame",
    "ten-frame, counters": "ten_frame",
    "hundred chart": "hundred_chart",
    "number line": "number_line",
    "dot card": "dot_card",
    "dot paper": "graph_paper",
    "graph paper": "graph_paper",

    # blocks
    "base-10 blocks": "base10_blocks",
    "blocks": "square_tiles",
    "square tiles": "square_tiles",
    "triangle tiles": "square_tiles",
    "unit cubes / lego": "square_tiles",
    "balance, cubes": "square_tiles",  # we'll also add balance separately below
    "rekenrek or paper": "ten_frame",

    # specialty
    "tangram": "tangram",
    "balance": "balance",
    "balance scale": "balance",
    "balance, blocks": "balance",
    "balance, marbles": "balance",
    "analog clock": "clock",
    "hole punch": "hole_punch",
    "paper, scissors": "paper",
    "paper, hole punch": "hole_punch",

    # ambient (treat as always-have)
    "a box / cube": "paper",
    "book": "paper",
    "jugs/cups": "counters",
    "pencil, pencil": "pencil",
}


def normalize_one(raw: str) -> str | None:
    """Turn one raw material string into a canonical key, or None if unknown.

    Handles compound strings like 'balance, marbles' by mapping to the most
    specific canonical key listed.
    """
    if raw is None:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    # exact-match first
    if key in _RAW_TO_CANONICAL:
        return _RAW_TO_CANONICAL[key]
    # heuristic: try prefix match against known forms
    for src, dst in _RAW_TO_CANONICAL.items():
        if key.startswith(src) or src in key:
            return dst
    return None


def normalize(materials: list[str]) -> set[str]:
    """Normalize a problem's raw materials list into a set of canonical keys.

    Always-have materials are dropped — we don't ask parents to confirm they
    own a pencil. The remaining set is what the checklist UI actually shows
    (and what the composer filter operates on).
    """
    result: set[str] = set()
    for raw in materials or []:
        key = normalize_one(raw)
        if key is None:
            continue
        m = _BY_KEY.get(key)
        if m is None:
            continue
        if m.always_have:
            continue
        result.add(key)
    return result


def by_key(key: str) -> Material | None:
    return _BY_KEY.get(key)


def collect_for_plan(plan_problems: list) -> dict[str, dict]:
    """For a list of Problem ORM rows, return {canonical_key: {material, count, problems}}.

    `count` reflects how many problems in the plan call for this material.
    `problems` is the list of problem titles that need it (for parent context).
    """
    bucket: dict[str, dict] = {}
    for prob in plan_problems:
        keys = normalize(getattr(prob, "materials", None) or [])
        for k in keys:
            if k not in bucket:
                bucket[k] = {"material": _BY_KEY[k], "count": 0, "problem_titles": []}
            bucket[k]["count"] += 1
            bucket[k]["problem_titles"].append(prob.title)
    # Stable order matching the canonical list
    ordered: dict[str, dict] = {}
    for m in CANONICAL:
        if m.key in bucket:
            ordered[m.key] = bucket[m.key]
    return ordered

"""Generate parametric problem variants from templates.

Each template is a small dict with a `type` and `params`. The generator turns
it into a runtime problem (same shape as a seeded Problem dict) without
touching the database.

Templates supported:
- secret_number_add / secret_number_sub
- missing_addend
- ways_to_make_n
- balance_blank
- ab_pattern, aab_pattern
- function_machine
- ten_frame_show
- two_dice_sum

Determinism: a `seed` argument lets callers regenerate identical variants
(useful for printable cards and tests).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class GeneratedProblem:
    slug: str
    title: str
    prompt: str
    answer: str
    answer_type: str
    hints: list[str]
    strategies: list[str]
    materials: list[str]
    tags: list[str]
    explain_prompt: str
    parent_extension: str
    minutes: int
    kind: str
    level: int
    strand: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _rng(seed: int | None) -> random.Random:
    return random.Random(seed) if seed is not None else random.Random()


# ---------- per-type generators ----------
def _gen_secret_number_add(p: dict, rng: random.Random) -> dict:
    add = rng.randint(p["params"].get("add_min", 1), p["params"].get("add_max", 9))
    secret = rng.randint(1, p["params"].get("result_max", 18) - add)
    result = secret + add
    return {
        "title": f"Secret number (+{add} = {result})",
        "prompt": f"I'm thinking of a secret number. If I add {add}, I get {result}. What's my number?",
        "answer": str(secret),
        "answer_type": "number",
        "hints": [
            f"Work backwards: {result} minus {add}.",
            f"Or count up from {add} to {result}.",
            f"{secret} + {add} = {result} ✓",
        ],
        "strategies": ["work backwards", "missing addend"],
        "materials": [],
        "tags": ["mystery", "generated"],
        "explain_prompt": "How do you 'undo' adding?",
        "parent_extension": "Try a new secret number with your child.",
        "minutes": 3,
    }


def _gen_secret_number_sub(p: dict, rng: random.Random) -> dict:
    sub = rng.randint(p["params"].get("sub_min", 1), p["params"].get("sub_max", 9))
    result = rng.randint(p["params"].get("result_min", 1), p["params"].get("result_max", 9))
    secret = result + sub
    return {
        "title": f"Secret number (−{sub} = {result})",
        "prompt": f"A secret number minus {sub} is {result}. What is the secret number?",
        "answer": str(secret),
        "answer_type": "number",
        "hints": [
            f"Undo subtract by adding: {result} + {sub}.",
            "Use a number line.",
            f"{secret} − {sub} = {result} ✓",
        ],
        "strategies": ["work backwards"],
        "materials": [],
        "tags": ["mystery", "generated"],
        "explain_prompt": "Why does adding undo subtracting?",
        "parent_extension": "",
        "minutes": 3,
    }


def _gen_missing_addend(p: dict, rng: random.Random) -> dict:
    start = rng.randint(p["params"].get("start_min", 3), p["params"].get("start_max", 12))
    end = rng.randint(max(start + 1, p["params"].get("end_min", 8)), p["params"].get("end_max", 20))
    diff = end - start
    return {
        "title": f"Missing addend {start}→{end}",
        "prompt": f"There were {start} kids at the park. Some more came and now there are {end}. How many more?",
        "answer": str(diff),
        "answer_type": "number",
        "hints": [f"{start} + ? = {end}.", "Count up.", f"{end} − {start} = {diff}."],
        "strategies": ["count up", "missing addend"],
        "materials": [],
        "tags": ["missing-addend", "generated"],
        "explain_prompt": "What does 'how many more' tell you to do?",
        "parent_extension": "",
        "minutes": 3,
    }


def _gen_ways_to_make_n(p: dict, rng: random.Random) -> dict:
    n = rng.randint(p["params"].get("n_min", 6), p["params"].get("n_max", 14))
    pairs = [(a, n - a) for a in range(0, n // 2 + 1)]
    answer = ",".join(f"{a}+{b}" for a, b in pairs)
    return {
        "title": f"Make {n}",
        "prompt": f"How many ways can you make {n} using two whole numbers (zero allowed)? Treat 3+{n-3} the same as {n-3}+3. List them all.",
        "answer": answer,
        "answer_type": "set",
        "hints": [
            f"Start with 0+{n}.",
            "March up: 1+...; 2+...",
            f"Stop at {n//2}+{n - n//2}.",
        ],
        "strategies": ["systematic list"],
        "materials": ["counters"],
        "tags": ["decompose", "generated"],
        "explain_prompt": "Why can you stop halfway?",
        "parent_extension": "Try with a different number tomorrow.",
        "minutes": 5,
    }


def _gen_balance_blank(p: dict, rng: random.Random) -> dict:
    a = rng.randint(2, 9)
    b = rng.randint(2, 9)
    target = a + b  # left side
    c = rng.randint(1, min(target - 1, 9))
    blank = target - c
    return {
        "title": f"Both sides equal: {a} + {b} = __ + {c}",
        "prompt": f"What number makes this true? {a} + {b} = __ + {c}. Don't 'do' the left first — think about what makes both sides match.",
        "answer": str(blank),
        "answer_type": "number",
        "hints": [
            f"Left side = {target}.",
            f"What plus {c} = {target}?",
            f"{blank} + {c} = {target} ✓",
        ],
        "strategies": ["both sides equal", "missing addend"],
        "materials": [],
        "tags": ["equality", "generated"],
        "explain_prompt": "What does the = sign really mean?",
        "parent_extension": "",
        "minutes": 4,
    }


def _gen_ab_pattern(p: dict, rng: random.Random) -> dict:
    pair = rng.choice(p["params"]["shapes"])
    a, b = pair[0], pair[1]
    seq = (f"{a} {b} " * 3).strip() + " ___ ___ ___"
    return {
        "title": "What comes next? (AB)",
        "prompt": f"{seq}",
        "answer": f"{a} {b} {a}",
        "answer_type": "text",
        "hints": ["Find the unit that repeats.", f"Unit: {a} {b}.", "Then continue."],
        "strategies": ["unit-of-repeat"],
        "materials": [],
        "tags": ["pattern", "AB", "generated"],
        "explain_prompt": "What makes a pattern a pattern?",
        "parent_extension": "Make your own AB pattern with toys.",
        "minutes": 2,
    }


def _gen_aab_pattern(p: dict, rng: random.Random) -> dict:
    pair = rng.choice(p["params"]["shapes"])
    a, b = pair[0], pair[1]
    seq = (f"{a} {a} {b} " * 2).strip() + f" {a} ___ ___"
    return {
        "title": "What comes next? (AAB)",
        "prompt": f"{seq}",
        "answer": f"{a} {b}",
        "answer_type": "text",
        "hints": ["Find the unit that repeats.", f"Unit: {a} {a} {b}.", "Then continue."],
        "strategies": ["unit-of-repeat"],
        "materials": [],
        "tags": ["pattern", "AAB", "generated"],
        "explain_prompt": "How long is the unit?",
        "parent_extension": "",
        "minutes": 2,
    }


_OPS: dict[str, Callable[[int], int]] = {
    "+1": lambda x: x + 1,
    "+2": lambda x: x + 2,
    "+3": lambda x: x + 3,
    "+5": lambda x: x + 5,
    "+10": lambda x: x + 10,
    "double": lambda x: x * 2,
}


def _gen_function_machine(p: dict, rng: random.Random) -> dict:
    op_name = rng.choice(p["params"]["ops"])
    fn = _OPS[op_name]
    inputs = sorted(rng.sample(range(1, 12), 3))
    pairs = ", ".join(f"{x}→{fn(x)}" for x in inputs)
    test = max(inputs) + 2
    return {
        "title": "What does the machine do?",
        "prompt": f"Inputs and outputs: {pairs}. What's the rule? If {test} goes in, what comes out?",
        "answer": f"rule: {op_name}; out: {fn(test)}",
        "answer_type": "text",
        "hints": ["Compare each in→out pair.", f"All examples follow {op_name}.", "Apply the rule."],
        "strategies": ["look at pairs", "find rule"],
        "materials": [],
        "tags": ["function", "generated"],
        "explain_prompt": "Could two different rules fit?",
        "parent_extension": "Make up a machine and quiz your child.",
        "minutes": 4,
    }


def _gen_ten_frame_show(p: dict, rng: random.Random) -> dict:
    n = rng.randint(p["params"].get("n_min", 4), p["params"].get("n_max", 10))
    return {
        "title": f"Ten-frame for {n}",
        "prompt": f"Fill a ten-frame to show {n}. How many empty squares? How many to make 10?",
        "answer": str(10 - n),
        "answer_type": "number",
        "hints": [
            "Ten-frame has 10 squares.",
            f"Show {n}; empties = {10 - n}.",
            f"{n} + {10 - n} = 10.",
        ],
        "strategies": ["ten-frame", "complements"],
        "materials": ["ten-frame", "counters"],
        "tags": ["ten-frame", "generated"],
        "explain_prompt": "How does the ten-frame show the partner to 10?",
        "parent_extension": "",
        "minutes": 3,
    }


def _gen_two_dice_sum(p: dict, rng: random.Random) -> dict:
    a, b = rng.randint(1, 6), rng.randint(1, 6)
    return {
        "title": "Two dice sum",
        "prompt": f"Roll showed {a} and {b}. What's the sum? Then: subtract smaller from larger. What do you get?",
        "answer": f"{a + b}; {abs(a - b)}",
        "answer_type": "multi",
        "hints": [
            "Add the two numbers.",
            "Subtract smaller from larger.",
            f"{a + b} and {abs(a - b)}.",
        ],
        "strategies": ["count on", "compare"],
        "materials": ["2 dice"],
        "tags": ["dice", "generated"],
        "explain_prompt": "When can the difference be 0?",
        "parent_extension": "Roll 5 times — track sums and differences.",
        "minutes": 3,
    }


_GENERATORS: dict[str, Callable[[dict, random.Random], dict]] = {
    "secret_number_add": _gen_secret_number_add,
    "secret_number_sub": _gen_secret_number_sub,
    "missing_addend": _gen_missing_addend,
    "ways_to_make_n": _gen_ways_to_make_n,
    "balance_blank": _gen_balance_blank,
    "ab_pattern": _gen_ab_pattern,
    "aab_pattern": _gen_aab_pattern,
    "function_machine": _gen_function_machine,
    "ten_frame_show": _gen_ten_frame_show,
    "two_dice_sum": _gen_two_dice_sum,
}


def generate_from_template(
    template_row: Any,
    *,
    seed: int | None = None,
) -> GeneratedProblem:
    """Produce a fresh problem from a GeneratedTemplate row.

    template_row may be an ORM GeneratedTemplate instance OR a dict shaped like
    {"strand": "key", "level": int, "kind": str, "template": {"type":..,"params":..}}.
    """
    if hasattr(template_row, "template"):
        t = template_row.template
        strand_key = template_row.strand.key
        level = template_row.level
        kind = template_row.kind
        name = template_row.name
    else:
        t = template_row["template"]
        strand_key = template_row["strand"]
        level = template_row.get("level", 1)
        kind = template_row.get("kind", "rich_puzzle")
        name = template_row.get("name", t["type"])

    fn = _GENERATORS.get(t["type"])
    if fn is None:
        raise ValueError(f"unknown template type: {t['type']}")

    rng = _rng(seed)
    payload = fn(t, rng)
    sid = seed if seed is not None else rng.randint(0, 1_000_000)
    slug = f"gen-{name}-{sid}"

    return GeneratedProblem(
        slug=slug,
        kind=kind,
        level=level,
        strand=strand_key,
        **payload,
    )

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


# ---------- additional generators ----------
def _gen_coin_change(p: dict, rng: random.Random) -> dict:
    target = rng.randint(p["params"].get("min", 10), p["params"].get("max", 50))
    return {
        "title": f"Make {target}¢ — many ways",
        "prompt": f"How many different ways can you make {target}¢ using pennies (1), nickels (5), dimes (10), and quarters (25)? Find at least three.",
        "answer": "many; depends on coins available",
        "answer_type": "open",
        "hints": [
            "Start with all pennies.",
            "Now swap 5 pennies for a nickel.",
            "Try with dimes / a quarter if it fits.",
        ],
        "strategies": ["systematic list", "exchange equivalents"],
        "materials": ["coins"],
        "tags": ["money", "decompose", "generated"],
        "explain_prompt": "How does each new combo relate to the last?",
        "parent_extension": "Pour real coins on the table. Build the same amount three ways.",
        "minutes": 6,
    }


def _gen_balance_multi(p: dict, rng: random.Random) -> dict:
    coeff = rng.choice([2, 3])
    addend = rng.randint(1, 8)
    box = rng.randint(2, 9)
    total = coeff * box + addend
    return {
        "title": f"{coeff} boxes + {addend} = {total}",
        "prompt": f"A balance shows {coeff} equal boxes plus {addend} marbles balancing {total} marbles. How many marbles in each box?",
        "answer": str(box),
        "answer_type": "number",
        "hints": [
            f"Take {addend} marbles off both sides.",
            f"Now {coeff} boxes balance {total - addend} marbles.",
            f"Each box = {box}.",
        ],
        "strategies": ["balance model", "halve / share"],
        "materials": ["balance scale", "marbles"],
        "tags": ["balance", "multi", "generated"],
        "explain_prompt": "Why does taking the same amount off both sides keep it balanced?",
        "parent_extension": "Set up real cups + counters and act it out.",
        "minutes": 5,
    }


def _gen_growing_pattern(p: dict, rng: random.Random) -> dict:
    step = rng.choice([2, 3, 4, 5])
    start = rng.randint(1, 6)
    seq = [start + step * i for i in range(4)]
    nxt = seq[-1] + step
    seq_str = ", ".join(str(x) for x in seq)
    pos10 = start + step * 9
    return {
        "title": f"Growing by {step}",
        "prompt": f"A growing pattern: {seq_str}, ___ . What comes next? What's the 10th number? What's the rule?",
        "answer": f"{nxt}; 10th = {pos10}; +{step} each step",
        "answer_type": "multi",
        "hints": [
            "Compare each pair of neighbors.",
            f"Each step adds {step}.",
            f"10th = start + 9 × step = {start} + 9×{step} = {pos10}.",
        ],
        "strategies": ["common difference", "rule"],
        "materials": [],
        "tags": ["growing", "pattern", "generated"],
        "explain_prompt": "How would you describe the rule in your own words?",
        "parent_extension": "Build the pattern with blocks: each step adds a row.",
        "minutes": 5,
    }


def _gen_lineup(p: dict, rng: random.Random) -> dict:
    """Generate a 3- or 4-position line-up logic puzzle with deducible answer."""
    pools = [
        ["Anna", "Ben", "Coco"],
        ["Dad", "Mom", "Kid"],
        ["dog", "cat", "bird"],
        ["fox", "rabbit", "bear"],
        ["red", "blue", "green"],
    ]
    people = list(rng.choice(pools))
    rng.shuffle(people)
    n = len(people)
    # solution = the shuffled order; clues uniquely fix it
    pos = {p: i for i, p in enumerate(people)}
    clues = []
    # clue: who is first
    clues.append(f"{people[0].capitalize()} is first.")
    # clue: ordering of last two
    clues.append(f"{people[-2].capitalize()} is right before {people[-1]}.")
    return {
        "title": f"Line up the {n}",
        "prompt": "Find the order. " + " ".join(clues),
        "answer": ", ".join(people),
        "answer_type": "text",
        "hints": [
            "Place fixed positions first.",
            "Use 'right before' to chain.",
            "Test orders against the clues.",
        ],
        "strategies": ["place fixed first", "use clues"],
        "materials": [],
        "tags": ["logic", "ordering", "generated"],
        "explain_prompt": "Which clue ruled out the most options?",
        "parent_extension": "Line up stuffed animals with the same clues.",
        "minutes": 4,
    }


def _gen_domino_sum(p: dict, rng: random.Random) -> dict:
    a, b = rng.randint(0, 6), rng.randint(0, 6)
    return {
        "title": f"Domino sum: {a} + {b}",
        "prompt": f"A domino shows {a} dots on one side and {b} on the other. What's the total? What's the difference (bigger minus smaller)?",
        "answer": f"sum {a + b}; diff {abs(a - b)}",
        "answer_type": "multi",
        "hints": ["Sum: combine.", "Difference: bigger minus smaller.", f"{a + b} and {abs(a - b)}."],
        "strategies": ["count on", "compare"],
        "materials": ["dominoes"],
        "tags": ["dominoes", "generated"],
        "explain_prompt": "When could the sum and the difference be the same number?",
        "parent_extension": "Lay out 3 dominoes. Add their sums.",
        "minutes": 3,
    }


def _gen_calendar(p: dict, rng: random.Random) -> dict:
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    today = rng.randint(0, 6)
    skip = rng.choice([2, 3, 5, 7])
    target_day = days[(today + skip) % 7]
    return {
        "title": f"Calendar jump",
        "prompt": f"Today is {days[today]}. What day will it be in {skip} days?",
        "answer": target_day,
        "answer_type": "text",
        "hints": [
            "Count the days on your fingers.",
            "There are 7 days in a week.",
            f"After 7 days you're back to {days[today]}.",
        ],
        "strategies": ["count on", "modular"],
        "materials": [],
        "tags": ["calendar", "time", "generated"],
        "explain_prompt": "If you skip 14 days, what day is it? Why?",
        "parent_extension": "Mark a real calendar — predict before checking.",
        "minutes": 4,
    }


def _gen_skip_chain(p: dict, rng: random.Random) -> dict:
    step = rng.choice([2, 3, 5, 10])
    start = rng.randint(0, 5)
    n = 6
    seq = [start + step * i for i in range(n)]
    return {
        "title": f"Skip-count by {step} from {start}",
        "prompt": f"Count by {step}s starting at {start}, six numbers. What pattern do the last digits make?",
        "answer": ", ".join(str(x) for x in seq),
        "answer_type": "set",
        "hints": [
            f"Add {step} each time.",
            "Look at the last digit each step.",
            "Sometimes it cycles!",
        ],
        "strategies": ["skip count", "look at digits"],
        "materials": [],
        "tags": ["skip-count", "generated"],
        "explain_prompt": "What's special about the last digits when you skip by 5? By 10?",
        "parent_extension": "Skip-count out loud while jumping a stair at a time.",
        "minutes": 4,
    }


def _gen_compare_diff(p: dict, rng: random.Random) -> dict:
    bigger = rng.randint(8, 25)
    diff = rng.randint(2, 9)
    smaller = bigger - diff
    name_pair = rng.choice([("Lila", "Sam"), ("Anna", "Ben"), ("Maya", "Theo"), ("Coco", "Dev")])
    return {
        "title": f"{name_pair[0]} vs {name_pair[1]}",
        "prompt": f"{name_pair[0]} has {smaller} stickers. {name_pair[1]} has {bigger}. How many MORE does {name_pair[1]} have? How many FEWER does {name_pair[0]} have?",
        "answer": f"{diff}; {diff}",
        "answer_type": "multi",
        "hints": [
            "Line them up.",
            f"{bigger} − {smaller} = the gap.",
            "MORE and FEWER ask the same question.",
        ],
        "strategies": ["line-up model", "compare"],
        "materials": ["counters"],
        "tags": ["compare", "generated"],
        "explain_prompt": "Why are 'how many more' and 'how many fewer' the same number?",
        "parent_extension": "Compare two stacks of LEGO. How many more in the taller stack?",
        "minutes": 4,
    }


def _gen_even_odd(p: dict, rng: random.Random) -> dict:
    n = rng.randint(6, 24)
    is_even = (n % 2) == 0
    return {
        "title": f"Even or odd: {n}",
        "prompt": f"You have {n} cookies. Can you split them into 2 equal piles? Why or why not?",
        "answer": "yes (even)" if is_even else "no (odd, one left over)",
        "answer_type": "text",
        "hints": [
            "Pair them up.",
            "If everyone has a partner, it's even.",
            "If one's alone, it's odd.",
        ],
        "strategies": ["pair model", "halve"],
        "materials": ["counters / cookies"],
        "tags": ["even-odd", "generated"],
        "explain_prompt": "Pick another number. Even or odd? How can you tell without counting?",
        "parent_extension": "Look at the next 5 house numbers on a walk. Predict odd or even.",
        "minutes": 4,
    }


def _gen_path_grid(p: dict, rng: random.Random) -> dict:
    size = rng.choice([2, 3])
    paths = {2: 6, 3: 20}[size]
    return {
        "title": f"Paths on a {size}×{size} grid",
        "prompt": f"On a {size}-by-{size} grid, walk from the bottom-left corner to the top-right corner. You can only go RIGHT or UP. How many different paths?",
        "answer": str(paths),
        "answer_type": "number",
        "hints": [
            f"Each path is {2*size} moves total ({size} right, {size} up).",
            "List them in order, smallest first.",
            f"There are {paths} paths.",
        ],
        "strategies": ["systematic list", "tree diagram"],
        "materials": ["graph paper"],
        "tags": ["paths", "combinations", "generated"],
        "explain_prompt": "Why do bigger grids have so many more paths?",
        "parent_extension": "Walk to the kitchen using only RIGHT and FORWARD moves through the rooms.",
        "minutes": 7,
    }


def _gen_handshakes(p: dict, rng: random.Random) -> dict:
    n = rng.randint(3, 6)
    total = n * (n - 1) // 2
    return {
        "title": f"Handshakes for {n} friends",
        "prompt": f"{n} friends each shake hands once with everyone else. How many handshakes total?",
        "answer": str(total),
        "answer_type": "number",
        "hints": [
            "Draw dots and lines.",
            f"Each person makes {n - 1} handshakes.",
            f"But each handshake involves 2 people, so divide by 2: {n}×{n-1}÷2 = {total}.",
        ],
        "strategies": ["draw graph", "count and adjust"],
        "materials": [],
        "tags": ["combinations", "graph", "generated"],
        "explain_prompt": "What if there were 10 friends?",
        "parent_extension": "Try the dot-and-line drawing for the family at dinner.",
        "minutes": 6,
    }


def _gen_target_sum(p: dict, rng: random.Random) -> dict:
    target = rng.randint(8, 18)
    return {
        "title": f"Hit {target} two ways",
        "prompt": f"Find TWO different pairs of whole numbers that add to {target}. Then find a pair where one of the numbers is bigger than 10.",
        "answer": "many",
        "answer_type": "open",
        "hints": [
            f"Start with 0 + {target}.",
            "Try 1 + ..., 2 + ...",
            f"For >10: try 11 + {target - 11}.",
        ],
        "strategies": ["systematic list", "decompose"],
        "materials": [],
        "tags": ["decompose", "generated"],
        "explain_prompt": "How many pairs are there in total?",
        "parent_extension": "Roll 2 dice; what target sums show up most often?",
        "minutes": 4,
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
    # new in v2
    "coin_change": _gen_coin_change,
    "balance_multi": _gen_balance_multi,
    "growing_pattern": _gen_growing_pattern,
    "lineup": _gen_lineup,
    "domino_sum": _gen_domino_sum,
    "calendar": _gen_calendar,
    "skip_chain": _gen_skip_chain,
    "compare_diff": _gen_compare_diff,
    "even_odd": _gen_even_odd,
    "path_grid": _gen_path_grid,
    "handshakes": _gen_handshakes,
    "target_sum": _gen_target_sum,
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

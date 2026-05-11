"""Parse data/drafts/prek_curriculum.md into Pre-K problem JSON entries.

The Pre-K curriculum lives in Markdown so it can be edited like prose. This
module converts it into the same dict shape used by build_seed.py so the two
sources can be merged into a single seed_problems.json.

The Pre-K problem dict carries 4 fields beyond the standard Problem shape:
  - parent_script: the read-aloud / do-this script
  - magic_prompt_tag: which of the 4 prompts (how_why | another_way | what_if | what_noticed)
  - what_to_listen_for: parent coaching
  - capture_field: voluntary "what did your kid say?" prompt
"""
from __future__ import annotations

import re
from pathlib import Path

MD_FILE = Path(__file__).parent / "drafts" / "prek_curriculum.md"

# Map strand section header (in the markdown) → canonical strand key.
STRAND_KEY = {
    "Number Sense": "number_sense",
    "Add & Subtract Structures": "add_sub_structures",
    "Missing Number Stories": "missing_number_stories",
    "Equality & Balance": "equality_balance",
    "Patterns": "patterns",
    "Logic & Sorting": "logic_classification",
    "Geometry & Spatial": "geometry_spatial",
    "Measurement": "measurement",
    "Counting Ways": "combinatorics_counting",
    "Math Games": "math_games",
}


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:48]


def _parse_metadata(line: str) -> dict[str, str]:
    """Parse a metadata bullet line of the form:
    - **Strand:** number_sense · **Level:** 1 · **Materials:** ... · **Time:** 3-5 min
    """
    parts: dict[str, str] = {}
    for chunk in line.split("·"):
        m = re.search(r"\*\*([\w\s&]+?):\*\*\s*(.+)", chunk.strip())
        if m:
            parts[m.group(1).strip().lower()] = m.group(2).strip()
    return parts


def _parse_time(s: str) -> int:
    """'3-5 min' -> 4, '5 min' -> 5, '5-7 min' -> 6."""
    m = re.match(r"(\d+)(?:[-–](\d+))?\s*min", s)
    if not m:
        return 5
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    return (a + b) // 2


def _split_materials(s: str) -> list[str]:
    """Heuristic split of a free-form materials sentence into a flat list."""
    # Strip parentheticals (used as parent-facing examples), then split.
    s = re.sub(r"\([^)]*\)", "", s).strip()
    # Drop trailing period; split on commas / semicolons / "and".
    s = s.rstrip(". ")
    items = re.split(r",\s*|;\s*|\s+and\s+|\s+or\s+", s)
    return [item.strip(" .–-") for item in items if item.strip(" .–-")]


def _derive_magic_tag(magic_text: str) -> str:
    """Map the magic-prompt section text to one of the four canonical tags."""
    t = magic_text.lower()
    if "another way" in t or "different way" in t or "different reason" in t:
        return "another_way"
    if "what if" in t:
        return "what_if"
    if "what did you notice" in t or "did you notice" in t or "rule" in t:
        return "what_noticed"
    return "how_why"


def _extract_section(block: str, heading: str) -> str:
    """Pull the body of a ### heading section out of a problem block."""
    pat = rf"###\s+{re.escape(heading)}\s*\n(.*?)(?=\n###\s+|\n---|\Z)"
    m = re.search(pat, block, re.DOTALL)
    return m.group(1).strip() if m else ""


def parse_curriculum(md_text: str | None = None) -> list[dict]:
    """Return a list of Pre-K problem dicts in the seed JSON shape."""
    if md_text is None:
        md_text = MD_FILE.read_text(encoding="utf-8")

    lines = md_text.split("\n")
    problems: list[dict] = []
    current_strand: str | None = None

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # Strand section header: "# Number Sense (10)"
        m_strand = re.match(r"^#\s+([A-Z][\w\s&]+?)\s*\(\d+\)\s*$", line)
        if m_strand:
            current_strand = STRAND_KEY.get(m_strand.group(1).strip())
            i += 1
            continue

        # Problem header: "## 1. Title (qualifier)"
        m_prob = re.match(r"^##\s+(\d+)\.\s*(.+?)\s*$", line)
        if m_prob and current_strand:
            title_full = m_prob.group(2).strip()
            title_clean = re.sub(r"\s*\([^)]+\)\s*$", "", title_full).strip()

            # Collect lines until next ## or # header.
            i += 1
            block_lines: list[str] = []
            while i < len(lines):
                nxt = lines[i].rstrip()
                if nxt.startswith("## ") or nxt.startswith("# "):
                    break
                block_lines.append(nxt)
                i += 1
            block = "\n".join(block_lines)

            meta_match = re.search(r"^- (\*\*Strand:.+)$", block, re.MULTILINE)
            meta = _parse_metadata(meta_match.group(1)) if meta_match else {}

            materials = _split_materials(meta.get("materials", ""))
            minutes = _parse_time(meta.get("time", "5 min"))

            parent_script = _extract_section(block, "Parent script")
            magic_prompt = _extract_section(block, "Magic prompt")
            what_to_listen_for = _extract_section(block, "What to listen for")
            capture_field = _extract_section(block, "Optional: what did your kid say?")

            # Strip leading "> " quote markers from script/prompt sections.
            def _strip_quote(s: str) -> str:
                return re.sub(r"^>\s?", "", s, flags=re.MULTILINE).strip()

            parent_script = _strip_quote(parent_script)
            magic_prompt = _strip_quote(magic_prompt)
            capture_field = _strip_quote(capture_field)

            slug = f"prek-{current_strand[:10]}-{_slugify(title_clean)}"[:96]

            # `prompt` field on K-2 problems is what the child sees. For Pre-K
            # the parent is the user, but we still need *something* in `prompt`
            # for list/preview views — use a short summary.
            short_prompt = parent_script.split("\n")[0][:240]

            problems.append({
                "slug": slug,
                "strand": current_strand,
                "level": 1,
                "grade_band": "PK",
                "kind": "parent_led",
                "title": title_clean,
                "prompt": short_prompt,
                "answer": "",
                "answer_type": "open",
                "hints": [],
                "strategies": [],
                "materials": materials,
                "tags": ["PreK", current_strand],
                "explain_prompt": _strip_quote(magic_prompt),
                "parent_extension": "",
                "minutes": minutes,
                "template": None,
                # Pre-K-specific fields:
                "parent_script": parent_script,
                "magic_prompt_tag": _derive_magic_tag(magic_prompt),
                "what_to_listen_for": what_to_listen_for,
                "capture_field": capture_field,
            })
            continue

        i += 1

    return problems


if __name__ == "__main__":
    import json
    probs = parse_curriculum()
    print(f"Parsed {len(probs)} Pre-K problems")
    from collections import Counter
    c = Counter(p["strand"] for p in probs)
    for k, n in sorted(c.items(), key=lambda x: -x[1]):
        print(f"  {k}: {n}")
    # Dump to stdout for quick inspection.
    print("--- first problem ---")
    print(json.dumps(probs[0], indent=2, ensure_ascii=False))

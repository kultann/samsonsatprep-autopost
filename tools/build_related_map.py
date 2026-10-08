#!/usr/bin/env python3
"""Build longform/related_map.json: for every short script id, the long-form videos it should link to,
best match first. The bot links each YouTube Short to the first one that is already public.

  python3 tools/build_related_map.py [path/to/shorts_bank.json]   (default ~/Desktop/SAT/shorts/shorts_bank.json)

Re-run it after the shorts bank or the long-form list changes, then commit longform/related_map.json.
"""
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BANK = Path(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Desktop/SAT/shorts/shorts_bank.json"))
OUT = REPO / "longform" / "related_map.json"

# date-specific videos ("...before November 7") would read wrong months later, so Shorts never link to them
SKIP = ("long-03_", "long-07_")


def longs():
    ids = sorted(json.loads(f.read_text())["id"] for f in (REPO / "longform").glob("*/post.json"))
    return {re.match(r"long-(\d+)_", i).group(1): i for i in ids if not i.startswith(SKIP)}


L = longs()


def has(text, *words):
    return any(re.search(rf"\b{w}", text) for w in words)


def candidates(d):
    """Long-form numbers ("11", "09", ...) for one short, best first."""
    skill, fmt, sec = d["skill"].lower(), d["format"], d["section"]
    q = d.get("question") or {}
    text = " ".join([d["topic"], d.get("hook_text", ""), d["skill"]]).lower()
    c = []
    if fmt == "desmos":
        c.append("02")
    # math by skill
    if skill.startswith("systems of two linear"):
        c.append("11")
    elif skill.startswith("nonlinear equations"):
        c += ["11", "12"] if has(text, "system", "intersect") else ["12", "21"] if has(text, "exponent") else ["12"]
    elif skill.startswith("nonlinear functions"):
        c += ["21", "12"] if has(text, "exponent", "growth", "decay", "half", "compound", "interest", "doubl", "percent") else ["12", "21"]
    elif skill.startswith("equivalent expressions"):
        c += ["12"] if has(text, "quadratic", "factor", "square", "vertex", "binomial") else []
    elif skill.startswith(("linear functions", "linear equations", "linear inequalities")):
        c.append("13")
    elif skill.startswith("percentages"):
        c.append("19")
    elif skill.startswith("ratios, rates"):
        c += ["19"] if has(text, "percent") else ["13"] if has(text, "rate", "per ", "speed") else []
    elif skill.startswith("circles"):
        c.append("20")
    elif skill.startswith(("one-variable data", "two-variable data", "inference from sample", "evaluating statistical")):
        c.append("22")
    elif skill.startswith("probability"):
        c += ["22"] if has(text, "table", "survey", "sample") else []
    # reading and writing by skill
    elif skill.startswith("rhetorical synthesis"):
        c.append("14")
    elif skill.startswith("transitions"):
        c.append("15")
    elif skill.startswith("command of evidence"):
        c += ["16"] if (q.get("table") or has(text, "table", "graph", "data", "chart", "percent", "number")) else ["06", "16"]
    elif skill.startswith("inferences"):
        c.append("17")
    elif skill.startswith("words in context"):
        c.append("18")
    elif skill.startswith(("boundaries", "form, structure")):
        c.append("01")
    elif skill.startswith(("central ideas", "text structure", "cross-text")):
        c.append("06")
    # strategy
    if sec == "strategy":
        if fmt == "countdown" or has(text, "last week", "test week", "night before", "days before", "countdown"):
            c += ["04", "08"]
        if has(text, "pac", "time", "minute", "clock", "second", "timer", "rush"):
            c.append("24")
        if has(text, "adaptive", "module", "harder", "scor"):
            c.append("23")
        if has(text, "test day", "admission", "ticket", "check-in", "check in", "bring", "device", "charg", "center",
               "route", "break", "snack", "morning", "arriv", "id\\b", "exam setup", "doors"):
            c.append("08")
        if has(text, "review", "error log", "mistake", "practice test", "wrong answer"):
            c.append("26")
        if has(text, "desmos", "calculator"):
            c.append("02")
        if has(text, "reference sheet", "formula"):
            c.append("05")
        c += ["25", "24"]
    # by format, then section-wide fallbacks
    if fmt == "formula":
        c.append("05")
    if fmt == "trap":
        c.append("10")
    if sec == "math":
        c += ["09", "27", "10"]
    elif sec == "rw":
        c += ["06", "01", "10"] if skill.startswith(("boundaries", "form, structure")) else ["06", "10"]
    seen, out = set(), []
    for n in c:
        if n in L and n not in seen:
            seen.add(n)
            out.append(L[n])
    return out


def main():
    bank = json.loads(BANK.read_text())
    m = {d["id"]: candidates(d) for d in bank}
    empty = [k for k, v in m.items() if not v]
    if empty:
        sys.exit(f"no related long video for {len(empty)} shorts, e.g. {empty[:5]}")
    OUT.write_text(json.dumps(m, indent=0, sort_keys=True) + "\n")
    first = {}
    for v in m.values():
        first[v[0]] = first.get(v[0], 0) + 1
    print(f"wrote {OUT} for {len(m)} shorts; best match per long video:")
    for k in sorted(first):
        print(f"  {first[k]:4d}  {k}")


if __name__ == "__main__":
    main()

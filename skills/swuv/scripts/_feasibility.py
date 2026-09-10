#!/usr/bin/env python3
"""Constant-propagation feasibility filter for enumerated paths.

Path enumeration walks the SWDD flowchart, which is pure control flow: an edge
exists because control can flow along it, not because the data can.  So the
enumerator happily emits combinations that the source can never take, and the
classic shape is:

    branch 3 : `abSeatActive == FALSE?` yes -> action sets `pullInMs = 300`
    branch 6 : `pullInMs > 0u?`         no  -> requires pullInMs == 0

`2/3/6` is a legal walk of the graph and an impossible run of the code.

Deciding feasibility in general needs symbolic execution and a solver.  This
module deliberately does far less: it propagates *literal constant assignments*
along the path and rejects a path only when a decision provably contradicts a
value assigned earlier on that same path.  Everything it cannot resolve - an
expression, a function result, an unknown variable - makes it forget the
variable rather than guess, so the filter never rejects a feasible path on a
hunch.  What it misses is caught later by reconcile_cases.py.
"""
from __future__ import annotations

import re

# `x = <value>`, excluding ==, !=, <=, >=.  Node labels arrive with several
# assignments run together ("a = TRUE b = 300"), so the starts are located
# first and each value is the slice up to the next start.
ASSIGN_START = re.compile(r'([A-Za-z_][\w.\[\]]*)\s*(?<![=!<>])=(?!=)\s*')
REL_RE = re.compile(r'^\s*(.+?)\s*(<=|>=|==|!=|<|>)\s*(.+?)\s*$')
BOOLEAN = {'TRUE': 1, 'FALSE': 0, 'NULL_PTR': 0}
OPS = {
    '<': lambda a, b: a < b,
    '<=': lambda a, b: a <= b,
    '>': lambda a, b: a > b,
    '>=': lambda a, b: a >= b,
    '==': lambda a, b: a == b,
    '!=': lambda a, b: a != b,
}


def _int(text: str, consts: dict):
    """Literal, boolean idiom or SWDD constant as an int; None if not resolvable."""
    t = (text or '').strip().rstrip(';').strip()
    if not t:
        return None
    if t in BOOLEAN:
        return BOOLEAN[t]
    m = re.fullmatch(r'\(?\s*([+-]?(?:0[xX][0-9a-fA-F]+|\d+))\s*\)?[uUlL]*', t)
    if m:
        return int(m.group(1), 0)
    entry = consts.get(t)
    if isinstance(entry, dict):
        entry = entry.get('value')
    if isinstance(entry, int):
        return entry
    if isinstance(entry, str):
        return _int(entry, {})
    return None


def assignments(label: str) -> list[tuple[str, str]]:
    """Every `lhs = rhs` in one action-node label, in order."""
    starts = list(ASSIGN_START.finditer(label or ''))
    out = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(label)
        out.append((m.group(1), label[m.end():end].strip()))
    return out


def infeasible_reason(path: list[dict], nodes: dict, consts: dict) -> str | None:
    """Why this path cannot run, or None when nothing contradictory was proven.

    Only a decision whose left side holds a value assigned earlier on the very
    same path, compared against a resolvable constant, can reject the path.
    """
    known: dict[str, int] = {}
    for e in path:
        if e.get('number') is not None:
            cond = (nodes.get(e['src'], '') or '').strip().rstrip('?').strip()
            reason = _check(cond, e.get('outcome', ''), known, consts)
            if reason:
                return f"分支 {e['number']}：{reason}"
        # Whatever the destination node assigns is what the next decision sees.
        for lhs, rhs in assignments(nodes.get(e['dst'], '') or ''):
            value = _int(rhs, consts)
            if value is None:
                known.pop(lhs, None)      # unknown value: forget, never guess
            else:
                known[lhs] = value
    return None


def _check(cond: str, outcome: str, known: dict, consts: dict) -> str | None:
    if not cond or '&&' in cond or '||' in cond:
        return None                       # compound: not decidable this cheaply
    out = (outcome or '').strip().upper()
    if not out or out.startswith('CASE') or out.startswith('DEFAULT'):
        return None                       # switch arms carry no truth value
    m = REL_RE.match(cond)
    if not m:
        return None
    lhs, op, rhs = m.group(1).strip(), m.group(2), m.group(3).strip()
    if lhs not in known:
        return None
    right = _int(rhs, consts)
    if right is None:
        return None
    actual = OPS[op](known[lhs], right)
    wanted = out.startswith('Y') or out == 'T'
    if actual == wanted:
        return None
    return (f"路径上此前已把 {lhs} 赋为 {known[lhs]}，"
            f"因此 `{cond}` 只能取 {'真' if actual else '假'}，"
            f"与本分支要求的 {'真' if wanted else '假'} 矛盾")


def split_paths(paths: list[list[dict]], nodes: dict,
                consts: dict) -> tuple[list[list[dict]], list[tuple[list[dict], str]]]:
    """Partition enumerated paths into feasible ones and rejected ones."""
    good, bad = [], []
    for p in paths:
        reason = infeasible_reason(p, nodes, consts)
        if reason:
            bad.append((p, reason))
        else:
            good.append(p)
    return good, bad

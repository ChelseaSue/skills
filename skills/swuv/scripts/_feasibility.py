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
# In-place updates and address-taking change a variable without a plain `=`:
# `i++`, `--n`, `cnt += 2`, `flags |= M`, `Get(&val)`.  Each of them must make
# the propagated value unknown, or a loop counter set to 0 before the loop
# would "prove" that the loop exit can never be taken.
MODIFY_RE = re.compile(
    r'(?:\+\+|--)\s*([A-Za-z_][\w.\[\]]*)'            # ++i / --i
    r'|([A-Za-z_][\w.\[\]]*)\s*(?:\+\+|--)'           # i++ / i--
    r'|([A-Za-z_][\w.\[\]]*)\s*(?:[-+*/%|&^]|<<|>>)='   # i += ...
    r'|(?<!&)&\s*([A-Za-z_][\w.\[\]]*)'                # &val (not &&)
)
BOOLEAN = {'TRUE': 1, 'FALSE': 0, 'NULL_PTR': 0}
# A declaration node: `uint16 u16Index = 0`, `ABBSM_tenuBbsWorkSta enuSta`,
# `int i=0`.  Names declared this way are function locals: nothing but an
# assignment / in-place update / address-taking on the same path can change
# them, so a decision on them that is evaluated twice without such a change
# must come out the same way both times.
DECL_RE = re.compile(r'^\s*(?:const\s+|static\s+|volatile\s+)*[A-Za-z_]\w*(?:\s*\*+)?\s+'
                     r'([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:=.*)?;?\s*$')
KEYWORDS = {'return', 'else', 'case', 'goto', 'break', 'continue', 'default', 'switch', 'if', 'while', 'for', 'do'}
IDENT_RE = re.compile(r'[A-Za-z_]\w*')
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


def locals_of(label: str) -> set[str]:
    out = set()
    for part in re.split(r'<br\s*/?>|\n', label or ''):
        m = DECL_RE.match(part)
        if m and part.split()[0] not in KEYWORDS:
            out.add(m.group(1))
    return out


def infeasible_reason(path: list[dict], nodes: dict, consts: dict) -> str | None:
    """Why this path cannot run, or None when nothing contradictory was proven.

    Two rules, both conservative:
      1. a decision whose left side holds a value assigned earlier on the very
         same path, compared against a resolvable constant, contradicts it;
      2. the same simple decision on function-local variables is taken with
         two different outcomes while nothing on the path between could have
         changed those variables (`if (BBS_ARMED == sta) ... if (BBS_ARMED == sta)`).
    """
    known: dict[str, int] = {}
    local_vars: set[str] = set()
    decided: dict[str, tuple[bool, int]] = {}     # cond text -> (truth, branch no)
    for e in path:
        if e.get('number') is not None:
            cond = (nodes.get(e['src'], '') or '').strip().rstrip('?').strip()
            reason = _check(cond, e.get('outcome', ''), known, consts)
            if reason:
                return f"分支 {e['number']}：{reason}"
            out = (e.get('outcome') or '').strip().upper()
            truth = True if out.startswith(('Y', 'T')) else False if out.startswith(('N', 'F')) else None
            names = set(IDENT_RE.findall(cond))
            if (truth is not None and cond and '&&' not in cond and '||' not in cond
                    and '(' not in cond and names and (names & local_vars)
                    and all(n in local_vars or n in consts or n in BOOLEAN or n.isupper()
                            for n in names)):
                prev = decided.get(cond)
                if prev is not None and prev[0] != truth:
                    return (f"分支 {e['number']}：判断 `{cond}` 在分支 {prev[1]} 处已取 "
                            f"{'真' if prev[0] else '假'}，其间没有语句改变其局部变量，"
                            f"不可能再取 {'真' if truth else '假'}")
                decided.setdefault(cond, (truth, e['number']))
        # Whatever the destination node assigns is what the next decision sees.
        label = nodes.get(e['dst'], '') or ''
        local_vars |= locals_of(label)
        touched = set()
        for lhs, rhs in assignments(label):
            value = _int(rhs, consts)
            if value is None:
                known.pop(lhs, None)      # unknown value: forget, never guess
            else:
                known[lhs] = value
            touched.add(lhs.split('[')[0].split('.')[0])
        for m in MODIFY_RE.finditer(label):
            name = next(g for g in m.groups() if g)
            known.pop(name, None)
            touched.add(name.split('[')[0].split('.')[0])
        if touched:
            decided = {c: v for c, v in decided.items()
                       if not (set(IDENT_RE.findall(c)) & touched)}
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

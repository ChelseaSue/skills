#!/usr/bin/env python3
"""Derive SWE.4 unit test cases from a parsed SWDD model.

Each case is one path through a unit's SWDD flowchart.  Paths are enumerated
from Start, then a greedy set cover picks the smallest set that exercises every
numbered branch, which is what makes the generated suite meet the 100% branch
coverage KPI by construction rather than by hope.

The "test target" column names the branch numbers a case covers ("覆盖分支 3/5"),
and the "test steps" column annotates each decision with the branch it takes
(`--3`), mirroring the reviewed company deliverable so the mapping back to the
SWDD stays checkable by a human.

Usage:
  python gen_cases.py --model model.json --spec ut_spec.json -o cases.json
  python gen_cases.py --model model.json --spec ut_spec.json --summary
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _feasibility import split_paths

MAX_PATHS = 4000          # safety valve for pathological flowcharts
MAX_PATH_LEN = 400


def build_graph(branches: list[dict], all_edges: list[dict] | None = None) -> dict:
    """Adjacency built from the flowchart edges of one unit."""
    adj: dict[str, list[dict]] = {}
    for e in (all_edges or []):
        adj.setdefault(e['src'], []).append(e)
    return adj


def enumerate_paths(adj: dict, start: str) -> list[list[dict]]:
    """All Start->terminal paths, never reusing an edge within one path.

    Not reusing an edge lets a loop be entered once (enough to cover its body
    and its exit) while guaranteeing termination.
    """
    paths: list[list[dict]] = []

    def walk(node: str, used: set[tuple], acc: list[dict]) -> None:
        if len(paths) >= MAX_PATHS or len(acc) > MAX_PATH_LEN:
            return
        outs = [e for e in adj.get(node, []) if (e['src'], e['dst'], e.get('label', '')) not in used]
        if not outs:
            if acc:
                paths.append(list(acc))
            return
        for e in outs:
            key = (e['src'], e['dst'], e.get('label', ''))
            used.add(key)
            acc.append(e)
            walk(e['dst'], used, acc)
            acc.pop()
            used.discard(key)

    walk(start, set(), [])
    return paths


def find_start(adj: dict, edges: list[dict]) -> str | None:
    dsts = {e['dst'] for e in edges}
    for n in adj:
        if n not in dsts:
            return n
    for n in adj:
        if n.lower().startswith('start'):
            return n
    return next(iter(adj), None)


def select_paths(paths: list[list[dict]], targets: set[int]) -> list[list[dict]]:
    """Greedy set cover over the numbered branches."""
    remaining = set(targets)
    chosen: list[list[dict]] = []
    pool = list(paths)
    while remaining and pool:
        best, best_gain = None, 0
        for p in pool:
            gain = len({e['number'] for e in p if e['number'] in remaining})
            if gain > best_gain or (gain == best_gain and best is not None
                                    and gain > 0 and len(p) < len(best)):
                best, best_gain = p, gain
        if not best or best_gain == 0:
            break
        chosen.append(best)
        remaining -= {e['number'] for e in best if e['number'] is not None}
        pool.remove(best)
    return chosen


REL_OPS_BOUNDARY = ('<', '<=', '>', '>=')


def design_method(fn: dict, spec: dict) -> str:
    """Which derivation methods actually apply to this unit.

    ISO 26262-6 asks for an appropriate *combination* of methods, not a fixed
    phrase on every row.  Claiming equivalence classes for a unit with no
    branches, or boundary values for one that compares nothing, is exactly the
    kind of blanket wording a reviewer bounces (checklist items 6 and 7).

      requirement analysis : always
      equivalence classes  : the unit has decisions to partition
      boundary values      : some decision compares against a limit
    """
    names = spec.get('derivation_methods') or ['需求分析', '等价类', '边界值', '错误推测']
    req, equiv, bound = (names + ['需求分析', '等价类', '边界值'])[:3]

    applied = [req]
    if fn.get('branch_no_expected', 0) > 0:
        applied.append(equiv)
    for b in fn.get('branches', []):
        m = REL_RE.match((b.get('decision') or '').strip().rstrip('?'))
        if m and m.group(2) in REL_OPS_BOUNDARY:
            applied.append(bound)
            break
    return '基于' + '、'.join(applied)


def priority_letter(priority: str, mapping: dict) -> str:
    try:
        value = int(str(priority).strip() or 0)
    except ValueError:
        value = 0
    for letter in ('H', 'M', 'L'):
        if letter in mapping and value >= int(mapping[letter]):
            return letter
    return 'L'


REL_RE = re.compile(r'^\s*(.+?)\s*(<=|>=|==|!=|<|>)\s*(.+?)\s*$')
SWITCH_RE = re.compile(r'^\s*switch\s*\(\s*(.+?)\s*\)\s*$')
CALL_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s*\(.*\)\s*$')
NUM_RE = re.compile(r'-?\d+')
TODO = '【待填具体取值】'


def _as_int(token: str, consts: dict) -> int | None:
    """Resolve a right-hand side to a number: literal, cast, or SWDD constant."""
    t = (token or '').strip()
    if t in consts:
        t = consts[t]
    t = t.replace('(uint8)', '').replace('(uint16)', '').replace('(uint32)', '')
    t = t.replace('(sint8)', '').replace('(sint16)', '').replace('(sint32)', '')
    t = t.strip('() ')
    t = re.sub(r'([0-9])[uUlL]+\b', r'\1', t)
    if re.fullmatch(r'-?\d+', t):
        return int(t)
    m = NUM_RE.fullmatch(t)
    return int(m.group()) if m else None


def _boundary(op: str, rhs: int, want_true: bool) -> int:
    """Value that makes `lhs op rhs` take the wanted outcome, on the boundary."""
    table = {
        '<':  (rhs - 1, rhs),
        '<=': (rhs, rhs + 1),
        '>':  (rhs + 1, rhs),
        '>=': (rhs, rhs - 1),
        '==': (rhs, rhs + 1),
        '!=': (rhs + 1, rhs),
    }
    return table[op][0 if want_true else 1]


def derive_input(condition: str, outcome: str, consts: dict) -> str:
    """Turn one decision plus its outcome into a concrete input assignment.

    Falls back to the condition text plus a TODO marker whenever the value
    cannot be derived mechanically, so the gap is visible instead of silently
    producing an untestable step.
    """
    cond = (condition or '').strip().rstrip('?').strip()
    out = (outcome or '').strip()

    m = SWITCH_RE.match(cond)
    if m and out.lower().startswith('case'):
        value = out.split(None, 1)[1].strip() if ' ' in out else TODO
        return f"{m.group(1)} = {value}"
    if m and out.lower() == 'default':
        return f"{m.group(1)} = <不在任何 case 内的值> {TODO}"

    want_true = out.upper().startswith('Y') or out.upper() == 'T'

    # Compound conditions cannot be satisfied by a single assignment.
    if '&&' in cond or '||' in cond:
        return f"使 ({cond}) 为 {'真' if want_true else '假'} {TODO}"

    m = REL_RE.match(cond)
    if m:
        lhs, op, rhs = m.group(1).strip(), m.group(2), m.group(3).strip()
        # boolean idiom: `flag != FALSE`
        if rhs in ('FALSE', 'TRUE'):
            truthy = want_true if rhs == 'FALSE' and op == '!=' else \
                     (not want_true if rhs == 'FALSE' and op == '==' else
                      want_true if rhs == 'TRUE' and op == '==' else not want_true)
            return f"{lhs} = {'TRUE' if truthy else 'FALSE'}"
        # a service call compared against a status: drive it through the stub
        call = CALL_RE.match(lhs)
        if call:
            if op == '!=':
                return (f"打桩 {call.group(1)} 返回 {'非 ' + rhs if want_true else rhs}")
            return (f"打桩 {call.group(1)} 返回 {rhs if want_true else '非 ' + rhs}")
        value = _as_int(rhs, consts)
        if value is not None:
            return f"{lhs} = {_boundary(op, value, want_true)}"
        return f"{lhs} {op} {rhs} 取 {'真' if want_true else '假'} {TODO}"

    # bare predicate, typically a function call used directly as a condition
    call = CALL_RE.match(cond)
    if call:
        return f"打桩 {call.group(1)} 返回 {'真' if want_true else '假'}"
    return f"{cond} 取 {'真' if want_true else '假'} {TODO}"


def steps_text(path: list[dict], nodes: dict, consts: dict) -> str:
    """Concrete input assignments along the path, each tagged with its branch.

    Mirrors the reviewed deliverable: numbered assignment groups, each ending in
    `--<branch>`; consecutive branches produced by one assignment are merged
    into a single `--a,b` tag.
    """
    steps: list[tuple[str, list[int]]] = []
    for e in path:
        if e['number'] is None:
            continue
        cond = nodes.get(e['src'], e['src'])
        text = derive_input(cond, e['outcome'], consts)
        if steps and steps[-1][0] == text:
            steps[-1][1].append(e['number'])
        else:
            steps.append((text, [e['number']]))
    if not steps:
        return '无分支，顺序执行'
    return '\n'.join(
        f"{i}、{text};--{','.join(str(n) for n in nums)}"
        for i, (text, nums) in enumerate(steps, 1)
    )


TERMINALS = {'start', 'end'}


def expected_text(path: list[dict], nodes: dict) -> str:
    """Effects reached on the path that are not decisions or flow terminals."""
    decisions = {e['src'] for e in path if e['number'] is not None}
    effects = []
    for e in path:
        label = nodes.get(e['dst'], e['dst'])
        if e['dst'] in decisions or not label:
            continue
        if label.strip().lower() in TERMINALS:
            continue
        if label not in effects:
            effects.append(label)
    return '\n'.join(effects[-4:]) if effects else '函数正常返回'


def function_paths(fn: dict) -> tuple[list[list[dict]], dict]:
    """Every enumerable path of one function, plus its node-label map.

    Shared with reconcile_cases.py so that a repaired case is rebuilt from the
    same graph the case was generated from.
    """
    chart_edges = fn.get('chart_edges') or []
    nodes = fn.get('chart_nodes') or {}
    if not chart_edges:
        return [], nodes
    adj = build_graph(fn['branches'], chart_edges)
    start = find_start(adj, chart_edges)
    if not start:
        return [], nodes
    return enumerate_paths(adj, start), nodes


def gen_for_function(fn: dict, spec: dict, seq: list[int],
                    consts: dict | None = None,
                    rejected: dict | None = None) -> list[dict]:
    paths, nodes = function_paths(fn)
    if not paths:
        return []
    consts = consts or {}

    # Drop the walks the data can never take before the set cover runs, so the
    # cover is computed over paths that a test can actually follow.
    paths, bad = split_paths(paths, nodes, consts)
    if bad and rejected is not None:
        rejected[fn['name']] = [
            {'branches': sorted({e['number'] for e in p if e['number'] is not None}),
             'reason': why} for p, why in bad]
    if not paths:
        return []

    targets = {b['number'] for b in fn['branches']}
    if targets:
        chosen = select_paths(paths, targets)
    else:
        chosen = paths[:1]
    if not chosen and paths:
        chosen = paths[:1]

    prio = priority_letter(fn.get('priority', ''), spec.get('priority_map', {}))
    cases = []
    for i, path in enumerate(chosen, 1):
        covered = sorted({e['number'] for e in path if e['number'] is not None})
        seq[0] += 1
        digits = int(spec.get('id_prefix', {}).get('digits', 5))
        cases.append({
            'module': spec.get('component', ''),
            'priority': prio,
            'case_id': f"{spec.get('id_prefix', {}).get('case', 'SUT-')}{seq[0]:0{digits}d}",
            'case_name': f"{fn['name']}.{i:03d}",
            'unit_id': fn.get('unit_id', ''),
            'unit_name': fn['name'],
            'test_method': (spec.get('test_methods') or ['功能测试'])[0],
            'design_method': design_method(fn, spec),
            'test_target': ('覆盖分支 ' + '/'.join(str(c) for c in covered)) if covered
                           else '覆盖整个函数',
            'precondition': spec.get('precondition_default', ''),
            'steps': steps_text(path, nodes, consts or {}),
            'expected': expected_text(path, nodes),
            'verdict': spec.get('verdict_default', ''),
            'covers_branches': covered,
        })
    return cases


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', type=Path, required=True, help='output of parse_swdd.py')
    ap.add_argument('--spec', type=Path, required=True, help='ut_spec.json')
    ap.add_argument('-o', '--out', type=Path)
    ap.add_argument('--summary', action='store_true')
    args = ap.parse_args()

    model = json.loads(args.model.read_text(encoding='utf-8'))
    spec = json.loads(args.spec.read_text(encoding='utf-8'))

    seq = [int(spec.get('id_prefix', {}).get('start', 1)) - 1]
    all_cases, uncovered, rejected = [], {}, {}
    for fn in model['functions']:
        cases = gen_for_function(fn, spec, seq, model.get('constants', {}), rejected)
        all_cases.extend(cases)
        targets = {b['number'] for b in fn['branches']}
        got = set()
        for c in cases:
            got |= set(c['covers_branches'])
        if targets - got:
            uncovered[fn['name']] = sorted(targets - got)

    # A branch that survives only on rejected paths is not a generator gap -
    # it is a branch the design cannot reach, and that is a finding of its own.
    unreachable = {}
    for name, gaps in uncovered.items():
        only_bad = {b for entry in rejected.get(name, []) for b in entry['branches']}
        both = sorted(set(gaps) & only_bad)
        if both:
            unreachable[name] = both

    result = {'component': model['component'], 'cases': all_cases,
              'uncovered_branches': uncovered,
              'rejected_paths': rejected,
              'unreachable_branches': unreachable}
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"wrote {args.out}  ({len(all_cases)} cases)")

    if args.summary or not args.out:
        by_fn: dict[str, list[dict]] = {}
        for c in all_cases:
            by_fn.setdefault(c['unit_name'], []).append(c)
        print(f"{'function':<26}{'prio':<6}{'cases':>6}  targets")
        for fn in model['functions']:
            cs = by_fn.get(fn['name'], [])
            tgt = ' | '.join(c['test_target'] for c in cs[:3])
            if len(cs) > 3:
                tgt += ' | ...'
            print(f"{fn['name']:<26}{(cs[0]['priority'] if cs else '-'):<6}{len(cs):>6}  {tgt}")
        print(f"\ntotal cases: {len(all_cases)}")
        if rejected:
            total = sum(len(v) for v in rejected.values())
            print()
            print(f"已剔除 {total} 条数据上不可行的路径（常量传播判定）：")
            for k, entries in rejected.items():
                for e in entries[:2]:
                    print(f"  {k} {e['branches']}: {e['reason']}")
                if len(entries) > 2:
                    print(f"  {k} ... 另有 {len(entries) - 2} 条")
        if unreachable:
            print()
            print("以下分支只出现在被剔除的路径上，可能是详设里走不到的分支，请人工确认：")
            for k, v in unreachable.items():
                print(f"  {k}: {v}")
        if uncovered:
            print("UNCOVERED branches:")
            for k, v in uncovered.items():
                print(f"  {k}: {v}")
            return 1
        print("every SWDD branch is covered by at least one case.")
    return 0


if __name__ == '__main__':
    sys.exit(main())

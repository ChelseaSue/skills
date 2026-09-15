#!/usr/bin/env python3
"""Bring the case table back in line with the tests that were actually written.

Path enumeration cannot prove feasibility in general (see _feasibility.py for
what the cheap filter does catch), so an implementer will sometimes find a
generated path impossible and walk a different one.  When that happens the case
table keeps describing the old path and the deliverable quietly rots: cases
nobody implements, tests nobody can trace.

This closes the loop in the only direction that is sound - the executed test is
the ground truth, and the case is rebuilt from the path the test really walks:

  marker says branches != case says branches  -> rebuild the case from the path
  marker names no case, but walks a path      -> add the missing case
  case claimed by no test                     -> report; a human decides

Rebuilding reuses gen_cases.steps_text/expected_text on the real path, so a
repaired row is derived exactly like a generated one, not hand-edited.

Prints a diff by default and changes nothing.  Pass --apply to write.

Usage:
  python reconcile_cases.py --model swdd_model.json --spec ut_spec.json \
      --cases cases.json --root . [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_evidence import map_tests_to_cases
from _feasibility import split_paths
from gen_cases import expected_text, function_paths, select_paths, steps_text


def branch_set(text: str) -> set[int]:
    return {int(x) for x in re.split(r'[^\d]+', text or '') if x}


def path_for(paths: list[list[dict]], wanted: set[int]) -> list[dict] | None:
    """Shortest enumerated path whose numbered branches are exactly `wanted`."""
    hits = [p for p in paths
            if {e['number'] for e in p if e['number'] is not None} == wanted]
    return min(hits, key=len) if hits else None


def rebuilt(case: dict, path: list[dict], nodes: dict, consts: dict) -> dict:
    covered = sorted({e['number'] for e in path if e['number'] is not None})
    out = dict(case)
    out['test_target'] = ('覆盖分支 ' + '/'.join(str(c) for c in covered)) if covered \
        else '覆盖整个函数'
    out['steps'] = steps_text(path, nodes, consts)
    out['expected'] = expected_text(path, nodes)
    out['covers_branches'] = covered
    return out


def next_ids(cases: list[dict], unit: str, spec: dict) -> tuple[str, str]:
    """Next free case name within the unit and next free global case id.

    Existing ids are never renumbered: they are quoted in the deliverables and
    in the test marker comments.
    """
    nums = [int(c['case_name'].rsplit('.', 1)[1]) for c in cases
            if c['unit_name'] == unit and '.' in c['case_name']]
    name = f"{unit}.{(max(nums) + 1) if nums else 1:03d}"
    prefix = spec.get('id_prefix', {}).get('case', 'SUT-')
    digits = int(spec.get('id_prefix', {}).get('digits', 5))
    used = [int(c['case_id'][len(prefix):]) for c in cases
            if c['case_id'].startswith(prefix) and c['case_id'][len(prefix):].isdigit()]
    return name, f"{prefix}{(max(used) + 1) if used else 1:0{digits}d}"


def reconcile(cases: list[dict], model: dict, spec: dict, root: Path) -> dict:
    consts = model.get('constants', {})
    fns = {f['name']: f for f in model['functions']}
    known = {c['case_name']: c['unit_name'] for c in cases}
    marks = map_tests_to_cases(spec, root, known)

    cache: dict[str, tuple[list, dict]] = {}

    def paths_of(unit: str):
        if unit not in cache:
            fn = fns.get(unit)
            cache[unit] = function_paths(fn) if fn else ([], {})
        return cache[unit]

    by_name = {c['case_name']: c for c in cases}
    out = list(cases)
    repaired, added, unresolved, bare = [], [], [], []
    mislabeled: list = []
    supplementary: list = []
    conflicts: list = []
    claimed: set[str] = set()
    # case name -> branch set a test earlier in this run established for it.
    # A later test quoting the same number with a *different* path is a
    # labelling conflict, not new evidence; repairing the case twice would just
    # ping-pong between the two paths on every run.
    settled: dict[str, set[int]] = {}

    # deterministic order so a rerun produces the same numbering
    for test in sorted(marks):
        mark = marks[test]
        walked = branch_set(mark['branches'])
        name = mark['case_name']

        if mark.get('supp') or mark.get('adds'):
            # Declared supplementary coverage: it states what it adds, not a
            # path, so there is nothing to reconcile against the case table.
            supplementary.append((test, name, sorted(branch_set(mark['adds']))))
            if name:
                claimed.add(name)
            continue

        if name and name in settled and walked and not (walked >= settled[name]
                                                          or settled[name] >= walked):
            conflicts.append((test, name, sorted(settled[name]), sorted(walked)))
            name = ''          # fall through: treated like an unlabelled test
            mark = dict(mark, case_name='')

        if name:
            case = by_name[name]
            want = set(case.get('covers_branches') or [])
            if walked:
                settled.setdefault(name, walked)
            # A superset is not drift: a test that drives a loop over several
            # items legitimately walks both arms of a decision inside it, so it
            # covers everything the case asks for and more.
            if not walked or walked >= want:
                claimed.add(name)
                continue
            # The walked path may simply belong to a different existing case:
            # then the marker quotes the wrong number and the case table is
            # fine.  Rewriting two perfectly good cases to chase a typo would
            # be the wrong repair, so this is reported instead.
            twin = next((c for c in out
                         if c['unit_name'] == case['unit_name']
                         and c['case_name'] != name
                         and set(c.get('covers_branches') or []) == walked), None)
            if twin is not None:
                mislabeled.append((test, name, twin['case_name'], sorted(walked)))
                claimed.add(twin['case_name'])
                continue
            claimed.add(name)
            paths, nodes = paths_of(case['unit_name'])
            path = path_for(paths, walked)
            if path is None:
                unresolved.append((test, name, sorted(walked)))
                continue
            new = rebuilt(case, path, nodes, consts)
            out[out.index(case)] = new
            by_name[name] = new
            repaired.append((test, name, sorted(case.get('covers_branches') or []),
                             sorted(walked)))
            continue

        if not walked:
            bare.append(test)
            continue

        unit = next((u for u in sorted(fns, key=len, reverse=True)
                     if test[5:].startswith(u + '_') or test[5:] == u), None)
        if unit is None:
            bare.append(test)
            continue
        # The case may already exist and the marker merely omits its number;
        # adding a second row with the same path would duplicate the case table.
        twin = next((c for c in out if c['unit_name'] == unit
                     and set(c.get('covers_branches') or []) == walked), None)
        if twin is not None:
            mislabeled.append((test, '（未写用例号）', twin['case_name'], sorted(walked)))
            claimed.add(twin['case_name'])
            continue
        paths, nodes = paths_of(unit)
        path = path_for(paths, walked)
        if path is None:
            unresolved.append((test, f'（{unit} 无对应用例）', sorted(walked)))
            continue
        name, case_id = next_ids(out, unit, spec)
        template = next((c for c in out if c['unit_name'] == unit), None)
        base = dict(template) if template else {
            'module': spec.get('component', ''), 'priority': 'M',
            'unit_id': fns[unit].get('unit_id', ''), 'unit_name': unit,
            'test_method': (spec.get('test_methods') or ['功能测试'])[0],
            'design_method': '', 'precondition': spec.get('precondition_default', ''),
            'verdict': spec.get('verdict_default', '')}
        base.update({'case_id': case_id, 'case_name': name, 'unit_name': unit,
                     'unit_id': fns[unit].get('unit_id', '')})
        new = rebuilt(base, path, nodes, consts)
        # keep cases of one unit together, in case-name order
        last = max(i for i, c in enumerate(out) if c['unit_name'] == unit) \
            if any(c['unit_name'] == unit for c in out) else len(out) - 1
        out.insert(last + 1, new)
        claimed.add(name)
        added.append((test, name, case_id, sorted(walked)))

    # Repairs narrow a case to the path its test really walks, which can drop
    # branches the original (infeasible) path was carrying.  The case table is
    # supposed to cover every SWDD branch by construction, so whatever fell out
    # is covered again here rather than left as a silent hole.
    restored = []
    for unit, fn in fns.items():
        targets = {b['number'] for b in fn.get('branches', [])}
        if not targets:
            continue
        have = set()
        for c in out:
            if c['unit_name'] == unit:
                have |= set(c.get('covers_branches') or [])
        missing = targets - have
        if not missing:
            continue
        paths, nodes = paths_of(unit)
        good, _ = split_paths(paths, nodes, consts)
        for path in select_paths(good, missing):
            name, case_id = next_ids(out, unit, spec)
            template = next((c for c in out if c['unit_name'] == unit), None)
            base = dict(template) if template else {
                'module': spec.get('component', ''), 'priority': 'M',
                'unit_id': fn.get('unit_id', ''), 'unit_name': unit,
                'test_method': (spec.get('test_methods') or ['功能测试'])[0],
                'design_method': '', 'precondition': spec.get('precondition_default', ''),
                'verdict': spec.get('verdict_default', '')}
            base.update({'case_id': case_id, 'case_name': name, 'unit_name': unit,
                         'unit_id': fn.get('unit_id', '')})
            new = rebuilt(base, path, nodes, consts)
            last = max(i for i, c in enumerate(out) if c['unit_name'] == unit)
            out.insert(last + 1, new)
            restored.append((unit, name, case_id, new['covers_branches'],
                             sorted(missing & set(new['covers_branches']))))

    orphan_cases = [c for c in out if c['case_name'] not in claimed]
    return {'cases': out, 'repaired': repaired, 'added': added,
            'unresolved': unresolved, 'bare': bare,
            'mislabeled': mislabeled, 'supplementary': supplementary,
            'conflicts': conflicts,
            'restored': restored,
            'orphan_cases': orphan_cases}


def report(res: dict) -> None:
    if res['repaired']:
        print(f"\n用例走向已按实测修正 ({len(res['repaired'])} 条)：")
        for test, name, old, new in res['repaired']:
            print(f"  {name:26} {old} -> {new}")
            print(f"  {'':26} 依据 {test}")
    if res['added']:
        print(f"\n为无用例的测试补建用例 ({len(res['added'])} 条)：")
        for test, name, cid, br in res['added']:
            print(f"  {cid} {name:26} 覆盖分支 {br}")
            print(f"  {'':>{len(cid) + 1}} 请把标记注释改成："
                  f"/* {cid} {name} - covers branches "
                  f"{'/'.join(str(b) for b in br)}: <为什么> */")
            print(f"  {'':>{len(cid) + 1}} 位于 {test}")
    if res['restored']:
        print()
        print(f"为恢复分支全覆盖补建用例 ({len(res['restored'])} 条)：")
        print("  修正走向后这些分支失去了用例，用例集必须覆盖全部详设分支，故补回。")
        for unit, name, cid, br, gained in res['restored']:
            print(f"  {cid} {name:26} 覆盖分支 {br}")
            print(f"  {'':>{len(cid) + 1}} 补回的分支 {gained}")
    if res['conflicts']:
        print()
        print(f"同一用例号被路径不同的测试重复声明 ({len(res['conflicts'])} 条)：")
        print("  第一个测试已把该用例修成它的路径；后面这些测试按“未写用例号”处理（匹配已有用例或补建），请把注释改成它们真正对应的用例号。")
        for test, name, first, walked in res['conflicts']:
            print(f"  {test}")
            print(f"    注释写的 {name}，该用例已按 {first} 修正，本测试实走 {walked}")
    if res['mislabeled']:
        print()
        print(f"标记注释里的用例号写错了 ({len(res['mislabeled'])} 条)：")
        print("  测试实走的分支正好是同单元的另一条用例，用例表没问题，改注释即可。")
        for test, wrong, right, br in res['mislabeled']:
            print(f"  {test}")
            print(f"    注释写的 {wrong}，实走分支 {br}，应为 {right}")
    if res['supplementary']:
        print()
        print(f"补充测试，不进用例表 ({len(res['supplementary'])} 条)：")
        print("  这些测试声明了自己在用例集之外额外覆盖的分支，属正常，无需处理。")
        for test, name, br in res['supplementary']:
            print(f"  {test} 新增分支 {br}" + (f"（同时实现 {name}）" if name else ""))
    if res['unresolved']:
        print(f"\n无法机械修正，需人工判断 ({len(res['unresolved'])} 条)：")
        print("  测试声明的分支组合在详设流程图上找不到一条完整路径。三种可能：")
        print("    1) 注释只写了该测试新增覆盖的分支，没写完整走向 —— 补全即可；")
        print("    2) 注释里的分支号写错了；")
        print("    3) 详设与实现已经不一致，这是要查的问题。")
        for test, name, br in res['unresolved']:
            print(f"  {test} -> {name} 声明 {br}")
    if res['bare']:
        print(f"\n缺标记注释，无法参与追溯 ({len(res['bare'])} 条)：")
        for test in res['bare']:
            print(f"  {test}")
    if res['orphan_cases']:
        print(f"\n仍无测试实现的用例 ({len(res['orphan_cases'])} 条)：")
        print("  这几条是漏测还是该删，脚本不替你决定。")
        for c in res['orphan_cases']:
            print(f"  {c['case_id']} {c['case_name']:26} {c['test_target']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--spec', type=Path, required=True)
    ap.add_argument('--cases', type=Path, required=True)
    ap.add_argument('--root', type=Path, default=Path('.'))
    ap.add_argument('--apply', action='store_true',
                    help='write the reconciled cases back to --cases')
    args = ap.parse_args()

    payload = json.loads(args.cases.read_text(encoding='utf-8'))
    model = json.loads(args.model.read_text(encoding='utf-8'))
    spec = json.loads(args.spec.read_text(encoding='utf-8'))

    res = reconcile(payload['cases'], model, spec, args.root)
    report(res)

    changed = len(res['repaired']) + len(res['added']) + len(res['restored'])
    print(f"\n共 {len(res['cases'])} 条用例，其中 {changed} 条需要变更。")
    if not args.apply:
        print("未写入。确认无误后加 --apply 落盘，然后重跑 build_deliverables.py "
              "与 build_evidence.py。")
        return 0
    payload['cases'] = res['cases']
    args.cases.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                          encoding='utf-8')
    print(f"已写入 {args.cases}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

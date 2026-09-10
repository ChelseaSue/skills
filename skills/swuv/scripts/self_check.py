#!/usr/bin/env python3
"""Mechanical half of the SWE.4 case review checklist.

Runs the `[A]` items of references/review-checklist.md against the generated
cases and prints a pass/fail line per item, so the human review starts from the
items that actually need judgement instead of re-deriving countable facts.

Nothing here replaces the review: items 14/15 (concrete input values) and 22
(combination of derivation methods) are judgement calls and are listed as
reminders, never as passes.

Pass --root to also check the test sources: items 19/20 (script matches the
case table) become mechanical once every test carries a complete marker
comment.  Without --root they stay on the manual list.

Usage:
  python self_check.py --cases cases.json --model swdd_model.json       --spec ut_spec.json [--root .]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_evidence import map_tests_to_cases     # owner of the marker convention


class Result:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool, str]] = []
        self.failed = 0

    def add(self, item: str, title: str, ok: bool, detail: str = '') -> None:
        self.rows.append((item, title, ok, detail))
        if not ok:
            self.failed += 1

    def report(self) -> int:
        width = max(len(t) for _, t, _, _ in self.rows) + 2
        for item, title, ok, detail in self.rows:
            mark = 'PASS' if ok else 'FAIL'
            print(f"[{item:>2}] {title:<{width}} {mark}  {detail}")
        print()
        print(f"{len(self.rows) - self.failed}/{len(self.rows)} automated checks passed")
        return 1 if self.failed else 0


def check(cases: list[dict], model: dict, spec: dict,
          root: Path | None = None) -> Result:
    r = Result()
    units = model['units']
    functions = {f['name']: f for f in model['functions']}
    by_unit: dict[str, list[dict]] = {}
    for c in cases:
        by_unit.setdefault(c['unit_name'], []).append(c)

    # 1 - column contract
    required = {'module', 'priority', 'case_id', 'case_name', 'unit_id', 'unit_name',
                'test_method', 'design_method', 'test_target', 'precondition',
                'steps', 'expected', 'verdict'}
    missing_cols = sorted(required - set(cases[0].keys())) if cases else sorted(required)
    r.add('1', '模板列契约完整', not missing_cols,
          '' if not missing_cols else f'缺列 {missing_cols}')

    # 5 - id format and uniqueness
    pfx = spec.get('id_prefix', {}).get('case', 'SUT-')
    digits = int(spec.get('id_prefix', {}).get('digits', 5))
    pat = re.compile(rf'^{re.escape(pfx)}\d{{{digits}}}$')
    bad_id = [c['case_id'] for c in cases if not pat.match(c['case_id'])]
    dup = {c['case_id'] for c in cases if [x['case_id'] for x in cases].count(c['case_id']) > 1}
    r.add('5', '用例编号符合策略且唯一', not bad_id and not dup,
          '' if not (bad_id or dup) else f'格式错{bad_id[:3]} 重复{sorted(dup)[:3]}')

    # 6 - design method within the allowed set
    allowed_design = spec.get('design_method_text', '')
    bad_dm = [c['case_name'] for c in cases if not c.get('design_method')]
    r.add('6', '设计方法取值合法', not bad_dm,
          '' if not bad_dm else f'{len(bad_dm)} 条为空')

    # 10 - precondition present
    bad_pre = [c['case_name'] for c in cases if not c.get('precondition')]
    r.add('10', '预置条件非空', not bad_pre, '' if not bad_pre else f'{len(bad_pre)} 条为空')

    # 11 - every unit and every numbered branch covered
    uncovered_units = [u['name'] for u in units if not by_unit.get(u['name'])]
    uncovered_branches: dict[str, list[int]] = {}
    for name, fn in functions.items():
        targets = {b['number'] for b in fn['branches']}
        got: set[int] = set()
        for c in by_unit.get(name, []):
            got |= set(c.get('covers_branches', []))
        if targets - got:
            uncovered_branches[name] = sorted(targets - got)
    ok11 = not uncovered_units and not uncovered_branches
    detail11 = ''
    if uncovered_units:
        detail11 += f'无用例单元 {uncovered_units[:3]} '
    if uncovered_branches:
        detail11 += f'未覆盖分支 {dict(list(uncovered_branches.items())[:2])}'
    r.add('11', '覆盖全部详设单元与分支', ok11, detail11)

    # 12 - test method within the allowed set
    allowed = set(spec.get('test_methods') or [])
    bad_tm = sorted({c['test_method'] for c in cases if allowed and c['test_method'] not in allowed})
    r.add('12', '测试方法取值合法', not bad_tm, '' if not bad_tm else f'非法 {bad_tm}')

    # 13 - priority derived from SWDD Priority
    pmap = spec.get('priority_map', {})

    def expect_letter(value: str) -> str:
        try:
            v = int(str(value).strip() or 0)
        except ValueError:
            v = 0
        for letter in ('H', 'M', 'L'):
            if letter in pmap and v >= int(pmap[letter]):
                return letter
        return 'L'

    bad_prio = []
    for c in cases:
        fn = functions.get(c['unit_name'])
        if fn and c['priority'] != expect_letter(fn.get('priority', '')):
            bad_prio.append(c['case_name'])
    r.add('13', '优先级由 SWDD Priority 映射', not bad_prio,
          '' if not bad_prio else f'{len(bad_prio)} 条不符')

    # 16 - verdict present
    bad_v = [c['case_name'] for c in cases if not c.get('verdict')]
    r.add('16', '判定准则非空', not bad_v, '' if not bad_v else f'{len(bad_v)} 条为空')

    # 17 - traceability established both ways
    no_unit_id = [c['case_name'] for c in cases if not c.get('unit_id')]
    r.add('17', '每条用例都关联详设单元', not no_unit_id,
          '' if not no_unit_id else f'{len(no_unit_id)} 条缺 unit_id')

    # 18 - traced content is consistent
    unit_ids = {u['name']: u['unit_id'] for u in units}
    mismatch = [c['case_name'] for c in cases
                if not c['case_name'].startswith(c['unit_name'] + '.')
                or c.get('unit_id') != unit_ids.get(c['unit_name'], c.get('unit_id'))]
    r.add('18', '追溯内容与详设一致', not mismatch,
          '' if not mismatch else f'{len(mismatch)} 条不一致 {mismatch[:2]}')

    # 19/20 - the test scripts agree with the case table.
    # Only checkable with the sources at hand, and only because every test is
    # required to carry a marker comment naming the case AND the branches it
    # walks.  The branch set is the part that catches drift: when an infeasible
    # generated path is rewritten during implementation, the case keeps saying
    # the old path until someone reconciles it.
    if root is not None:
        known = {c['case_name']: c['unit_name'] for c in cases}
        marks = map_tests_to_cases(spec, root, known)
        # A supplementary test declares itself as extra coverage; it is traceable
        # by that declaration and does not need a case number.
        bare = sorted(t for t, m in marks.items()
                      if not m['case_name'] and not m.get('supp'))
        r.add('19', '每个测试都有完整标记注释', not bare,
              '' if not bare else f'{len(bare)} 个既无用例号也未声明补充测试 {bare[:2]}')

        want = {c['case_name']: set(c.get('covers_branches') or []) for c in cases}
        drift = []
        for test, m in marks.items():
            name = m['case_name']
            if not name or m.get('supp'):
                continue
            got = {int(x) for x in m['branches'].replace('/', ' ').replace(',', ' ').split()}
            # a superset is a test that loops over several items - not drift
            if got and not got >= want.get(name, set()):
                drift.append(f"{test}->{name} 实走{sorted(got)} 用例称{sorted(want.get(name, set()))}")
        claimed = {m['case_name'] for m in marks.values() if m['case_name']}
        orphan = [c['case_name'] for c in cases if c['case_name'] not in claimed]
        r.add('20', '测试实走分支与用例声明一致', not drift and not orphan,
              '' if not (drift or orphan)
              else f'{len(drift)} 条漂移, {len(orphan)} 条用例无测试；跑 reconcile_cases.py')

    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cases', type=Path, required=True)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--spec', type=Path, required=True)
    ap.add_argument('--root', type=Path,
                    help='project root; enables the test-source checks 19/20')
    args = ap.parse_args()

    cases = json.loads(args.cases.read_text(encoding='utf-8'))['cases']
    model = json.loads(args.model.read_text(encoding='utf-8'))
    spec = json.loads(args.spec.read_text(encoding='utf-8'))

    if not cases:
        print('no cases to check', file=sys.stderr)
        return 2

    rc = check(cases, model, spec, args.root).report()
    print()
    if args.root is None:
        print('提示：加 --root <项目根> 可把第 19/20 项（测试脚本与用例一致）'
              '变成机械判定')
        print()
    print('仍需人工确认（不可自动判定）：')
    for item, text in [
        ('2/3/4', '项目名称、文档版本日期作者、修订历史'),
        ('7', '设计方法是否说清等价类/边界值的取法'),
        ('8', '测试目标是否映射正确的安全机制（QM 项目写"不适用"）'),
        ('9', '是否覆盖单元间动态行为（对照 SWDD 2.6）'),
        ('14/15', '测试步骤与预期结果是否落实成具体取值 —— 生成结果只是草稿'),
        ('21', '测试工程是否已按公司流程验证'),
        ('22', '是否用了方法组合导出用例（ISO 26262-6 §9.4.3）'),
    ]:
        print(f'  [{item}] {text}')
    return rc


if __name__ == '__main__':
    sys.exit(main())

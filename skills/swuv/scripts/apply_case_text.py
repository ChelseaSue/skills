#!/usr/bin/env python3
"""Merge hand-written case text (steps / expected / design method) into cases.json.

gen_cases.py produces draft steps with 【待填具体取值】 placeholders, and
reconcile_cases.py may renumber or rebuild cases.  The concrete values are
therefore authored in a *separate* file keyed by what stays stable across
those steps - the unit name plus the covered branch set - and merged in last:

    {
      "ABBSM_vidMainFunction": {
        "2/4/9/21": {"steps": "1、...;--2\n2、...;--4", "expected": "..."},
        "*": {"design_method": "基于需求分析、等价类、边界值：..."}
      },
      "BBSM_bHasVoltageFault": {"1": {...}, "2": {...}},
      "ABBSM_vidSounderTurnOff": {"whole": {...}}
    }

Keys: branch numbers joined by "/", "whole" for units without decisions,
"*" for unit-wide defaults (applied first, then the path entry on top).
Only the fields present are overwritten.  Cases that receive no text and
cases still carrying the placeholder are listed and make the tool exit 1,
so nothing ships with drafts unnoticed.

    python scripts/apply_case_text.py --cases cases.json --text case_text.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

FIELDS = ('steps', 'expected', 'design_method', 'test_method', 'precondition')


def design_method_error(text: str, allowed: list[str]) -> str | None:
    """The design-method column holds method names only - `基于需求分析、等价类、边界值`.

    How the equivalence classes were chosen belongs in the steps, not here:
    reviewers filter and count this column, and prose in it breaks that.
    """
    t = (text or '').strip()
    body = t[2:] if t.startswith('基于') else t
    parts = [x.strip() for x in re.split(r'[、,，/ ]+', body) if x.strip()]
    if not parts or any(x not in allowed for x in parts):
        return f'设计方法只能由 {"/".join(allowed)} 组成（如 "基于需求分析、等价类"），实际为: {t[:60]}'
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cases', type=Path, required=True)
    ap.add_argument('--text', type=Path, required=True)
    ap.add_argument('--spec', type=Path, help='ut_spec.json; enables the design-method vocabulary check')
    ap.add_argument('--placeholder', default='待填', help='draft marker that must not survive')
    args = ap.parse_args()

    doc = json.loads(args.cases.read_text(encoding='utf-8'))
    text = json.loads(args.text.read_text(encoding='utf-8'))
    missing, applied = [], 0
    for case in doc['cases']:
        unit = text.get(case['unit_name'], {})
        key = '/'.join(str(b) for b in case.get('covers_branches') or []) or 'whole'
        entry = dict(unit.get('*', {}))
        entry.update(unit.get(key, {}))
        if not entry:
            missing.append((case['case_id'], case['case_name'], key))
            continue
        for f in FIELDS:
            if f in entry:
                case[f] = entry[f]
        applied += 1
    args.cases.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{applied}/{len(doc["cases"])} cases updated')
    left = [c for c in doc['cases']
            if args.placeholder in (c.get('steps', '') + c.get('expected', ''))]
    for cid, name, key in missing:
        print(f'  no text for {cid} {name} [{key}]')
    if left:
        print(f'  {len(left)} cases still contain "{args.placeholder}"')
    bad_dm = []
    if args.spec:
        allowed = json.loads(args.spec.read_text(encoding='utf-8')).get('derivation_methods', [])
        for c in doc['cases']:
            err = design_method_error(c.get('design_method', ''), allowed)
            if err:
                bad_dm.append((c['case_name'], err))
                print(f'  {c["case_name"]}: {err}')
    return 1 if (missing or left or bad_dm) else 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Merge Claude-written case text (case_text.json) into cases.json.

case_text.json is keyed by SWIT ID:
  {"SWIT-00001": {"name": "...", "target": "...", "precondition": "...", "steps": "1. ...\\n2. ...",
                  "expected": "...", "criteria": "...", "design_method": "...", "priority": "High",
                  "observed_calls": ["AMSG_vidLinMainFunction", "Com_MainFunctionRx"]}, ...}

A case becomes text_status="filled" only when every text field is present, non-empty and free of
placeholders (【TBD】 / 待填 / TODO). Draft / stale cases block deliverables (see check.py).

Usage: apply_text.py --project swit_project.json [--text ws/cases/case_text.json] [--list-pending]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import Project, load_json, save_json, utf8_console  # noqa: E402

FIELDS = ('name', 'target', 'precondition', 'steps', 'expected', 'criteria', 'design_method')
OPTIONAL = ('priority', 'observed_calls', 'notes')
PLACEHOLDER = re.compile(r'【TBD|待填|TODO|TBD】|\?\?\?')


def apply(reg, text):
    stats = {'filled': 0, 'still_pending': [], 'unknown_ids': []}
    by = {c['id']: c for c in reg['cases']}
    for cid, t in text.items():
        if cid.startswith('_'):
            continue
        c = by.get(cid)
        if c is None:
            stats['unknown_ids'].append(cid)
            continue
        for f in FIELDS + OPTIONAL:
            if f in t and t[f] not in (None, ''):
                c[f] = t[f]
        missing = [f for f in FIELDS if not str(c.get(f, '')).strip() or PLACEHOLDER.search(str(c.get(f, '')))]
        if not missing:   # an entry for a stale case = Claude re-checked it against the changed anchor
            c['text_status'] = 'filled'
            c['text_anchor_hash'] = c.get('anchor_hash')
            stats['filled'] += 1
        else:
            stats['still_pending'].append((cid, missing))
    return stats


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--text', type=Path)
    ap.add_argument('--list-pending', action='store_true', help='print draft/stale cases (ID, anchor) and exit')
    a = ap.parse_args()
    prj = Project(a.project)
    cases_p = prj.wsp('cases', 'cases.json')
    reg = load_json(cases_p)
    if a.list_pending:
        pend = [c for c in reg['cases'] if c['status'] == 'Active' and c.get('text_status') != 'filled']
        for c in pend:
            print(f"{c['id']}  {c['text_status']:6s} {c['category']:11s} {c['execution']:13s} "
                  f"{c.get('anchor_id') or '-':12s} {c['anchor_name'][:70]}")
        print(f'{len(pend)} pending')
        return 0
    text_p = a.text or prj.wsp('cases', 'case_text.json')
    st = apply(reg, load_json(text_p))
    save_json(cases_p, reg)
    print(f"filled {st['filled']}; pending {len(st['still_pending'])}; unknown ids {len(st['unknown_ids'])}")
    for cid, miss in st['still_pending'][:30]:
        print(f'  {cid}: missing/placeholder in {", ".join(miss)}')
    if st['unknown_ids']:
        print('  unknown:', ', '.join(st['unknown_ids'][:20]))
    pend_total = sum(1 for c in reg['cases'] if c['status'] == 'Active' and c.get('text_status') != 'filled')
    print(f'active cases still draft/stale: {pend_total}')
    return 1 if pend_total else 0


if __name__ == '__main__':
    sys.exit(main())

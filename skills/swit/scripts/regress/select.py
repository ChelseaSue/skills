#!/usr/bin/env python3
"""Select regression cases from the PREVIOUS round's test record (AU-QR-R&D-236 or 237 .xlsx).

A case is selected when any of these holds (reasons are recorded per case):
  failed / blocked / skipped / not run in the previous record   (verdict column; NA = SWE.6 transfer is not re-run)
  linked to a defect in the previous record                     (defect-ID column, e.g. fixed defects to confirm)
  linked to a defect in the defects file that is fixed/verified
  impacted by a code change: a changed file belongs to component X  ->  cases of X, interface cases X provides
                             or consumes, and dynamic behaviours owned by / naming X
  priority listed in regression.always_include_priority          (smoke set)

Code changes come from --changed-files, or --svn REV1:REV2 / --git REF1..REF2 run in sources.root.

Writes ws/results/selection_<round>.json {"round","previous","selected","reasons"}; collect.py --selection uses it.

Usage: select.py --project P --previous <236-or-237.xlsx> --round R1
                 [--changed-files a.c b.c | --svn 1200:1234 | --git v1.0..HEAD] [--include SWIT-00012 ...]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / 'docs'))
from common import Project, load_json, save_json, utf8_console  # noqa: E402
import xlsx_util as X  # noqa: E402

VERDICT_KEYS = [('fail', r'(?i)失败|^F$|fail'), ('na', r'(?i)不适用|^NA$|N/A'), ('blocked', r'(?i)阻塞|^B$|block'),
                ('skipped', r'(?i)跳过|^S$|skip'), ('pass', r'(?i)通过|^P$|pass')]


def verdict_of(text: str) -> str:
    t = X.norm(text)
    if not t:
        return 'not_run'
    for key, rx in VERDICT_KEYS:
        if re.search(rx, t):
            return key
    return 'not_run'


def read_record(path: Path):
    wb = openpyxl.load_workbook(path, data_only=True)
    rows = []
    for ws in X.data_sheets(wb):
        hdr = X.find_cell(ws, r'(?i)标识符|identifier|test case id', (1, 8))
        if hdr is None:
            continue
        cols = X.header_cols(ws, {'verdict': r'(?i)判定结果|verdict', 'defect': r'(?i)缺陷\s*id|defect id'},
                            (max(1, hdr.row - 1), hdr.row))
        for r in range(hdr.row + 1, ws.max_row + 1):
            cid = X.norm(ws.cell(r, hdr.column).value)
            if not cid:
                continue
            v = ws.cell(r, cols['verdict']).value if 'verdict' in cols else ''
            d = X.norm(ws.cell(r, cols['defect']).value) if 'defect' in cols else ''
            defects = [x for x in re.split(r'[,;，；\s]+', d) if x and x.upper() not in ('NO', 'NA', 'N/A', '/', '-', 'NONE', '无')]
            rows.append({'id': cid, 'verdict': verdict_of(v), 'defects': defects, 'sheet': ws.title})
    return rows


def changed_files(prj, a):
    if a.changed_files:
        return a.changed_files
    root = prj.resolve(prj.get('sources.root')) or prj.root
    if a.svn:
        r = subprocess.run(['svn', 'diff', '--summarize', '-r', a.svn], cwd=root, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        return [ln.split()[-1] for ln in r.stdout.splitlines() if ln.strip()]
    if a.git:
        r = subprocess.run(['git', 'diff', '--name-only', a.git], cwd=root, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    return []


def components_of(files, prj):
    cdirs = {c: ([d] if isinstance(d, str) else d) for c, d in prj.get('sources.component_dirs', {}).items()}
    hit = set()
    for f in files:
        p = '/' + f.replace('\\', '/').lower().strip('/')
        for c, ds in cdirs.items():
            if any('/' + d.replace('\\', '/').lower().strip('/') + '/' in p for d in ds):
                hit.add(c)
    for pat, comp in (prj.get('regression.change_map') or {}).items():
        if any(re.search(pat, f) for f in files):
            hit.update([comp] if isinstance(comp, str) else comp)
    return hit


def select(prj, prev_rows, model, reg, changed, defects, include, always_prio):
    act = {c['id']: c for c in reg['cases'] if c['status'] == 'Active'}
    reasons = {}

    def add(cid, why):
        if cid in act:
            reasons.setdefault(cid, [])
            if why not in reasons[cid]:
                reasons[cid].append(why)
    unknown = []
    for r in prev_rows:
        if r['id'] not in act:
            unknown.append(r['id'])
            continue
        if act[r['id']]['execution'] == 'swe6':
            continue
        if r['verdict'] in ('fail', 'blocked', 'skipped', 'not_run'):
            add(r['id'], f"previous verdict {r['verdict']}")
        for d in r['defects']:
            add(r['id'], f'defect {d}')
    for d in defects:
        if d.get('status') in ('fixed', 'verified', 'closed'):
            for cid in d.get('cases', []):
                add(cid, f"defect {d['id']} {d['status']}")
    comps = components_of(changed, prj)
    if comps:
        itf_by_name = {i['name']: i for i in model['interfaces']}
        for c in act.values():
            if c['execution'] == 'swe6':
                continue
            if c['component'] in comps:
                add(c['id'], f"code change in {c['component']}")
            if c['category'] == 'interface':
                itf = itf_by_name.get(c['anchor_name'])
                if itf and set(itf['consumers']) & comps:
                    add(c['id'], f"consumer changed ({', '.join(sorted(set(itf['consumers']) & comps))})")
            if c['category'] == 'dynamic':
                txt = c['anchor_name'] + ' ' + c.get('steps', '')
                hit = [x for x in comps if re.search(rf'\b{re.escape(x)}', txt)]
                if hit:
                    add(c['id'], f"behaviour involves changed {', '.join(hit)}")
    for c in act.values():
        if c.get('priority') in always_prio and c['execution'] != 'swe6':
            add(c['id'], f"always-run priority {c['priority']}")
    for cid in include:
        add(cid, 'added by hand')
    sel = sorted(reasons)
    return sel, reasons, unknown, sorted(comps)


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--previous', type=Path, required=True, help='previous round record .xlsx (236 or 237)')
    ap.add_argument('--round', required=True)
    ap.add_argument('--changed-files', nargs='*')
    ap.add_argument('--svn')
    ap.add_argument('--git')
    ap.add_argument('--include', nargs='*', default=[])
    a = ap.parse_args()
    prj = Project(a.project)
    model = load_json(prj.wsp('sad', 'arch_model.json'))
    reg = load_json(prj.wsp('cases', 'cases.json'))
    defects = load_json(prj.resolve(prj.get('defects_file')), default=[]) if prj.get('defects_file') else []
    rows = read_record(a.previous)
    if not rows:
        print(f'error: no case rows found in {a.previous} (expected an Identifiers/标识符 column)', file=sys.stderr)
        return 2
    sel, reasons, unknown, comps = select(prj, rows, model, reg, changed_files(prj, a), defects, a.include,
                                          prj.get('regression.always_include_priority') or [])
    out = {'round': a.round, 'previous': str(a.previous), 'changed_components': comps,
           'selected': sel, 'reasons': reasons, 'unknown_ids_in_previous': unknown}
    save_json(prj.wsp('results', f'selection_{a.round}.json'), out)
    print(f'previous record: {len(rows)} rows; selected {len(sel)} case(s) for {a.round}')
    for cid in sel[:40]:
        print(f"  {cid}  {'; '.join(reasons[cid])}")
    if unknown:
        print(f'  WARN {len(unknown)} IDs in the previous record are not in the case register '
              f'(record not produced from this register?): {", ".join(unknown[:8])}')
    if not sel:
        print('  nothing to re-run: no failed/not-run/defect-linked case and no impacting change')
    return 0


if __name__ == '__main__':
    sys.exit(main())

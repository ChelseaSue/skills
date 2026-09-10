#!/usr/bin/env python3
"""SWE.4-A04 static verification with cppcheck (+ MISRA addon).

Produces the JSON that feeds the "static validation" section of the unit test
report: MISRA findings grouped by obligation level, and the cyclomatic
complexity of every unit measured against the process KPI.

Complexity is taken from the SWDD rather than re-measured: McCabe CCN equals the
number of decisions plus one, and the decisions are already enumerated as
numbered branches in the SWDD flowcharts.  That keeps the report consistent with
the design document by construction and avoids a second, disagreeing measurement.

MISRA rule texts are licensed and are not shipped with cppcheck.  Point
`static.misra_rule_texts` at your licensed copy to get full descriptions;
without it the rule identifiers are still reported, which is enough to classify
mandatory / required / advisory.

Usage:
  python run_static.py --spec ut_spec.json --model swdd_model.json -o static.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# cppcheck --template makes the output trivially parsable and stable across versions.
TEMPLATE = '{file}|{line}|{severity}|{id}|{message}'
MISRA_ID_RE = re.compile(r'misra-c2012-(\d+)\.(\d+)')

# MISRA C:2012 obligation levels.  Only the mandatory set is normative for the
# report's pass criterion; required/advisory are reported with justification.
MANDATORY = {
    (9, 1), (12, 5), (13, 6), (17, 3), (17, 4), (17, 6), (19, 1), (21, 13),
    (21, 17), (21, 18), (21, 19), (21, 20), (22, 2), (22, 4), (22, 5), (22, 6),
}


def find_addon(spec_path: str | None) -> str | None:
    if spec_path and Path(spec_path).is_file():
        return spec_path
    exe = shutil.which('cppcheck')
    if not exe:
        return None
    for base in (Path(exe).resolve().parent.parent, Path(exe).resolve().parent):
        for cand in (base / 'share' / 'cppcheck' / 'addons' / 'misra.py',
                     base / 'addons' / 'misra.py'):
            if cand.is_file():
                return str(cand)
    return None


def run_cppcheck(spec: dict, root: Path) -> tuple[list[dict], str]:
    cfg = spec.get('static', {})
    sources = [str(root / s) for s in spec.get('source_dirs', [])]
    if not sources:
        return [], 'no source_dirs configured'
    if not shutil.which('cppcheck'):
        return [], 'cppcheck not found on PATH'

    cmd = ['cppcheck', '--quiet', '--inline-suppr', f'--template={TEMPLATE}',
           '--enable=style,warning']
    addon = find_addon(cfg.get('misra_addon'))
    if cfg.get('misra', True):
        if not addon:
            return [], 'misra addon (misra.py) not found; set static.misra_addon'
        rule_texts = cfg.get('misra_rule_texts')
        if rule_texts and Path(rule_texts).is_file():
            cmd += [f'--addon={addon}', f'--rule-texts={rule_texts}']
        else:
            cmd += [f'--addon={addon}']
    for inc in spec.get('include_dirs', []):
        cmd += ['-I', str(root / inc)]
    for d in spec.get('defines', []):
        cmd += [f'-D{d}']
    cmd += sources

    proc = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    findings = []
    for line in (proc.stderr or '').splitlines():
        parts = line.split('|')
        if len(parts) < 5:
            continue
        file, ln, severity, rid, message = parts[0], parts[1], parts[2], parts[3], '|'.join(parts[4:])
        m = MISRA_ID_RE.search(rid)
        level = ''
        if m:
            level = 'mandatory' if (int(m.group(1)), int(m.group(2))) in MANDATORY else 'required/advisory'
        findings.append({
            'file': file, 'line': ln, 'severity': severity, 'rule': rid,
            'message': message.strip(), 'misra_level': level,
        })
    return findings, ' '.join(cmd)


def complexity_from_model(model: dict, limit: int) -> tuple[list[dict], int, bool]:
    """McCabe CCN per unit, derived from the SWDD decision count."""
    rows, worst = [], 0
    for fn in model.get('functions', []):
        ccn = int(fn.get('branch_no_expected', 0)) + 1
        worst = max(worst, ccn)
        rows.append({'unit': fn['name'], 'unit_id': fn.get('unit_id', ''),
                     'ccn': ccn, 'ok': ccn <= limit})
    return rows, worst, all(r['ok'] for r in rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', type=Path, required=True)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--root', type=Path, default=Path('.'))
    ap.add_argument('-o', '--out', type=Path)
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text(encoding='utf-8'))
    model = json.loads(args.model.read_text(encoding='utf-8'))
    cfg = spec.get('static', {})
    limit = int(cfg.get('cyclomatic_max', 15))

    findings, cmdline = run_cppcheck(spec, args.root)
    ccn_rows, worst, ccn_ok = complexity_from_model(model, limit)

    mandatory = [f for f in findings if f['misra_level'] == 'mandatory']
    other = [f for f in findings if f['misra_level'] == 'required/advisory']
    non_misra = [f for f in findings if not f['misra_level']]

    result = {
        'tool': f"cppcheck ({cmdline.split()[0] if cmdline else 'not run'})",
        'command': cmdline,
        'object': spec.get('component', ''),
        'cyclomatic_max_found': worst,
        'cyclomatic_limit': limit,
        'cyclomatic_ok': ccn_ok,
        'cyclomatic_rows': ccn_rows,
        'misra_ok': len(mandatory) == 0,
        'misra_summary': f"mandatory({len(mandatory)}) required/advisory({len(other)}) other({len(non_misra)})",
        'summary': (f"cppcheck+MISRA: mandatory={len(mandatory)}, "
                    f"required/advisory={len(other)}, other={len(non_misra)}; "
                    f"max CCN={worst} (limit {limit})"),
        'findings': findings,
    }

    if args.out:
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"wrote {args.out}")

    print(result['summary'])
    if not cmdline or 'not found' in cmdline:
        print(f"note: {cmdline}")
    over = [r for r in ccn_rows if not r['ok']]
    if over:
        print(f"units above the CCN limit: {[(r['unit'], r['ccn']) for r in over]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

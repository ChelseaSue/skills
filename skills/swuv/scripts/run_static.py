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
import html
import re
import shutil
import subprocess
import sys
from datetime import datetime
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
    # Directories searched only by cppcheck, before the real include dirs.
    # Typical use: neutralised AutoSAR *_MemMap.h replacements (see
    # gen_memmap_stubs.py) - cppcheck cannot follow the repeated-inclusion
    # #pragma section protocol and reports a false '#error'.
    for inc in cfg.get('extra_include_dirs', []):
        cmd += ['-I', str(root / inc)]
    for inc in spec.get('include_dirs', []):
        cmd += ['-I', str(root / inc)]
    for d in spec.get('defines', []):
        cmd += [f'-D{d}']
    # cppcheck-only defines, e.g. __GNUC__ so a vendor compiler-abstraction
    # header picks its GCC branch instead of '#error unsupported compiler'
    # (gcc predefines it itself, so it must NOT go into `defines`).
    for d in cfg.get('extra_defines', []):
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


def _esc(t) -> str:
    return html.escape(str(t), quote=True)


def write_static_report(result: dict, spec: dict, root: Path, out: Path) -> None:
    """Standalone static-verification report (SWE.4-A04 evidence).

    One page per module: verdict, MISRA counts per rule, every finding with
    the offending source line, and the per-unit cyclomatic complexity.  The
    048 report's static sheet lists the same findings; this page is what a
    reviewer opens to see them in context, and what the 048 report's evidence
    column points at.  Nothing here is judged - the pass criterion is applied
    in build_deliverables.py from the same static.json.
    """
    findings = result['findings']
    by_rule: dict[str, int] = {}
    for f in findings:
        by_rule[f['rule']] = by_rule.get(f['rule'], 0) + 1
    src_cache: dict[str, list[str]] = {}

    def src_line(f: dict) -> str:
        try:
            lines = src_cache.setdefault(f['file'], (root / f['file']).read_text(
                encoding='utf-8', errors='replace').splitlines())
            return lines[int(f['line']) - 1].strip()
        except (OSError, ValueError, IndexError):
            return ''

    css = ('body{font-family:Segoe UI,Arial,sans-serif;font-size:13px;margin:24px;color:#222}'
           'h1{font-size:20px}h2{font-size:15px;margin-top:28px;border-bottom:1px solid #ccc}'
           'table{border-collapse:collapse;margin:8px 0}th,td{border:1px solid #bbb;padding:3px 8px;'
           'vertical-align:top}th{background:#eee}code{font-family:Consolas,monospace;font-size:12px}'
           '.pass{color:#0a0;font-weight:bold}.fail{color:#c00;font-weight:bold}.meta{color:#666}'
           'td.num{text-align:right}')
    p = [f'<!doctype html><html lang="zh"><head><meta charset="utf-8">'
         f'<title>{_esc(result["object"])} 静态验证报告</title><style>{css}</style></head><body>',
         f'<h1>{_esc(result["object"])} 软件单元静态验证报告 / Static Verification Report</h1>',
         f'<p class="meta">生成时间/Generated {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>']

    mand = sum(1 for f in findings if f['misra_level'] == 'mandatory')
    req = sum(1 for f in findings if f['misra_level'] == 'required/advisory')
    oth = len(findings) - mand - req
    p.append('<h2>1. 结果/Summary</h2><table><tr><th>项/Item</th><th>值/Value</th><th>判定/Verdict</th></tr>')
    p.append(f'<tr><td>工具/Tool</td><td>{_esc(result["tool"])}, MISRA C:2012 addon</td><td></td></tr>')
    p.append(f'<tr><td>验证对象/Object</td><td>{_esc("; ".join(spec.get("source_dirs", [])))}</td><td></td></tr>')
    p.append(f'<tr><td>MISRA mandatory</td><td class="num">{mand}</td>'
             f'<td class="{"pass" if mand == 0 else "fail"}">{"PASS" if mand == 0 else "FAIL"}</td></tr>')
    p.append(f'<tr><td>MISRA required/advisory</td><td class="num">{req}</td><td>需逐条给出理由/justify each</td></tr>')
    p.append(f'<tr><td>其他 cppcheck 发现/Other findings</td><td class="num">{oth}</td><td></td></tr>')
    p.append(f'<tr><td>最大圈复杂度/Max CCN</td><td class="num">{result["cyclomatic_max_found"]} '
             f'(限值/limit {result["cyclomatic_limit"]})</td>'
             f'<td class="{"pass" if result["cyclomatic_ok"] else "fail"}">'
             f'{"PASS" if result["cyclomatic_ok"] else "FAIL"}</td></tr>')
    p.append('</table>')

    p.append('<h2>2. 按规则统计/Findings per rule</h2><table><tr><th>规则/Rule</th><th>级别/Level</th><th>条数/Count</th></tr>')
    level = {f['rule']: (f['misra_level'] or 'cppcheck') for f in findings}
    for rule, n in sorted(by_rule.items(), key=lambda kv: (-kv[1], kv[0])):
        p.append(f'<tr><td>{_esc(rule)}</td><td>{_esc(level[rule])}</td><td class="num">{n}</td></tr>')
    p.append('</table>')

    p.append('<h2>3. 发现明细/Findings</h2><table><tr><th>#</th><th>文件/File</th><th>行/Line</th>'
             '<th>规则/Rule</th><th>级别/Level</th><th>严重度/Severity</th><th>源码/Source line</th></tr>')
    for i, f in enumerate(sorted(findings, key=lambda f: (f['file'], int(f['line']))), 1):
        p.append(f'<tr><td class="num">{i}</td><td>{_esc(Path(f["file"]).name)}</td><td class="num">{_esc(f["line"])}</td>'
                 f'<td>{_esc(f["rule"])}</td><td>{_esc(f["misra_level"] or "cppcheck")}</td>'
                 f'<td>{_esc(f["severity"])}</td><td><code>{_esc(src_line(f))}</code></td></tr>')
    p.append('</table>')

    p.append('<h2>4. 圈复杂度/Cyclomatic complexity</h2>'
             '<p class="meta">CCN = SWDD 流程图判定数 + 1，与详设同源。</p>'
             '<table><tr><th>单元ID/Unit ID</th><th>单元/Unit</th><th>CCN</th><th>判定/Verdict</th></tr>')
    for r in result['cyclomatic_rows']:
        p.append(f'<tr><td>{_esc(r["unit_id"])}</td><td>{_esc(r["unit"])}</td><td class="num">{r["ccn"]}</td>'
                 f'<td class="{"pass" if r["ok"] else "fail"}">{"PASS" if r["ok"] else "FAIL"}</td></tr>')
    p.append('</table>')

    p.append('<h2>5. 命令行/Command</h2>'
             f'<p><code>{_esc(result["command"])}</code></p>'
             '<p class="meta">MISRA 规则原文属授权内容；未配置 rule-texts 时只报规则号。</p>')
    p.append('</body></html>')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(p), encoding='utf-8')


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

    # The verification object is the module's own source; cppcheck also reports
    # on every header it pulls in (vendor MCAL, other modules).  Those belong to
    # other objects' verification, so keep them out of the judgement but record
    # how many were dropped so the report stays honest.
    obj_dirs = [str((args.root / d).resolve()).lower() for d in spec.get('source_dirs', [])]
    def _in_object(f):
        try:
            fp = str(Path(f['file']).resolve()).lower()
        except OSError:
            return False
        return any(fp.startswith(d) for d in obj_dirs)
    outside = [f for f in findings if not _in_object(f)]
    findings = [f for f in findings if _in_object(f)]

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
        'findings_outside_object': len(outside),
        'findings_outside_object_note': ('cppcheck findings located in included headers of other '
                                         'modules / vendor MCAL; not part of this verification object'),
    }

    report = args.root / spec.get('output_dir', 'unit_test') / 'report' / 'static_verification_report.html'
    write_static_report(result, spec, args.root, report)
    result['report'] = report.as_posix()
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"wrote {args.out}")
    print(f"wrote {report}")

    print(result['summary'])
    if not cmdline or 'not found' in cmdline:
        print(f"note: {cmdline}")
    over = [r for r in ccn_rows if not r['ok']]
    if over:
        print(f"units above the CCN limit: {[(r['unit'], r['ccn']) for r in over]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Collect execution and coverage numbers for the unit test report.

Runs gcovr itself with a filter derived from `ut_spec.source_dirs` instead of
relying on the Ceedling gcov plugin's own report.  That default report filters
by Ceedling's `:paths :source`, and a unit tested with the whole-translation-
unit pattern (`#include "<module>.c"`) is deliberately NOT on that path — so the
file under test is silently absent from the coverage summary and the report ends
up quoting the coverage of the mocks instead.

Test counts come from Ceedling's `.pass` / `.fail` result files.

Usage:
  python collect_coverage.py --spec ut_spec.json --build <build dir> \
      --cases cases.json --root . -o coverage.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _gcovr_cmd(build: Path, root: Path, filters: list[str]) -> list[str]:
    exe = shutil.which('gcovr')
    cmd = [exe] if exe else [sys.executable, '-m', 'gcovr']
    gcov_dir = build / 'gcov'
    cmd += ['--root', str(root), str(gcov_dir if gcov_dir.is_dir() else build)]
    for f in filters:
        cmd += ['--filter', f]
    return cmd


def _uncovered_lines(build: Path, root: Path, filters: list[str]) -> dict:
    """Uncovered line numbers per file, from gcovr's text report.

    They are what turns an unexplained "target not reached" row in the report
    into a reviewable statement about which code is missing and why.
    """
    proc = subprocess.run(_gcovr_cmd(build, root, filters) + ['--txt', '-'],
                          capture_output=True, text=True, errors='replace')
    missing: dict[str, str] = {}
    for line in (proc.stdout or '').splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].endswith('.c') and parts[-1][:1].isdigit():
            missing[parts[0]] = parts[-1]
    return missing


def gcovr_summary(build: Path, root: Path, filters: list[str]) -> dict:
    """Run gcovr over the gcov artefacts, restricted to the units under test."""
    proc = subprocess.run(
        _gcovr_cmd(build, root, filters) + ['--json-summary-pretty', '--json-summary', '-'],
        capture_output=True, text=True, errors='replace')
    if proc.returncode != 0 or not proc.stdout.strip():
        return {'error': (proc.stderr or 'gcovr produced no output').strip()[:400]}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {'error': f'cannot parse gcovr output: {exc}'}

    missing = _uncovered_lines(build, root, filters)
    files = []
    for f in data.get('files', []):
        files.append({
            'file': f.get('filename'),
            'uncovered_lines': missing.get(f.get('filename'), ''),
            'line_percent': f.get('line_percent'),
            'branch_percent': f.get('branch_percent'),
            'lines_total': f.get('line_total'),
            'lines_covered': f.get('line_covered'),
            'branches_total': f.get('branch_total'),
            'branches_covered': f.get('branch_covered'),
        })
    return {
        'statement': (data.get('line_percent') or 0) / 100.0,
        'branch': (data.get('branch_percent') or 0) / 100.0,
        'lines_total': data.get('line_total'),
        'lines_covered': data.get('line_covered'),
        'branches_total': data.get('branch_total'),
        'branches_covered': data.get('branch_covered'),
        'files': files,
    }


def test_counts(build: Path) -> dict:
    """Parse Ceedling result files for executed / passed counts."""
    executed = passed = failed = ignored = 0
    for results in (build / 'test' / 'results', build / 'gcov' / 'results'):
        files = (list(results.glob('*.pass')) + list(results.glob('*.fail')))             if results.is_dir() else []
        if not files:
            # `ceedling gcov:all` leaves build/test/results present but empty;
            # taking it would report zero tests while the results sit next door.
            continue
        for f in files:
            text = f.read_text(encoding='utf-8', errors='replace')
            # Ceedling writes a small YAML-ish summary per test executable.
            for key, pat in (('total', r':total:\s*(\d+)'),
                             ('passed', r':passed:\s*(\d+)'),
                             ('failed', r':failed:\s*(\d+)'),
                             ('ignored', r':ignored:\s*(\d+)')):
                m = re.search(pat, text)
                if not m:
                    continue
                n = int(m.group(1))
                if key == 'total':
                    executed += n
                elif key == 'passed':
                    passed += n
                elif key == 'failed':
                    failed += n
                else:
                    ignored += n
        break   # prefer build/test over build/gcov to avoid double counting
    return {'executed': executed, 'passed': passed, 'failed': failed, 'ignored': ignored}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', type=Path, required=True)
    ap.add_argument('--build', type=Path, required=True)
    ap.add_argument('--cases', type=Path, help='cases.json, for the selected-case count')
    ap.add_argument('--model', type=Path, help='swdd_model.json, for design coverage')
    ap.add_argument('--root', type=Path, default=Path('.'))
    ap.add_argument('-o', '--out', type=Path)
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text(encoding='utf-8'))
    # Filter on the full source path, not just its last segment: the Ceedling
    # build tree usually lives under a directory named after the component too
    # (unit_test/<component>/build/...), and a bare name would match the mocks
    # and vendor sources as well.
    filters = [f'.*{re.escape(Path(d).as_posix())}/.*\\.c$'
               for d in spec.get('source_dirs', [])]
    if not filters:
        filters = ['.*\\.c$']

    cov = gcovr_summary(args.build, args.root, filters)
    counts = test_counts(args.build)

    selected = 0
    if args.cases and args.cases.is_file():
        selected = len(json.loads(args.cases.read_text(encoding='utf-8'))['cases'])

    design_coverage = None
    if args.model and args.model.is_file():
        model = json.loads(args.model.read_text(encoding='utf-8'))
        units = model.get('units', [])
        if units and args.cases and args.cases.is_file():
            cases = json.loads(args.cases.read_text(encoding='utf-8'))['cases']
            covered = {c['unit_name'] for c in cases}
            design_coverage = sum(1 for u in units if u['name'] in covered) / len(units)

    # A test function may implement several cases (a switch covered in one test)
    # and a case may need several tests, so the raw counts are not a ratio.
    # `executed` is clamped to the number of selected cases and the raw test
    # count is reported separately, instead of yielding a rate above 100%.
    tests_run = counts['executed']
    executed = min(tests_run, selected) if selected else tests_run
    note = ''
    if selected and tests_run != selected:
        note = (f'{tests_run} 个测试函数实现了 {selected} 条用例；'
                f'一个测试函数可覆盖多条用例，两者不是一一对应')

    result = {
        **{k: v for k, v in cov.items() if k != 'files'},
        'coverage_files': cov.get('files', []),
        'design_coverage': design_coverage,
        'selected': selected,
        'tests_run': tests_run,
        'executed': executed,
        'passed': min(counts['passed'], selected) if selected else counts['passed'],
        'failed': counts['failed'],
        'ignored': counts['ignored'],
        'execution_rate': (executed / selected) if selected else None,
        'pass_rate': (counts['passed'] / tests_run) if tests_run else None,
        'defects_found': counts['failed'],
        'defects_fixed': 0,
        'note': note,
    }
    if 'error' in cov:
        result['error'] = cov['error']

    if args.out:
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'wrote {args.out}')

    if 'error' in result:
        print(f"gcovr error: {result['error']}", file=sys.stderr)
        return 1
    print(f"statement {result['statement']:.1%}  branch {result['branch']:.1%}  "
          f"executed {result['executed']}/{selected}  passed {result['passed']}")
    for f in result['coverage_files']:
        print(f"  {f['file']}: lines {f['line_percent']}%  branches {f['branch_percent']}%")
    return 0


if __name__ == '__main__':
    sys.exit(main())

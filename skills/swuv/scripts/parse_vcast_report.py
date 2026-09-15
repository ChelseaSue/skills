#!/usr/bin/env python3
"""Extract test cases, probe points and metrics from a VectorCAST "Full Report" HTML.

Used when an existing VectorCAST verification has to be compared with (or
migrated to) the swuv deliverables.  The HTML is flattened to text and the
per-test blocks are parsed into:

    name, input (globals / parameters / stub returns), expected, stubbed calls
    in event order, result, and whether the test has expected data at all.

Also collected: the "Probe Points" section (code injected into the unit under
test at runtime - each entry is a branch reached by modifying the UUT rather
than by inputs) and the per-function Statement+Branch metrics.

    python scripts/parse_vcast_report.py <full_report.html> -o vcast.json [--summary]
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


def flatten(path: Path) -> list[str]:
    s = path.read_text(encoding='utf-8', errors='replace')
    s = re.sub(r'<script.*?</script>', '', s, flags=re.S)
    s = re.sub(r'<style.*?</style>', '', s, flags=re.S)
    s = re.sub(r'<[^>]+>', '\n', s)
    s = html.unescape(s)
    return [l.strip() for l in s.split('\n') if l.strip()]


def squash(lines: list[str]) -> str:
    return ' '.join(l for l in lines if l)


def parse(path: Path) -> dict:
    lines = flatten(path)
    n = len(lines)

    # ---- test case blocks -------------------------------------------------
    heads = [i for i, l in enumerate(lines)
             if l == 'Test Case Configuration' and i + 1 < n and lines[i + 1].startswith('Unit Under Test')]
    tests = []
    for k, i in enumerate(heads):
        end = heads[k + 1] - 1 if k + 1 < len(heads) else n
        blk = lines[i:end]
        name = lines[i - 1]
        # Tags become line breaks, so the label and its value may sit on one
        # line ("Subprogram X") or on consecutive lines ("Subprogram", "X").
        subprogram = ''
        for j, l in enumerate(blk[:12]):
            if l.startswith('Unit Under Test') and 'Subprogram' in l:
                subprogram = l.split('Subprogram', 1)[1].strip()
                break
            if l.startswith('Subprogram '):
                subprogram = l.split(' ', 1)[1].strip()
                break
            if l == 'Subprogram' and j + 1 < len(blk):
                subprogram = blk[j + 1].strip()
                break

        def section(start_key: str, end_keys: tuple[str, ...]) -> str:
            try:
                a = next(j for j, l in enumerate(blk) if l.startswith(start_key))
            except StopIteration:
                return ''
            b = next((j for j in range(a + 1, len(blk))
                      if any(blk[j].startswith(e) for e in end_keys)), len(blk))
            return squash(blk[a + 1:b])

        inp = section('Input Test Data', ('Expected Test Data',))
        exp = section('Expected Test Data', ('Test Case / Parameter Input User Code',))
        # "Control Flow" expectations (expected stub call sequence) live in the
        # same block; a test that has them does verify something even when it
        # has no expected *data*.
        control_flow = 'Control Flow' in exp
        user_in = section('Test Case / Parameter Input User Code', ('Test Case / Parameter Expected User Code',))
        stubs = []
        for j, l in enumerate(blk):
            if l.startswith('- Stubbed'):
                rest = l.split('Stubbed', 1)[1].strip()
                stubs.append(rest or (blk[j + 1] if j + 1 < len(blk) else ''))
        result = ''
        for j, l in enumerate(blk):
            if l.startswith('Result -'):
                result = l.split('-', 1)[1].strip() or (blk[j + 1] if j + 1 < len(blk) else '')
                break
        tests.append({
            'name': name,
            'subprogram': subprogram,
            'input': inp,
            'expected': exp,
            'input_user_code': '' if 'no input user code' in user_in else user_in,
            'has_expected_data': not ('no expected data' in exp),
            'has_control_flow': control_flow,
            'stubbed_calls': stubs,
            'result': result,
        })

    # ---- overall results ---------------------------------------------------
    overall = {}
    for key in ('Testcases', 'Expecteds', 'Control Flow', 'Statement Coverage', 'Branch Coverage'):
        try:
            j = lines.index(key)
            overall[key] = lines[j + 1]
        except ValueError:
            pass

    # ---- metrics table (cells arrive one per line) -----------------------
    metrics = []
    try:
        j = lines.index('Branches', lines.index('Complexity')) + 1
        unit = ''
        cov = re.compile(r'^(\d+) / (\d+) \((\d+)%\)$')
        while j + 3 < n and not lines[j].startswith('GRAND TOTALS'):
            if lines[j] == 'TOTALS':               # per-unit subtotal: name, #fn, ccn, st, br
                j += 5
                continue
            if not lines[j + 1].isdigit():          # a unit-name cell precedes the row
                unit = lines[j]
                j += 1
                continue
            m1, m2 = cov.match(lines[j + 2]), cov.match(lines[j + 3])
            if not (m1 and m2):
                break
            metrics.append({'unit': unit, 'subprogram': lines[j], 'complexity': int(lines[j + 1]),
                            'statements': f'{m1.group(1)}/{m1.group(2)}',
                            'branches': f'{m2.group(1)}/{m2.group(2)}'})
            j += 4
    except ValueError:
        pass

    # ---- probe points (cells arrive one per line) --------------------------
    probes = []
    try:
        j = lines.index('Applied probe points')
        j = lines.index('Code After', j) + 1
        cur = None
        while j < n:
            l = lines[j]
            if l in ('Full Report', 'Contents', 'Aggregate Coverage', 'Top'):
                break
            if l.isdigit() and j + 2 < n and not lines[j + 1].isdigit():
                cur = {'id': int(l), 'unit': lines[j + 1], 'function': lines[j + 2], 'text': ''}
                probes.append(cur)
                j += 3
                continue
            if cur is not None:
                cur['text'] += ' ' + l
            j += 1
    except ValueError:
        pass
    for p in probes:
        p['tests'] = re.findall(r'vcast_test_name_equals\("([^"]+)"\)', p['text'])
        p['injected'] = re.findall(r'\{([^{}]*=[^{}]*;)\}', p['text'])
        p['text'] = p['text'].strip()

    return {'source': str(path), 'overall': overall, 'metrics': metrics,
            'tests': tests, 'probe_points': probes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('report', type=Path)
    ap.add_argument('-o', '--out', type=Path)
    ap.add_argument('--summary', action='store_true')
    args = ap.parse_args()

    data = parse(args.report)
    if args.out:
        args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'wrote {args.out}')
    if args.summary or not args.out:
        print('overall:', data['overall'])
        by_fn: dict[str, list] = {}
        for t in data['tests']:
            by_fn.setdefault(t['subprogram'], []).append(t)
        for fn, ts in sorted(by_fn.items()):
            weak = [t['name'] for t in ts if not t['has_expected_data'] and not t['has_control_flow']]
            cf = [t['name'] for t in ts if not t['has_expected_data'] and t['has_control_flow']]
            print(f'{fn:40s} {len(ts):3d} tests'
                  + (f'  (no expectations at all: {", ".join(weak)})' if weak else '')
                  + (f'  (control-flow expectation only: {", ".join(cf)})' if cf else ''))
        if data['probe_points']:
            print(f'{len(data["probe_points"])} probe points (branches reached by injecting code into the UUT):')
            for p in data['probe_points']:
                print(f'  #{p["id"]} {p["function"]}: {"; ".join(p["injected"])}  <- {", ".join(p["tests"])}')
        stub_own = sorted({s for t in data['tests'] for s in t['stubbed_calls']
                           if any(s == m['subprogram'] for m in data['metrics'])})
        if stub_own:
            print('unit-internal functions stubbed in some tests:', ', '.join(stub_own))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

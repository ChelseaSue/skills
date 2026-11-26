#!/usr/bin/env python3
"""Collect one test round: Ceedling results + gcov + call graph + target/manual results -> round JSON.

  per test     Ceedling build/<gcov|test>/results/*.pass|*.fail
  per case     through the /* SWIT: ... */ marker above each test function (never by name):
               all mapped tests pass -> pass; any fails -> fail; only ignored -> not_run;
               no test -> not_run
  coverage     function coverage of the in-scope component files (gcov JSON, union over executables)
               call coverage = executed cross-component call sites / all cross-component call sites,
               call sites from gcc -fcallgraph-info (.ci), execution from gcov per-line call returns.
               Calls into mocks are listed as boundary calls (information, not in the ratio).
               A line with several calls counts as executed only if every call on it returned (ambiguous).
  other cases  execution=target-static : ws/results/target_<round>.json (target/check_resources.py)
               execution=review / manual: ws/results/manual_<round>.json  {"SWIT-x": {"verdict","actual"}}
               execution=swe6           : verdict "na" (transferred to SWE.6)

Usage: collect.py --project P --round 1 [--type first|regression] [--run] [--selection ws/results/selection_R1.json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from common import Project, load_json, save_json, utf8_console  # noqa: E402
from gen_ceedling import MARK_RE, comp_dirs, host_dir, scope_components  # noqa: E402

FUNC_DEF_RE = re.compile(r'^\s*void\s+(test\w*)\s*\(\s*void\s*\)', re.M)
CI_NODE = re.compile(r'node:\s*\{\s*title:\s*"([^"]+)"\s+label:\s*"([^"]*)"')
CI_EDGE = re.compile(r'edge:\s*\{\s*sourcename:\s*"([^"]+)"\s+targetname:\s*"([^"]+)"\s+label:\s*"([^"]+)"')


def norm_path(p: str, base: Path) -> str:
    q = Path(p)
    if not q.is_absolute():
        q = base / q
    try:
        return str(q.resolve()).replace('\\', '/').lower()
    except OSError:
        return str(q).replace('\\', '/').lower()


# --------------------------------------------------------------------------- tests

def test_markers(test_dir: Path):
    """test function -> [case ids]; a marker applies to every test function after it until the next marker."""
    out, unmarked = {}, []
    for f in sorted(test_dir.glob('test_*.c')):
        txt = f.read_text(encoding='utf-8', errors='replace')
        events = [(m.start(), 'mark', [x.strip() for x in m.group(1).split(',') if x.strip()]) for m in MARK_RE.finditer(txt)]
        events += [(m.start(), 'func', m.group(1)) for m in FUNC_DEF_RE.finditer(txt)]
        cur = None
        for _, kind, val in sorted(events, key=lambda e: e[0]):
            if kind == 'mark':
                cur = val
            else:
                key = f'{f.stem}::{val}'
                if cur:
                    out[key] = cur
                else:
                    unmarked.append(key)
    return out, unmarked


def _yaml_tests(text: str):
    res = []
    section = None
    cur = None
    for ln in text.splitlines():
        m = re.match(r'^:(successes|failures|ignores):', ln)
        if m:
            section = m.group(1)
            continue
        if re.match(r'^:\w+:', ln):
            section = None
        if section is None:
            continue
        m = re.match(r'^\s*-\s*:test:\s*(\S+)', ln)
        if m:
            cur = {'test': m.group(1), 'status': {'successes': 'pass', 'failures': 'fail', 'ignores': 'ignored'}[section],
                   'message': ''}
            res.append(cur)
            continue
        m = re.match(r"^\s*:message:\s*'?(.*?)'?\s*$", ln)
        if m and cur is not None:
            cur['message'] = m.group(1)
    return res


def test_results(hd: Path):
    out = {}
    for sub in ('gcov', 'test'):
        rd = hd / 'build' / sub / 'results'
        if not rd.is_dir():
            continue
        for f in rd.glob('*.*'):
            if f.suffix not in ('.pass', '.fail'):
                continue
            for t in _yaml_tests(f.read_text(encoding='utf-8', errors='replace')):
                out.setdefault(f'{f.stem}::{t["test"]}', t)
        if out:
            break
    return out


# --------------------------------------------------------------------------- coverage

def gcov_json(hd: Path, gcov: str):
    data = []
    for gcda in (hd / 'build' / 'gcov' / 'out').rglob('*.gcda'):
        r = subprocess.run([gcov, '--json-format', '--stdout', '--branch-probabilities', str(gcda)],
                           cwd=hd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        for ln in r.stdout.splitlines():
            ln = ln.strip()
            if ln.startswith('{'):
                try:
                    data.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    return data


def call_graph(hd: Path):
    """defs: function -> defining file; globals_: names with external linkage (bare .ci titles)."""
    defs, edges, globals_ = {}, [], set()
    for ci in (hd / 'build' / 'gcov' / 'out').rglob('*.ci'):
        txt = ci.read_text(encoding='utf-8', errors='replace')
        for title, label in CI_NODE.findall(txt):
            parts = label.split('\\n')
            if len(parts) >= 3 and 'bytes' in parts[2]:          # a definition (has a stack-usage line)
                loc = parts[1].rsplit(':', 2)[0]
                name = parts[0]
                defs.setdefault(title, loc)
                defs.setdefault(name, loc)
                if title == name:
                    globals_.add(name)
        for src, dst, label in CI_EDGE.findall(txt):
            f, line, _col = label.rsplit(':', 2)
            edges.append((src, dst, f, int(line)))
    return defs, edges, globals_


def coverage(prj, model, hd: Path):
    comps = scope_components(prj, model)
    cdirs = comp_dirs(prj, comps)
    dir_of = [(norm_path(str(d), hd), c) for c, ds in cdirs.items() for d in ds]
    module = {c['short']: c['module'] for c in model['components']}

    def comp_of(path: str):
        p = norm_path(path, hd)
        for d, c in dir_of:
            if p.startswith(d + '/'):
                return c
        return None

    funcs = {}                       # (file, name) -> count
    line_calls = {}                  # (file, line) -> [returned per call record] (max over executables)
    for d in gcov_json(hd, prj.get('toolchain.gcov', 'gcov')):
        for f in d.get('files', []):
            fp = norm_path(f['file'], hd)
            if comp_of(fp) is None:
                continue
            for fn in f.get('functions', []):
                k = (fp, fn['name'])
                funcs[k] = max(funcs.get(k, 0), fn.get('execution_count', 0))
            for ln in f.get('lines', []):
                if ln.get('calls'):
                    k = (fp, ln['line_number'])
                    rets = [c.get('returned', 0) for c in ln['calls']]
                    old = line_calls.get(k)
                    line_calls[k] = rets if old is None else [max(a, b) for a, b in zip(old, rets)] + old[len(rets):]
    compiled = {ci.stem.lower() for ci in (hd / 'build' / 'gcov' / 'out').rglob('*.ci')}
    untested = []
    for c, ds in cdirs.items():
        for d in ds:
            for src in d.glob('*.c'):
                if src.stem.lower() not in compiled:
                    untested.append(f'{c}/{src.name}')

    defs, edges, globals_ = call_graph(hd)
    sites, boundary = {}, {}
    for src, dst, f, line in edges:
        ca = comp_of(f)
        if ca is None:
            continue
        loc = defs.get(dst, '')
        cb = comp_of(loc) if loc else None
        key = (norm_path(f, hd), line, dst)
        if cb is None:
            if loc and ('/mocks/' in loc.replace('\\', '/') or 'mock_' in loc):
                boundary[key] = {'caller': ca, 'callee': dst, 'file': Path(f).name, 'line': line}
            continue
        if cb == ca:
            continue
        sites[key] = {'caller': ca, 'callee_component': cb, 'callee': dst, 'file': Path(f).name, 'line': line}
    per_line = {}
    for (fp, line, _), s in sites.items():
        per_line.setdefault((fp, line), []).append(s)
    for (fp, line), lst in per_line.items():
        rets = line_calls.get((fp, line), [])
        ambiguous = len(rets) > 1 or len(lst) > 1
        hit = bool(rets) and all(r > 0 for r in rets)
        for s in lst:
            s['executed'] = hit
            s['ambiguous'] = ambiguous
    for (fp, line, _), b in boundary.items():
        rets = line_calls.get((fp, line), [])
        b['executed'] = bool(rets) and all(r > 0 for r in rets)

    objs = {}
    for (fp, name), cnt in funcs.items():
        c = comp_of(fp)
        o = objs.setdefault(module.get(c, c), {'functions_total': 0, 'functions_hit': 0, 'calls_total': 0, 'calls_hit': 0,
                                               'unexecuted_functions': [], 'unexecuted_calls': []})
        o['functions_total'] += 1
        if cnt > 0:
            o['functions_hit'] += 1
        else:
            o['unexecuted_functions'].append(f'{c}:{name}')
    for s in sites.values():
        o = objs.setdefault(module.get(s['caller'], s['caller']), {'functions_total': 0, 'functions_hit': 0, 'calls_total': 0,
                                                                   'calls_hit': 0, 'unexecuted_functions': [], 'unexecuted_calls': []})
        o['calls_total'] += 1
        if s.get('executed'):
            o['calls_hit'] += 1
        else:
            o['unexecuted_calls'].append(f"{s['file']}:{s['line']} {s['caller']}->{s['callee_component']}.{s['callee']}")
    documented = {i['name'] for i in model['interfaces']}
    undocumented = sorted({f'{comp_of(defs[n])}:{n}' for n in globals_
                           if comp_of(defs[n]) and n not in documented and not n.startswith('_')})
    tot = {k: sum(o[k] for o in objs.values()) for k in ('functions_total', 'functions_hit', 'calls_total', 'calls_hit')}
    objects = [dict(name=k, **v) for k, v in sorted(objs.items())]
    for o in objects:
        o['analysis'] = ''
        if o['unexecuted_functions'] or o['unexecuted_calls']:
            o['analysis'] = '; '.join((['not executed: ' + ', '.join(o['unexecuted_functions'][:6])] if o['unexecuted_functions'] else []) +
                                      (['call sites not executed: ' + ', '.join(o['unexecuted_calls'][:4])] if o['unexecuted_calls'] else []))
    return {'objects': objects, 'total': tot, 'call_sites': list(sites.values()),
            'boundary_calls': list(boundary.values()), 'untested_sources': untested,
            'undocumented_public_functions': undocumented}


# --------------------------------------------------------------------------- assemble

def collect(prj, model, reg, rnd_name, rnd_type, selection=None, run=False):
    hd = host_dir(prj)
    if run:
        exe = prj.get('toolchain.ceedling', 'ceedling')
        r = subprocess.run([exe, 'gcov:all'], cwd=hd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                           shell=sys.platform == 'win32')
        (hd / 'build').mkdir(exist_ok=True)
        (hd / 'build' / 'swit_ceedling.log').write_text(r.stdout + r.stderr, encoding='utf-8')
    marks, unmarked = test_markers(hd / 'test')
    tres = test_results(hd)
    by_case = {}
    for test, ids in marks.items():
        for cid in ids:
            by_case.setdefault(cid, []).append(test)
    act = {c['id']: c for c in reg['cases'] if c['status'] == 'Active'}
    if selection is None:
        selection = list(act)
    target = load_json(prj.wsp('results', f'target_{rnd_name}.json'), default={})
    manual = load_json(prj.wsp('results', f'manual_{rnd_name}.json'), default={})
    inscope = {c['short'] for c in scope_components(prj, model)}
    results = {}
    for cid in selection:
        c = act.get(cid)
        if c is None:
            continue
        ex = c['execution']
        if ex == 'swe6':
            results[cid] = {'verdict': 'na', 'actual': '', 'reason': 'transferred to SWE.6'}
            continue
        if cid in manual:
            results[cid] = dict(manual[cid])
            continue
        if ex == 'target-static':
            results[cid] = dict(target.get(cid) or {'verdict': 'not_run', 'reason': 'target artefacts not checked'})
            continue
        if ex == 'review':
            results[cid] = {'verdict': 'not_run', 'reason': 'review result not recorded (manual_<round>.json)'}
            continue
        tests = by_case.get(cid, [])
        if not tests:
            why = 'component not integrated in this round' if c['category'] == 'interface' and c['component'] not in inscope \
                else 'no test implemented'
            results[cid] = {'verdict': 'not_run', 'reason': why}
            continue
        st = [tres.get(t, {'status': 'missing', 'message': 'no result (test not built?)'}) for t in tests]
        if any(s['status'] == 'fail' for s in st):
            v = 'fail'
        elif all(s['status'] == 'pass' for s in st):
            v = 'pass'
        else:
            v = 'not_run'
        msgs = [f"{t.split('::')[1]}: {s['status']}{(' - ' + s['message']) if s.get('message') else ''}" for t, s in zip(tests, st)]
        results[cid] = {'verdict': v, 'actual': ('All checks met: ' if v == 'pass' else '') + '; '.join(msgs),
                        'evidence': ', '.join(tests),
                        'reason': '' if v != 'not_run' else 'test ignored / not built'}
    cov = coverage(prj, model, hd) if (hd / 'build' / 'gcov' / 'out').is_dir() else {}
    prev = load_json(prj.wsp('results', f'round_{rnd_name}.json'), default={})
    for cid, r in results.items():
        old = (prev.get('results') or {}).get(cid, {})
        if old.get('defects'):
            r.setdefault('defects', old['defects'])
    rnd = {'round': rnd_name, 'type': rnd_type, 'date': dt.date.today().isoformat(),
           'software_version': prj.get('project.software_version'), 'tester': prj.get('project.tester'),
           'scope': sorted(inscope), 'selected': [cid for cid in selection if cid in act],
           'results': results, 'coverage': cov, 'environment_difference': prj.get('environment_difference'),
           'unmarked_tests': unmarked, 'unknown_case_ids': sorted(set(by_case) - set(act))}
    save_json(prj.wsp('results', f'round_{rnd_name}.json'), rnd)
    return rnd


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--round', required=True)
    ap.add_argument('--type', choices=['first', 'regression'])
    ap.add_argument('--selection', type=Path)
    ap.add_argument('--run', action='store_true', help='run `ceedling gcov:all` first')
    a = ap.parse_args()
    prj = Project(a.project)
    model = load_json(prj.wsp('sad', 'arch_model.json'))
    reg = load_json(prj.wsp('cases', 'cases.json'))
    typ = a.type or ('regression' if a.round.upper().startswith('R') else 'first')
    sel = load_json(a.selection)['selected'] if a.selection else None
    rnd = collect(prj, model, reg, a.round, typ, sel, a.run)
    v = {}
    for r in rnd['results'].values():
        v[r['verdict']] = v.get(r['verdict'], 0) + 1
    print(f"round {a.round} ({typ}): {len(rnd['selected'])} selected  verdicts {v}")
    t = rnd['coverage'].get('total') if rnd['coverage'] else None
    if t:
        fc = f"{t['functions_hit']}/{t['functions_total']}"
        cc = f"{t['calls_hit']}/{t['calls_total']}"
        print(f"  function coverage {fc}   cross-component call coverage {cc}   "
              f"boundary calls {len(rnd['coverage']['boundary_calls'])}")
        if rnd['coverage'].get('undocumented_public_functions'):
            print(f"  FINDING public functions not in the SAD: {', '.join(rnd['coverage']['undocumented_public_functions'])}")
        if rnd['coverage']['untested_sources']:
            print(f"  in-scope sources not linked in any test: {', '.join(rnd['coverage']['untested_sources'])}")
    if rnd['unmarked_tests']:
        print(f"  WARN tests without SWIT marker: {', '.join(rnd['unmarked_tests'][:10])}")
    if rnd['unknown_case_ids']:
        print(f"  WARN markers naming unknown/obsolete cases: {', '.join(rnd['unknown_case_ids'])}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

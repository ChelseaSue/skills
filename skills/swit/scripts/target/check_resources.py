#!/usr/bin/env python3
"""Static resource check on TARGET build artefacts (no board needed) for execution=target-static cases.

  ROM / RAM per component   GNU ld map: every input-section contribution is classified by its address
                            against the map's "Memory Configuration" regions (flash-like -> ROM,
                            ram/tcm-like -> RAM), then attributed to a component through the object
                            path (sources.component_dirs). Budgets come from the SAD resource anchors
                            ("ROM consumption must not exceed 1300 Byte" lines of each component).
  region usage              used / length per memory region (anchors without a numeric budget are
                            judged against region capacity and say so)
  stack                     max frame per component from gcc -fstack-usage .su files (target.su_dirs);
                            without .su files stack items are "not_run" with the reason

Writes ws/results/target_<round>.json  {"SWIT-x": {"verdict","actual","evidence"}} consumed by collect.py.

Usage: check_resources.py --project P --round 1
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import Project, load_json, save_json, utf8_console  # noqa: E402

REGION_RE = re.compile(r'^(\S+)\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)')
CONTRIB_RE = re.compile(r'^\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)\s+(\S+\.o\S*)\s*$')
INSEC_RE = re.compile(r'^ (\S+)(?:\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)\s+(\S+\.o\S*))?\s*$')
SKIP_OUT = re.compile(r'^\.(debug|comment|ARM\.attributes|stab|group|note)')


def parse_map(path: Path):
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    regions, contribs = [], []
    i = 0
    while i < len(lines) and not lines[i].startswith('Memory Configuration'):
        i += 1
    i += 1
    while i < len(lines) and not lines[i].startswith('Linker script and memory map'):
        m = REGION_RE.match(lines[i])
        if m and m.group(1) not in ('Name', '*default*'):
            regions.append({'name': m.group(1), 'origin': int(m.group(2), 16), 'length': int(m.group(3), 16)})
        i += 1
    out_sec, in_sec = None, None
    for ln in lines[i:]:
        if ln and not ln[0].isspace():
            out_sec = ln.split()[0] if ln.startswith('.') else out_sec
            continue
        if out_sec is None or SKIP_OUT.match(out_sec):
            continue
        m = INSEC_RE.match(ln)
        if m and not ln.startswith('  '):
            in_sec = m.group(1)
            if m.group(4):
                contribs.append((out_sec, in_sec, int(m.group(2), 16), int(m.group(3), 16), m.group(4)))
            continue
        m = CONTRIB_RE.match(ln)
        if m and in_sec:
            contribs.append((out_sec, in_sec, int(m.group(1), 16), int(m.group(2), 16), m.group(3)))
    return regions, contribs


def classify(regions, rom_rx, ram_rx):
    def kind(addr):
        for r in regions:
            if r['origin'] <= addr < r['origin'] + r['length']:
                if re.search(rom_rx, r['name']):
                    return 'ROM', r['name']
                if re.search(ram_rx, r['name']):
                    return 'RAM', r['name']
                return None, r['name']
        return None, None
    return kind


def budgets_of(text):
    out = {}
    for ln in (text or '').splitlines():
        m = re.search(r'(?i)\b(ROM|RAM|flash|stack)\b.*?(\d+(?:\.\d+)?)\s*(k?b(?:yte)?s?)\b', ln)
        if m:
            v = float(m.group(2)) * (1024 if m.group(3).lower().startswith('k') else 1)
            k = {'flash': 'ROM'}.get(m.group(1).lower(), m.group(1).upper())
            out[k] = int(v)
    return out


def stack_frames(dirs, comp_match):
    frames = {}
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for su in d.rglob('*.su'):
            comp = comp_match(str(su))
            for ln in su.read_text(encoding='utf-8', errors='replace').splitlines():
                parts = ln.split('\t')
                if len(parts) >= 2 and parts[1].strip().isdigit() and comp:
                    frames[comp] = max(frames.get(comp, 0), int(parts[1]))
    return frames


def run(prj: Project, rnd: str):
    reg = load_json(prj.wsp('cases', 'cases.json'))
    model = load_json(prj.wsp('sad', 'arch_model.json'))
    mp = prj.resolve(prj.get('target.map_file'))
    out = {}
    cases = [c for c in reg['cases'] if c['status'] == 'Active' and c['execution'] == 'target-static']
    if not mp or not mp.exists():
        for c in cases:
            out[c['id']] = {'verdict': 'not_run', 'reason': 'target.map_file not configured / not found'}
        save_json(prj.wsp('results', f'target_{rnd}.json'), out)
        return out, None
    regions, contribs = parse_map(mp)
    src_root = prj.resolve(prj.get('sources.root'))
    if src_root and src_root.is_dir():
        newest = max((f.stat().st_mtime for f in src_root.rglob('*.c')), default=0)
        if newest > mp.stat().st_mtime:
            print(f'WARN {mp.name} is older than the newest source file: rebuild the target so the map matches '
                  f'the software version under test')
    kind = classify(regions, prj.get('target.rom_region_regex', r'(?i)flash|rom'),
                    prj.get('target.ram_region_regex', r'(?i)ram|tcm|stack|heap|results|shareable|cacheable'))
    cdirs = {c: ([d] if isinstance(d, str) else d) for c, d in prj.get('sources.component_dirs', {}).items()}

    def comp_match(path):
        p = path.replace('\\', '/').lower()
        for c, ds in cdirs.items():
            for d in ds:
                if '/' + d.replace('\\', '/').lower().strip('/') + '/' in p:
                    return c
        return None
    usage, region_used = {}, {}
    for out_sec, in_sec, addr, size, obj in contribs:
        k, rname = kind(addr)
        if rname:
            region_used[rname] = region_used.get(rname, 0) + size
        c = comp_match(obj)
        if c and k:
            usage.setdefault(c, {'ROM': 0, 'RAM': 0})[k] += size
    frames = stack_frames([prj.resolve(d) for d in prj.get('target.su_dirs', [])], comp_match)
    anchors = {a['key']: a for a in model['resource'] + model['performance']}
    short_of = {c['name']: c['short'] for c in model['components']}
    for c in cases:
        a = anchors.get(c['anchor_key'], {})
        lines, ok, judged = [], True, False
        for m in a.get('members', []):
            comp = short_of.get(m['component'], m['component'].split()[0])
            b = budgets_of(m['text'])
            u = usage.get(comp)
            if not b:
                continue
            if u is None:
                u = {'ROM': 0, 'RAM': 0}
                lines.append(f'{comp}: no object in map (header-only / macro component) ->')
            for k in ('ROM', 'RAM'):
                if k in b:
                    judged = True
                    good = u[k] <= b[k]
                    ok &= good
                    lines.append(f"{comp} {k} {u[k]}/{b[k]} B{'' if good else ' EXCEEDED'}")
            if 'STACK' in b:
                if comp in frames:
                    judged = True
                    good = frames[comp] <= b['STACK']
                    ok &= good
                    lines.append(f"{comp} stack(max frame) {frames[comp]}/{b['STACK']} B")
                else:
                    lines.append(f'{comp} stack: no .su data')
        if not a.get('members'):
            for r in regions:
                used = region_used.get(r['name'], 0)
                if used:
                    judged = True
                    good = used <= r['length']
                    ok &= good
                    lines.append(f"{r['name']} {used}/{r['length']} B ({used / r['length']:.1%})")
            if re.search(r'(?i)stack|栈', a.get('name', '')) and not frames:
                judged = False
                lines = ['stack usage needs -fstack-usage (.su) in the target build']
        ev = f'{mp.name}' + (' + .su' if frames else '')
        if judged:
            out[c['id']] = {'verdict': 'pass' if ok else 'fail', 'actual': '; '.join(lines), 'evidence': ev}
        else:
            out[c['id']] = {'verdict': 'not_run', 'reason': '; '.join(lines) or 'no numeric budget / no data', 'evidence': ev}
    save_json(prj.wsp('results', f'target_{rnd}.json'), out)
    return out, {'regions': regions, 'region_used': region_used, 'usage': usage, 'stack': frames}


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--round', required=True)
    a = ap.parse_args()
    prj = Project(a.project)
    res, info = run(prj, a.round)
    for cid, r in res.items():
        print(f"{cid} {r['verdict']:8s} {r.get('actual') or r.get('reason')}")
    if info:
        print('regions: ' + ', '.join(f"{n} {u}B" for n, u in info['region_used'].items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())

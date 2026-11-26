#!/usr/bin/env python3
"""Compare two arch_model.json files anchor by anchor (key + content hash).

Output (JSON + text summary): added / removed / modified anchors per category, and which
deliverables must be re-issued. Used by `swit.py status` to decide between the `execute`
and `sad-change` modes, and to write the revision-log entry of every re-issued document.

Usage: diff.py <baseline_model.json> <new_model.json> [-o diff.json]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import load_json, save_json, utf8_console  # noqa: E402

CATS = ('interfaces', 'dynamic', 'resource', 'performance')


def anchors(model):
    out = {}
    for cat in CATS:
        for a in model.get(cat, []):
            out[a['key']] = (cat, a)
    for c in model.get('components', []):
        k = f"component:{c['id'] or c['short']}"
        out[k] = ('components', {'key': k, 'id': c['id'], 'name': c['name'],
                                 'hash': c['name'] + '|' + ','.join(c.get('uses', []))})
    return out


def diff(base, new):
    a, b = anchors(base), anchors(new)
    res = {'sad_old': base['meta'].get('source'), 'sad_new': new['meta'].get('source'),
           'sha_old': base['meta'].get('sha256'), 'sha_new': new['meta'].get('sha256'),
           'added': [], 'removed': [], 'modified': []}
    for k, (cat, x) in b.items():
        if k not in a:
            res['added'].append({'key': k, 'category': cat, 'id': x.get('id'), 'name': x.get('name')})
        elif a[k][1].get('hash') != x.get('hash'):
            res['modified'].append({'key': k, 'category': cat, 'id': x.get('id'), 'name': x.get('name')})
    for k, (cat, x) in a.items():
        if k not in b:
            res['removed'].append({'key': k, 'category': cat, 'id': x.get('id'), 'name': x.get('name')})
    res['changed'] = bool(res['added'] or res['removed'] or res['modified'])
    return res


def summary_line(d, lang='en'):
    def cnt(lst):
        by = {}
        for x in lst:
            by[x['category']] = by.get(x['category'], 0) + 1
        return ', '.join(f'{k} {v}' for k, v in sorted(by.items())) or '0'
    if lang == 'zh':
        return f"架构变更同步：新增 {cnt(d['added'])}；修改 {cnt(d['modified'])}；删除 {cnt(d['removed'])}"
    return f"Synchronised with SAD change: added {cnt(d['added'])}; modified {cnt(d['modified'])}; removed {cnt(d['removed'])}"


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('baseline', type=Path)
    ap.add_argument('new', type=Path)
    ap.add_argument('-o', '--out', type=Path)
    a = ap.parse_args()
    d = diff(load_json(a.baseline), load_json(a.new))
    if a.out:
        save_json(a.out, d)
    print('SAD changed' if d['changed'] else 'SAD anchors unchanged')
    for k in ('added', 'modified', 'removed'):
        for x in d[k]:
            print(f"  {k:9s} {x['category']:11s} {x['id'] or '-':12s} {x['name']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

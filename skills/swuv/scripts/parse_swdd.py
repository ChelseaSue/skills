#!/usr/bin/env python3
"""Parse a swdd-generator SWDD markdown into a machine-readable unit/branch model.

The SWDD produced by `swdd-generator` is the authoritative input for SWE.4 unit
verification: section 2.4.2 gives the unit inventory (Unit ID / External-Internal
/ ASIL), sections 2.7/2.8 give one attribute table plus one Mermaid flowchart per
unit, and every decision edge in those flowcharts carries a continuous branch
number (`-->|"3) Y"|`).  Those numbers are what a test case's "test target"
column refers to ("covers branch 3"), so they are extracted here as first class
data rather than re-derived from source code.

Nothing in this script is project specific: it keys off the mandatory SWDD
structure only.  Section numbering, unit-id prefix and function naming are all
read from the document.

Usage:
  python parse_swdd.py <swdd.md> [-o model.json]
  python parse_swdd.py <swdd.md> --summary
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# --- Mermaid node / edge syntax -------------------------------------------------
# Node text may be wrapped in [], {}, ([]) and is normally double quoted because
# it contains C expressions.
NODE_RE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*'
    r'(?:\[\(|\(\[|\[|\{)\s*"?(.*?)"?\s*(?:\)\]|\]\)|\]|\})\s*$'
)
# Edge with a numbered label:  Src -->|"12) N"| Dst["..."]
EDGE_LABELLED_RE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*-->\s*\|\s*"([^"]*)"\s*\|\s*'
    r'([A-Za-z_][A-Za-z0-9_]*)'
)
# Plain edge:  Src --> Dst
EDGE_PLAIN_RE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*-->\s*([A-Za-z_][A-Za-z0-9_]*)'
)
BRANCH_LABEL_RE = re.compile(r'^\s*(\d+)\s*\)\s*(.*)$')

MERMAID_BLOCK_RE = re.compile(r'```mermaid\s*\n(.*?)```', re.S)
# Only the External (x.7.n) and Internal (x.8.n) function chapters describe units;
# 1.5.n / 2.5.n share the same heading depth and must not be picked up.
SECTION_RE = re.compile(r'^####\s+(\d+)\.([78])\.(\d+)\s+(\S+)\s*$', re.M)


def _clean(text: str) -> str:
    """Normalise Mermaid node text into a single readable line."""
    return re.sub(r'\s*<br/>\s*', ' ', text or '').strip()


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip('|').split('|')]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(set(c) <= set('-: ') and c for c in cells)


def parse_tables(md: str) -> list[list[list[str]]]:
    """Return every markdown table as a list of rows (header row included)."""
    tables, cur = [], []
    for line in md.splitlines():
        if line.lstrip().startswith('|'):
            cells = _split_row(line)
            if not _is_separator(cells):
                cur.append(cells)
        else:
            if len(cur) > 1:
                tables.append(cur)
            cur = []
    if len(cur) > 1:
        tables.append(cur)
    return tables


def parse_overview(md: str) -> tuple[list[dict], str]:
    """Section 2.4.2 Component Overview Table -> unit inventory."""
    units, component = [], ''
    for tbl in parse_tables(md):
        head = [h.lower() for h in tbl[0]]
        if not any('unit id' in h for h in head):
            continue
        idx = {}
        for i, h in enumerate(head):
            if 'component id' in h:
                idx['component'] = i
            elif 'unit id' in h:
                idx['unit_id'] = i
            elif 'unit name' in h:
                idx['name'] = i
            elif 'external' in h and 'internal' in h:
                idx['scope'] = i
            elif 'description' in h:
                idx['description'] = i
            elif 'asil' in h:
                idx['asil'] = i
        if 'unit_id' not in idx or 'name' not in idx:
            continue
        for row in tbl[1:]:
            if len(row) <= max(idx.values()):
                continue
            name = row[idx['name']].strip()
            if not name:
                continue
            component = component or row[idx.get('component', 0)].strip()
            units.append({
                'unit_id': row[idx['unit_id']].strip(),
                'name': name,
                'scope': row[idx.get('scope', 0)].strip() if 'scope' in idx else '',
                'description': row[idx['description']].strip() if 'description' in idx else '',
                'asil': row[idx['asil']].strip() if 'asil' in idx else '',
            })
        break
    return units, component


def parse_constants(md: str) -> dict:
    """Section 2.5.4 Constant -> {name: value}.

    These are the numbers a test case needs in order to turn a symbolic
    condition such as `value < SOME_THRESHOLD` into the concrete boundary
    inputs the reviewed deliverables use.
    """
    consts: dict[str, str] = {}
    for tbl in parse_tables(md):
        head = [h.lower() for h in tbl[0]]
        if head[:2] != ['name', 'value']:
            continue
        for row in tbl[1:]:
            if len(row) >= 2 and row[0] and row[1]:
                consts[row[0].strip()] = row[1].strip()
    return consts


def parse_enums(md: str) -> dict:
    """Section 2.5.3 Enum -> {member: value}, for equivalence-class inputs."""
    members: dict[str, str] = {}
    for tbl in parse_tables(md):
        head = [h.lower() for h in tbl[0]]
        if not (len(head) >= 3 and 'enum name' in head[0] and 'member' in head[1]):
            continue
        for row in tbl[1:]:
            if len(row) >= 3 and row[1]:
                members[row[1].strip()] = row[2].strip()
    return members


def _attr_table_after(md: str, start: int, end: int) -> dict:
    """First Attribute/Value table inside a section -> dict."""
    chunk = md[start:end]
    for tbl in parse_tables(chunk):
        head = [h.lower() for h in tbl[0]]
        if len(head) >= 2 and head[0].startswith('attribute'):
            return {r[0].strip(): r[1].strip() for r in tbl[1:] if len(r) >= 2}
    return {}


def _param_table_after(md: str, start: int, end: int) -> list[dict]:
    """Parameter table (Name/Type/Direction/Range/...) inside a section."""
    chunk = md[start:end]
    for tbl in parse_tables(chunk):
        head = [h.lower() for h in tbl[0]]
        if head[:3] == ['name', 'type', 'direction']:
            keys = [h.replace(' ', '_') for h in head]
            return [dict(zip(keys, r)) for r in tbl[1:] if len(r) == len(keys)]
    return []


def parse_flowchart(block: str) -> dict:
    """Extract nodes and numbered decision edges from one Mermaid flowchart."""
    nodes: dict[str, str] = {}
    edges: list[dict] = []
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith(('flowchart', 'subgraph', 'end')):
            continue
        m = EDGE_LABELLED_RE.match(line)
        if m:
            src, label, dst = m.group(1), m.group(2), m.group(3)
            bm = BRANCH_LABEL_RE.match(label)
            edges.append({
                'src': src,
                'dst': dst,
                'label': label.strip(),
                'number': int(bm.group(1)) if bm else None,
                'outcome': bm.group(2).strip() if bm else label.strip(),
            })
        elif EDGE_PLAIN_RE.match(line):
            m2 = EDGE_PLAIN_RE.match(line)
            edges.append({'src': m2.group(1), 'dst': m2.group(2),
                          'label': '', 'number': None, 'outcome': ''})
        # A line may both define a node and start an edge; scan for node text too.
        for part in re.split(r'-->(?:\|[^|]*\|)?', line):
            nm = NODE_RE.match(part)
            if nm:
                nodes.setdefault(nm.group(1), _clean(nm.group(2)))
    return {'nodes': nodes, 'edges': edges}


def build_branches(chart: dict) -> list[dict]:
    """Numbered edges -> branch records carrying their decision and effect text."""
    nodes = chart['nodes']
    out = []
    for e in chart['edges']:
        if e['number'] is None:
            continue
        out.append({
            'number': e['number'],
            'outcome': e['outcome'],
            'decision_node': e['src'],
            'decision': nodes.get(e['src'], e['src']),
            'effect': nodes.get(e['dst'], e['dst']),
        })
    out.sort(key=lambda b: b['number'])
    return out


def expected_branch_no(branches: list[dict]) -> int:
    """Branch No as the SWDD template counts it.

    An if/else decision has two outgoing numbered edges but counts as one
    branch; a switch with N cases counts as N.  Grouping the numbered edges by
    their decision node covers both without special-casing the syntax.
    """
    fanout: dict[str, int] = {}
    for b in branches:
        fanout[b['decision_node']] = fanout.get(b['decision_node'], 0) + 1
    return sum(1 if n == 2 else n for n in fanout.values())


def parse(md_path: Path) -> dict:
    md = md_path.read_text(encoding='utf-8')
    units, component = parse_overview(md)
    by_name = {u['name']: u for u in units}

    sections = list(SECTION_RE.finditer(md))
    charts = list(MERMAID_BLOCK_RE.finditer(md))

    functions = []
    for i, sec in enumerate(sections):
        chapter = f"{sec.group(1)}.{sec.group(2)}.{sec.group(3)}"
        fname = sec.group(4)
        start = sec.end()
        end = sections[i + 1].start() if i + 1 < len(sections) else len(md)

        chart = next((c for c in charts if start <= c.start() < end), None)
        parsed = parse_flowchart(chart.group(1)) if chart else {'nodes': {}, 'edges': []}
        branches = build_branches(parsed)

        attrs = _attr_table_after(md, start, end)
        unit = by_name.get(fname, {})
        try:
            declared = int(re.sub(r'\D', '', attrs.get('Branch No', '')) or 0)
        except ValueError:
            declared = 0

        functions.append({
            'chapter': chapter,
            'name': fname,
            'unit_id': unit.get('unit_id', ''),
            'scope': unit.get('scope', 'External' if sec.group(2) == '7' else 'Internal'),
            'asil': unit.get('asil', ''),
            'description': unit.get('description', '') or attrs.get('Function Description', ''),
            'prototype': attrs.get('Prototype', ''),
            'location': attrs.get('Location', ''),
            'complexity': attrs.get('Complexity', ''),
            'importance': attrs.get('Importance', ''),
            'priority': attrs.get('Priority', ''),
            'calls': attrs.get('Calls Func', ''),
            'called_by': attrs.get('Calling Func', ''),
            'constraint': attrs.get('constraint', ''),
            'non_function': attrs.get('Non-function', ''),
            'branch_no_declared': declared,
            'branch_no_expected': expected_branch_no(branches),
            'branch_edges': len(branches),
            'branches': branches,
            # Full topology: path enumeration needs the unnumbered edges too.
            'chart_nodes': parsed['nodes'],
            'chart_edges': parsed['edges'],
            'parameters': _param_table_after(md, start, end),
        })

    return {
        'source': str(md_path),
        'component': component,
        'units': units,
        'constants': parse_constants(md),
        'enums': parse_enums(md),
        'functions': functions,
    }


def summarize(model: dict) -> int:
    """Print a human summary; return non-zero when consistency checks fail."""
    print(f"component      : {model['component']}")
    print(f"units in 2.4.2 : {len(model['units'])}")
    print(f"function chaps : {len(model['functions'])}")
    print()
    print(f"{'chapter':<9}{'unit_id':<18}{'function':<26}{'scope':<10}"
          f"{'decl':>5}{'chart':>5}{'edges':>6}  status")
    bad = 0
    for f in model['functions']:
        ok = f['branch_no_declared'] == f['branch_no_expected']
        flag = '' if ok else '  <-- Branch No disagrees with the flowchart'
        if not ok:
            bad += 1
        print(f"{f['chapter']:<9}{f['unit_id']:<18}{f['name']:<26}{f['scope']:<10}"
              f"{f['branch_no_declared']:>5}{f['branch_no_expected']:>5}"
              f"{f['branch_edges']:>6}{flag}")
    if not any(u['name'] not in {f['name'] for f in model['functions']} for u in model['units']):
        print("\n2.4.2 table and 2.7/2.8 chapters are consistent.")
    else:
        missing = {u['name'] for u in model['units']} - {f['name'] for f in model['functions']}
        print(f"\nunits without a chapter: {sorted(missing)}")
        bad += len(missing)
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('swdd', type=Path, help='SWDD markdown produced by swdd-generator')
    ap.add_argument('-o', '--out', type=Path, help='write the model as JSON')
    ap.add_argument('--summary', action='store_true', help='print a human summary')
    args = ap.parse_args()

    if not args.swdd.is_file():
        print(f"error: not a file: {args.swdd}", file=sys.stderr)
        return 2

    model = parse(args.swdd)
    if args.out:
        args.out.write_text(json.dumps(model, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"wrote {args.out}")
    if args.summary or not args.out:
        return 1 if summarize(model) else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())

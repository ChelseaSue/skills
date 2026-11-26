#!/usr/bin/env python3
"""sad_ir.json + SAD profile rules -> arch_model.json (the architecture anchors).

Anchors (the things SWE.5 tests are traced to):
  modules / components        structure, from the "Software Components" chapter
  interfaces                  component APIs (vertical "Syntax:" tables or horizontal API tables)
  dynamic                     operating/functional modes (state machines) + sequence diagrams
  resource                    resource consumption items
  performance                 performance / timing items

IDs are taken from the SAD verbatim (e.g. SWAD-47666). An anchor without an ID in the SAD
keeps id=null and key "NOID:<slug>" and is reported - IDs are never invented.

Usage:
  model.py --ir ws/sad/sad_ir.json [--project swit_project.json] [--supplement ws/sad/arch_supplement.json]
           -o ws/sad/arch_model.json [--summary] [--list]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ASSETS, Project, content_hash, deep_merge, load_json, norm, save_json, utf8_console  # noqa: E402
import diagrams  # noqa: E402

FUNC_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*\(')
MEASURE_RE = re.compile(r'(≤|<=|<|≥|>=|>|=|not exceed|must not exceed|less than|within|不超过|小于|大于)?\s*'
                        r'(\d+(?:\.\d+)?)\s*(us|µs|μs|ms|s|min|%|kb|kbyte|kbytes|byte|bytes|b|k|mb|hz|khz|mhz)\b', re.I)
TIME_UNITS = {'us', 'µs', 'μs', 'ms', 's', 'min'}


# --------------------------------------------------------------------------- tree

class Node:
    __slots__ = ('num', 'title', 'lvl', 'blocks', 'children', 'parent', 'idx',
                 'id', 'upstream', 'downstream', 'body')

    def __init__(self, num, title, lvl, idx, parent=None):
        self.num, self.title, self.lvl, self.idx, self.parent = num, title, lvl, idx, parent
        self.blocks, self.children = [], []
        self.id, self.upstream, self.downstream, self.body = None, [], [], []

    def ancestors(self):
        n = self.parent
        while n is not None and n.lvl > 0:
            yield n
            n = n.parent

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def label(self):
        return f'{self.num} {self.title}'.strip()


def build_tree(blocks):
    root = Node('', '<root>', 0, -1)
    stack = [root]
    for i, b in enumerate(blocks):
        if b['t'] == 'h':
            while stack[-1].lvl >= b['lvl']:
                stack.pop()
            n = Node(b['num'], b['text'], b['lvl'], i, stack[-1])
            stack[-1].children.append(n)
            stack.append(n)
        else:
            stack[-1].blocks.append(b)
    return root


# --------------------------------------------------------------------------- item meta

def parse_items(root, prof):
    det = prof['item_detection']
    lab = re.compile(det['id_label_regex'])
    idre = re.compile(det['id_regex'])
    up = re.compile(det['upstream_label_regex'], re.I)
    down = re.compile(det['downstream_label_regex'], re.I)
    mode = det.get('mode', 'auto')
    if mode == 'auto':
        has = any(b['t'] == 'tbl' and b['rows'] and b['rows'][0] and lab.match(b['rows'][0][0] or '')
                  for n in root.walk() for b in n.blocks)
        mode = 'id_table' if has else 'heading'
    for n in root.walk():
        body, pending = [], None
        for b in n.blocks:
            if b['t'] == 'tbl' and pending:
                refs = [(r[0], r[1] if len(r) > 1 else '') for r in b['rows'] if r and r[0]]
                (n.upstream if pending == 'up' else n.downstream).extend(refs)
                pending = None
                continue
            pending = None
            if b['t'] == 'p':
                t = norm(b['text'])
                if up.match(t):
                    pending = 'up'
                    continue
                if down.match(t):
                    pending = 'down'
                    continue
                if t in ('Description', '描述') and not b.get('imgs'):
                    continue
            if (mode == 'id_table' and n.id is None and b['t'] == 'tbl' and b['rows'] and b['rows'][0]
                    and lab.match(b['rows'][0][0] or '') and len(b['rows'][0]) > 1):
                cell = norm(b['rows'][0][1])
                m = idre.search(cell)
                n.id = (m.group(0) if m else cell.split(' / ')[0].strip()) or None
                continue
            body.append(b)
        n.body = body
        if n.id is None:
            m = idre.search(n.title)
            if m:
                n.id = m.group(0)
                n.title = norm(idre.sub('', n.title).strip(' -:|'))
    return mode


def body_text(n, deep=False):
    parts = []
    nodes = n.walk() if deep else [n]
    for x in nodes:
        if x is not n:
            parts.append(x.label())
        for b in x.body:
            if b['t'] == 'p':
                parts.append(norm(b['text']))
            elif b['t'] == 'tbl':
                parts.extend(' | '.join(c for c in r if c) for r in b['rows'])
            elif b['t'] == 'code':
                parts.append(f"[{b['lang']} diagram source]")
    return '\n'.join(p for p in parts if p)


def node_imgs(n, deep=False):
    nodes = n.walk() if deep else [n]
    return [i for x in nodes for b in x.body for i in b.get('imgs', [])]


def node_code(n, deep=False):
    nodes = n.walk() if deep else [n]
    return [b for x in nodes for b in x.body if b['t'] == 'code']


def node_hints(n, deep=False):
    nodes = n.walk() if deep else [n]
    return [h for x in nodes for b in x.body for h in b.get('diagram_hints', [])]


def measures(text):
    out = []
    for m in MEASURE_RE.finditer(text or ''):
        unit = m.group(3).lower()
        out.append({'op': (m.group(1) or '').strip(), 'value': float(m.group(2)), 'unit': unit,
                    'timing': unit in TIME_UNITS, 'text': m.group(0).strip()})
    return out


def slug(s):
    return re.sub(r'[^A-Za-z0-9一-鿿]+', '-', s).strip('-')[:48] or 'item'


def short(title, regex):
    m = re.search(regex, title or '')
    return m.group(1) if m else title


def refs_req(refs):
    return [{'id': a, 'name': b} for a, b in refs if not a.lower().startswith('milestone')]


# --------------------------------------------------------------------------- structure

def find_components(root, prof):
    chap_re = re.compile(prof['components_chapter_regex'])
    chapter = next((n for n in root.walk() if n.lvl and chap_re.search(n.title)), None)
    if chapter is None:
        return None, [], []
    mex = re.compile(prof['module_exclude_regex'])
    cex = re.compile(prof['component_exclude_regex'])
    modules, comps = [], []
    for m in chapter.children:
        if mex.search(m.title):
            continue
        mshort = short(m.title, prof['module_short_regex'])
        mod = {'id': m.id, 'name': m.title, 'short': mshort, 'num': m.num, '_node': m}
        modules.append(mod)
        for c in m.children:
            if cex.search(c.title):
                continue
            comps.append({'id': c.id, 'name': c.title, 'short': short(c.title, prof['component_short_regex']),
                          'num': c.num, 'module': mshort, 'module_id': m.id,
                          'upstream': refs_req(c.upstream), 'downstream': [a for a, _ in c.downstream],
                          '_node': c})
    return chapter, modules, comps


def _kv_rows(rows):
    out = {}
    for r in rows:
        if not r or not r[0]:
            continue
        k = norm(r[0]).rstrip(':：')
        out.setdefault(k, []).append(' | '.join(x for x in r[1:] if x and x != '/'))
    return out


def find_interfaces(comps, prof, warnings):
    ip = prof['interface']
    syn = re.compile(ip['syntax_row_regex'])
    hdr = re.compile(ip['api_table_header_regex'])
    exw = re.compile(ip['exclude_within_regex'])
    idre = re.compile(prof['item_detection']['id_regex'])
    out, seen = [], {}
    for c in comps:
        cn = c['_node']
        for n in cn.walk():
            if n is not cn and (exw.search(n.title) or any(exw.search(a.title) for a in n.ancestors()
                                                           if a is not cn and cn in list(a.ancestors()) + [cn])):
                continue
            for b in n.body:
                if b['t'] != 'tbl' or not b['rows']:
                    continue
                rows = b['rows']
                srow = next((r for r in rows if r and syn.match(r[0] or '') and len(r) > 1), None)
                if srow:
                    sig = srow[1]
                    fm = FUNC_RE.search(sig)
                    name = fm.group(1) if fm else re.sub(r'\s+', '', n.title)
                    kv = _kv_rows(rows)
                    _add_if(out, seen, warnings, c, name, sig, n.id if n is not cn else None,
                            n.label(), kv, n.upstream, n.downstream)
                    continue
                head = [norm(x) for x in rows[0]]
                col = next((i for i, h in enumerate(head) if hdr.match(h)), None)
                if col is None:
                    continue
                idcol = next((i for i, h in enumerate(head) if re.match(r'(?i)^(id|编号|接口id|接口编号)$', h)), None)
                for r in rows[1:]:
                    if col >= len(r) or not r[col]:
                        continue
                    fm = FUNC_RE.search(r[col])
                    if not fm:
                        continue
                    iid = None
                    if idcol is not None and idcol < len(r):
                        m = idre.search(r[idcol])
                        iid = m.group(0) if m else None
                    kv = {head[i]: [r[i]] for i in range(min(len(head), len(r))) if head[i]}
                    _add_if(out, seen, warnings, c, fm.group(1), r[col], iid, n.label(), kv, [], [])
    return out


def _add_if(out, seen, warnings, comp, name, sig, iid, where, kv, upstream, downstream):
    key = (comp['short'], name)
    if key in seen:
        warnings.append({'level': 'WARN', 'code': 'DUP-INTERFACE',
                         'msg': f"{comp['short']}.{name} 在 SAD 中出现多次（{seen[key]} / {where}），只保留第一处"})
        return
    seen[key] = where
    out.append({'id': iid, 'name': name, 'signature': norm(sig), 'component': comp['short'],
                'component_id': comp['id'], 'module': comp['module'], 'module_id': comp['module_id'],
                'where': where,
                'description': ' / '.join(kv.get('Description', kv.get('描述', []))),
                'params_in': kv.get('Parameters (in)', kv.get('入参', [])),
                'params_out': kv.get('Parameters (out)', kv.get('出参', [])),
                'returns': ' / '.join(kv.get('Return value', kv.get('返回值', []))),
                'reentrancy': ' / '.join(kv.get('Reentrancy', [])),
                'sync': ' / '.join(kv.get('Sync/Async', [])),
                'upstream': refs_req(upstream), 'downstream': [a for a, _ in downstream],
                'consumers': []})


def find_dependencies(comps, interfaces, prof, aliases=None):
    """Consumer relations from each component's dependency section.

    aliases: {alias: real function} from glue/RTE mapping headers (host/aliases.py); an alias that
    resolves to a documented interface counts as a use of that interface.
    """
    dep_re = re.compile(prof['dependency_section_regex'])
    aliases = aliases or {}
    by_name = {}
    for itf in interfaces:
        by_name.setdefault(itf['name'], []).append(itf)
        by_name.setdefault(itf['name'].lower(), []).append(itf)
    for c in comps:
        used, sigs = [], {}
        for n in c['_node'].walk():
            if not dep_re.search(n.title):
                continue
            for b in n.body:
                if b['t'] == 'tbl':
                    for r in b['rows']:
                        for cell in r[:1]:
                            for fn in FUNC_RE.findall(cell):
                                used.append(fn)
                                sigs.setdefault(fn, cell)
                elif b['t'] == 'p':
                    used += FUNC_RE.findall(b['text'])
        c['uses'] = sorted(set(used))
        c['uses_sig'] = {k: v for k, v in sigs.items() if k in c['uses']}
        c['uses_resolved'] = {}
        ext = []
        for fn in c['uses']:
            real = aliases.get(fn, fn)
            if real != fn:
                c['uses_resolved'][fn] = real
            prov = by_name.get(real) or by_name.get(real.lower())
            if not prov:
                ext.append(fn)
                continue
            for itf in prov:
                if itf['component'] != c['short'] and c['short'] not in itf['consumers']:
                    itf['consumers'].append(c['short'])
        c['uses_external'] = ext


# --------------------------------------------------------------------------- anchors

def transitions_from_tables(n, prof):
    tt = prof['transition_table']
    fr, to, cd = re.compile(tt['from_regex']), re.compile(tt['to_regex']), re.compile(tt['cond_regex'])
    lab = re.compile(tt['label_regex']) if tt.get('label_regex') else None
    out = []
    for x in n.walk():
        for b in x.body:
            if b['t'] != 'tbl' or len(b['rows']) < 2:
                continue
            if lab is not None:
                hits = [(lab.match(r[0]), r) for r in b['rows'] if r and r[0]]
                hits = [(m, r) for m, r in hits if m]
                if hits:
                    for m, r in hits:
                        out.append({'from': m.group(1), 'to': m.group(2),
                                    'label': r[1] if len(r) > 1 else '', 'n': len(out) + 1})
                    continue
            head = [norm(h) for h in b['rows'][0]]
            fi = next((i for i, h in enumerate(head) if fr.search(h)), None)
            ti = next((i for i, h in enumerate(head) if to.search(h)), None)
            if fi is None or ti is None or fi == ti:
                continue
            ci = next((i for i, h in enumerate(head) if cd.search(h) and i not in (fi, ti)), None)
            for r in b['rows'][1:]:
                if max(fi, ti) < len(r) and r[fi] and r[ti]:
                    out.append({'from': r[fi], 'to': r[ti],
                                'label': r[ci] if ci is not None and ci < len(r) else '', 'n': len(out) + 1})
    return out


def find_anchors(root, chapter, modules, prof, extra):
    rules = list(prof['anchors']) + list(extra or [])
    comp_nodes = set()
    if chapter is not None:
        comp_nodes = {id(n) for n in chapter.walk()}
    mod_of = {}
    for m in modules:
        for n in m['_node'].walk():
            mod_of[id(n)] = m
    out, seen = [], set()
    for rule in rules:
        tre = re.compile(rule.get('title_regex', '.*'))
        wre = re.compile(rule['within_regex']) if rule.get('within_regex') else None
        groups = {}
        for n in root.walk():
            if not n.lvl or not tre.search(n.title):
                continue
            if (id(n) in comp_nodes) != bool(rule.get('in_components')):
                continue
            if wre and not any(wre.search(a.title) for a in n.ancestors()):
                continue
            if rule.get('leaf') and n.children:
                continue
            if rule.get('aggregate') == 'module':
                m = mod_of.get(id(n))
                if m is None:
                    continue
                groups.setdefault(m['short'], (m, []))[1].append(n)
                continue
            _emit(out, seen, rule, n, n.id, n.title, [n], prof)
        for mshort, (m, nodes) in groups.items():
            name = rule.get('name', '{module}').format(module=mshort)
            _emit(out, seen, rule, nodes[0], m['id'], name, nodes, prof, aggregate=True)
    return out


def _emit(out, seen, rule, n, aid, name, nodes, prof, aggregate=False):
    cat = rule['category']
    key = f"{cat}:{aid}" if aid else f"{cat}:NOID:{slug(name)}"
    if key in seen:
        return
    seen.add(key)
    deep = not aggregate
    text = '\n'.join(body_text(x, deep=deep) for x in nodes)
    members = []
    if aggregate:
        for x in nodes:
            comp = x.parent.title if x.parent else ''
            members.append({'id': x.id, 'component': comp, 'text': body_text(x),
                            'measures': measures(body_text(x))})
    a = {'key': key, 'id': aid, 'name': name, 'category': cat, 'kind': rule.get('kind', cat),
         'num': n.num if not aggregate else '', 'where': [x.label() for x in nodes],
         'text': text, 'measures': measures(text), 'members': members,
         'upstream': refs_req(sum((x.upstream for x in nodes), [])),
         'downstream': sorted({r for x in nodes for r, _ in x.downstream}),
         'images': [i for x in nodes for i in node_imgs(x, deep=deep)],
         'diagram_hints': [h for x in nodes for h in node_hints(x, deep=deep)],
         'diagrams': [], 'transitions': []}
    if cat == 'dynamic':
        for b in (c for x in nodes for c in node_code(x, deep=True)):
            d = diagrams.parse(b['lang'], b['text'])
            d['origin'] = f"{b['lang']}-source"
            a['diagrams'].append(d)
        for x in nodes:
            a['transitions'] += transitions_from_tables(x, prof)
    out.append(a)


# --------------------------------------------------------------------------- assembly

def load_profile(project: Project | None):
    name = (project.get('sad.profile') if project else None) or 'aspice_sad'
    p = Path(name)
    if not p.suffix:
        p = ASSETS / 'sad_profiles' / f'{name}.json'
    elif project and not p.is_absolute():
        p = project.resolve(name)
    prof = load_json(p)
    if project:
        prof = deep_merge(prof, project.get('sad.profile_overrides') or {})
    return prof


def merge_supplement(model, supp):
    """Claude's transcription of diagram images (arch_supplement.json), keyed by anchor id/key."""
    if not supp:
        return
    by = {}
    for a in model['dynamic']:
        by[a['key']] = a
        if a['id']:
            by[a['id']] = a
    for k, entry in supp.get('diagrams', {}).items():
        a = by.get(k)
        if a is None:
            model['warnings'].append({'level': 'WARN', 'code': 'SUPPLEMENT-ORPHAN',
                                      'msg': f'arch_supplement 条目 {k} 找不到对应动态行为锚点'})
            continue
        for d in entry if isinstance(entry, list) else [entry]:
            d = dict(d)
            d['origin'] = 'image-transcription'
            a['diagrams'].append(d)


def build(ir, prof, extra_anchors=None, supplement=None, aliases=None):
    root = build_tree(ir['blocks'])
    mode = parse_items(root, prof)
    warnings = []
    chapter, modules, comps = find_components(root, prof)
    if chapter is None:
        warnings.append({'level': 'FAIL', 'code': 'NO-COMPONENT-CHAPTER',
                         'msg': '未找到软件组件章节（components_chapter_regex），无法得到组件与接口'})
    interfaces = find_interfaces(comps, prof, warnings)
    find_dependencies(comps, interfaces, prof, aliases)
    anchors = find_anchors(root, chapter, modules, prof, extra_anchors)

    reqs = {}
    for n in root.walk():
        for a, b in n.upstream:
            if not a.lower().startswith('milestone'):
                reqs.setdefault(a, b)

    model = {
        'meta': {'source': ir['source'], 'sha256': ir['sha256'], 'format': ir['format'], 'item_mode': mode,
                 'aliases_used': len(aliases or {})},
        'modules': [{k: v for k, v in m.items() if not k.startswith('_')} for m in modules],
        'components': [{k: v for k, v in c.items() if not k.startswith('_')} for c in comps],
        'interfaces': interfaces,
        'dynamic': [a for a in anchors if a['category'] == 'dynamic'],
        'resource': [a for a in anchors if a['category'] == 'resource'],
        'performance': [a for a in anchors if a['category'] == 'performance'],
        'requirements': reqs,
        'warnings': warnings,
    }
    merge_supplement(model, supplement)
    for itf in interfaces:
        itf['key'] = f"interface:{itf['id']}" if itf['id'] else f"interface:NOID:{itf['component']}.{itf['name']}"
        itf['category'] = 'interface'
        itf['hash'] = content_hash({k: itf[k] for k in ('name', 'signature', 'description', 'params_in',
                                                         'params_out', 'returns', 'consumers')})
    for cat in ('dynamic', 'resource', 'performance'):
        for a in model[cat]:
            a['hash'] = content_hash({'name': a['name'], 'text': a['text'], 'diagrams': a['diagrams'],
                                      'transitions': a['transitions']})
    check(model)
    return model


def check(model):
    w = model['warnings']
    for m in model['modules']:
        if not m['id']:
            w.append({'level': 'WARN', 'code': 'NO-ID', 'msg': f"模块 {m['name']} 在 SAD 中没有 ID"})
    for c in model['components']:
        if not c['id']:
            w.append({'level': 'WARN', 'code': 'NO-ID', 'msg': f"组件 {c['name']} 在 SAD 中没有 ID"})
    for itf in model['interfaces']:
        if not itf['id']:
            w.append({'level': 'WARN', 'code': 'NO-ID', 'msg': f"接口 {itf['component']}.{itf['name']} 没有 ID"})
    for cat in ('dynamic', 'resource', 'performance'):
        for a in model[cat]:
            if not a['id']:
                w.append({'level': 'WARN', 'code': 'NO-ID', 'msg': f"{cat} 锚点「{a['name']}」没有 ID"})
    names = {}
    for itf in model['interfaces']:
        names.setdefault(itf['name'].lower(), set()).add(itf['name'])
    for variants in names.values():
        if len(variants) > 1:
            w.append({'level': 'WARN', 'code': 'NAME-CASE', 'msg': f"同一接口多种写法：{' / '.join(sorted(variants))}"})
    for a in model['dynamic']:
        has_src = any(d.get('origin', '').endswith('-source') for d in a['diagrams'])
        has_tr = any(d.get('origin') == 'image-transcription' for d in a['diagrams'])
        if a['images'] and not has_src and not has_tr and not a['transitions']:
            w.append({'level': 'TODO', 'code': 'IMAGE-ONLY',
                      'msg': f"动态行为「{a['name']}」只有图片（{len(a['images'])} 张）没有图源码：请 Claude 读图转写到 "
                             f"arch_supplement.json，并建议上游 SAD 附带 PlantUML/Mermaid 源码"})
        if not a['images'] and not a['diagrams'] and not a['transitions']:
            w.append({'level': 'WARN', 'code': 'NO-DIAGRAM', 'msg': f"动态行为「{a['name']}」既无图也无转移表，仅能按文字派生用例"})
    for a in model['dynamic']:
        for d in a['diagrams']:
            if d.get('origin') == 'image-transcription' and not d.get('verified'):
                w.append({'level': 'TODO', 'code': 'UNVERIFIED',
                          'msg': f"动态行为「{a['name']}」的读图转写尚未人工确认（verified=false）"})
                break


def summary(model, listing=False):
    lines = [f"SAD: {Path(model['meta']['source']).name}  (item mode: {model['meta']['item_mode']})",
             f"  modules      {len(model['modules']):4d}  {', '.join(m['short'] for m in model['modules'])}",
             f"  components   {len(model['components']):4d}",
             f"  interfaces   {len(model['interfaces']):4d}",
             f"  dynamic      {len(model['dynamic']):4d}",
             f"  resource     {len(model['resource']):4d}",
             f"  performance  {len(model['performance']):4d}",
             f"  requirements {len(model['requirements']):4d} (upstream refs)"]
    if listing:
        for c in model['components']:
            n = sum(1 for i in model['interfaces'] if i['component'] == c['short'])
            lines.append(f"    [{c['module']}] {c['id'] or 'NO-ID'} {c['name']}  interfaces={n}  "
                         f"uses={len(c.get('uses', []))} external={len(c.get('uses_external', []))}")
        for cat in ('dynamic', 'resource', 'performance'):
            for a in model[cat]:
                dg = ','.join(d.get('origin', '?') for d in a['diagrams']) or '-'
                lines.append(f"    {cat:11s} {a['id'] or 'NO-ID':12s} {a['name'][:60]:60s} imgs={len(a['images'])} "
                             f"diag={dg} trans={len(a['transitions'])}")
    by = {}
    for w in model['warnings']:
        by.setdefault((w['level'], w['code']), []).append(w['msg'])
    for (lvl, code), msgs in sorted(by.items()):
        lines.append(f"  {lvl:5s} {code:18s} x{len(msgs)}")
        for m in msgs[: (len(msgs) if listing else 3)]:
            lines.append(f"        - {m}")
        if not listing and len(msgs) > 3:
            lines.append(f"        ... (+{len(msgs) - 3}, --list 查看全部)")
    return '\n'.join(lines)


def project_aliases(project):
    """Scan the project's source/include dirs for #define alias mappings (RTE/glue headers)."""
    root = project.resolve(project.get('sources.root'))
    if not root or not root.is_dir():
        return {}
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'host'))
    import aliases as _al
    dirs = [root] + [project.resolve(d) if Path(d).is_absolute() else root / d
                     for d in project.get('sources.include_dirs', [])]
    return _al.scan(dirs)


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ir', type=Path, required=True)
    ap.add_argument('--project', type=Path)
    ap.add_argument('--supplement', type=Path)
    ap.add_argument('-o', '--out', type=Path, required=True)
    ap.add_argument('--summary', action='store_true')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    project = Project(a.project) if a.project else None
    prof = load_profile(project)
    supp = load_json(a.supplement) if a.supplement and a.supplement.exists() else None
    aliases = project_aliases(project) if project else {}
    model = build(load_json(a.ir), prof, project.get('sad.extra_anchors') if project else None, supp, aliases)
    save_json(a.out, model)
    if a.summary or a.list:
        print(summary(model, a.list))
    fails = [w for w in model['warnings'] if w['level'] == 'FAIL']
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Fill a company Word template (strategy AU-QR-R&D-050, guide AU-QW-R&D-56) from a content JSON.

Content JSON (ws/docs/<what>_content.json, drafted by draft_docs.py, reviewed/extended by Claude):
  {"what": "strategy",
   "placeholders": {"ＸＸＸＸＸ": "BBS_P519_V436", "XXXX": "BBS_P519_V436"},
   "sections": [
     {"match": "(?i)^目的|purpose", "nth": 0,
      "blocks": [
        {"p": "paragraph text"},
        {"bullets": ["item", "item"]},
        {"fill_table": 0, "rows": [["1", "DRV", "..."]], "header_rows": 1},      # reuse the n-th table of the section
        {"set_column": 0, "col": 6, "values": {"(?i)interface": "是 Yes"}, "match_col": 1},  # edit cells in a kept table
        {"table": {"header": ["No.", "Name"], "rows": [["1", "x"]]}, "caption": "..."},  # new table
        {"image": "path.png", "width_cm": 15}]}]}

For every matched heading the section body (everything up to the next heading) is replaced:
template sample/instruction paragraphs are removed, the template's tables are reused when a block
refers to them (header rows and table style kept, data rows rebuilt), captions in front of kept
tables stay. Sections not listed keep the template text; remaining 【样本示例/【填写说明 markers are
reported (check.py blocks release while they or 【TBD】 remain).

Usage: build_docx.py --project P --what strategy|guide [--content ws/docs/strategy_content.json] [--change "..."]
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import re
import sys
from pathlib import Path

import docx
from docx.shared import Cm
from docx.table import Table
from docx.text.paragraph import Paragraph

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from common import Project, load_json, utf8_console  # noqa: E402
from convert import convert  # noqa: E402

HEAD_STYLE = re.compile(r'(?i)heading\s*(\d)|标题\s*(\d)|标题(\d)')
MARKERS = re.compile(r'【(样本示例|填写说明)[^】]*】')
W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def heading_level(p: Paragraph) -> int:
    name = p.style.name if p.style is not None else ''
    m = HEAD_STYLE.search(name)
    if m:
        return int(next(g for g in m.groups() if g))
    return 0


def clean_title(t: str) -> str:
    return re.sub(r'^\s*[\d.]+\s*', '', t or '').strip()


def body_elements(doc):
    return list(doc.element.body.iterchildren())


def find_headings(doc):
    out = []
    for el in body_elements(doc):
        if el.tag == W_NS + 'p':
            p = Paragraph(el, doc)
            lvl = heading_level(p)
            if lvl and p.text.strip():
                out.append((el, lvl, clean_title(p.text)))
    return out


def section_body(doc, head_el):
    """Elements after head_el up to the next heading paragraph (any level) or sectPr."""
    out = []
    el = head_el.getnext()
    while el is not None:
        if el.tag == W_NS + 'sectPr':
            break
        if el.tag == W_NS + 'p' and heading_level(Paragraph(el, doc)):
            break
        out.append(el)
        el = el.getnext()
    return out


def body_style(doc, body):
    for el in body:
        if el.tag == W_NS + 'p':
            p = Paragraph(el, doc)
            nm = p.style.name if p.style is not None else ''
            if p.text.strip() and not re.search(r'(?i)caption|题注|toc|list', nm) and not MARKERS.search(p.text):
                return p.style
    for cand in ('HR正文', 'Body Text', 'Normal'):
        try:
            return doc.styles[cand]
        except KeyError:
            continue
    return None


def make_par(doc, text, style, anchor_el):
    p = doc.add_paragraph(text)
    if style is not None:
        p.style = style
    anchor_el.addnext(p._p)
    return p._p


def _set_cell(cell, text):
    text = '' if text is None else str(text)
    paras = cell.paragraphs
    first = paras[0]
    for r in first.runs[1:]:
        r._r.getparent().remove(r._r)
    if first.runs:
        first.runs[0].text = text
    else:
        first.add_run(text)
    for extra in paras[1:]:
        extra._p.getparent().remove(extra._p)


def fill_table(tbl: Table, rows, header_rows=1):
    data_rows = list(tbl.rows)[header_rows:]
    proto = copy.deepcopy((data_rows[0] if data_rows else tbl.rows[-1])._tr)
    for r in data_rows:
        tbl._tbl.remove(r._tr)
    for vals in rows:
        tr = copy.deepcopy(proto)
        tbl._tbl.append(tr)
        row = tbl.rows[-1]
        cells, prev = [], None
        for c in row.cells:
            if c._tc is prev:
                continue
            prev = c._tc
            cells.append(c)
        for i, c in enumerate(cells):
            _set_cell(c, vals[i] if i < len(vals) else '')


def set_column(tbl: Table, col, values: dict, match_col=0, header_rows=1):
    for row in list(tbl.rows)[header_rows:]:
        cells = row.cells
        key = ' '.join(cells[i].text for i in range(min(len(cells), match_col + 1)))
        for rx, v in values.items():
            if re.search(rx, key):
                if col < len(cells):
                    _set_cell(cells[col], v)
                break


def new_table(doc, header, rows, anchor_el):
    t = doc.add_table(rows=1, cols=len(header))
    for style in ('Table Grid', '网格型', 'TableGrid'):
        try:
            t.style = doc.styles[style]
            break
        except KeyError:
            continue
    for i, h in enumerate(header):
        _set_cell(t.rows[0].cells[i], h)
    for vals in rows:
        cells = t.add_row().cells
        for i, v in enumerate(vals[:len(header)]):
            _set_cell(cells[i], v)
    anchor_el.addnext(t._tbl)
    return t._tbl


def apply_section(doc, head_el, spec, base_dir: Path):
    body = section_body(doc, head_el)
    style = body_style(doc, body)
    tables = [el for el in body if el.tag == W_NS + 'tbl']
    keep_idx = {b['fill_table'] for b in spec['blocks'] if 'fill_table' in b} | \
               {b['set_column'] for b in spec['blocks'] if 'set_column' in b}
    keep = {id(tables[i]) for i in keep_idx if i < len(tables)}
    # captions directly in front of kept tables stay attached to them
    captions = {}
    for i, el in enumerate(body):
        if el.tag == W_NS + 'tbl' and id(el) in keep and i > 0 and body[i - 1].tag == W_NS + 'p':
            prev = Paragraph(body[i - 1], doc)
            if re.search(r'(?i)caption|题注', prev.style.name if prev.style is not None else '') or re.match(r'^表\s*\d', prev.text.strip()):
                captions[id(el)] = body[i - 1]
    for el in body:
        if id(el) in keep or any(el is c for c in captions.values()):
            continue
        if el.tag == W_NS + 'p' and el.xpath('.//w:sectPr'):
            continue
        el.getparent().remove(el)
    anchor = head_el
    for b in spec['blocks']:
        if 'p' in b:
            anchor = make_par(doc, b['p'], style, anchor)
        elif 'bullets' in b:
            for it in b['bullets']:
                anchor = make_par(doc, f'• {it}', style, anchor)
        elif 'fill_table' in b or 'set_column' in b:
            i = b.get('fill_table', b.get('set_column'))
            if i >= len(tables):
                anchor = make_par(doc, f'【TBD-模板中缺少第 {i + 1} 张表】', style, anchor)
                continue
            el = tables[i]
            cap = captions.get(id(el))
            if cap is not None:
                anchor.addnext(cap)
                anchor = cap
            anchor.addnext(el)
            anchor = el
            t = Table(el, doc)
            if 'fill_table' in b:
                fill_table(t, b['rows'], b.get('header_rows', 1))
            else:
                set_column(t, b['col'], b['values'], b.get('match_col', 0), b.get('header_rows', 1))
        elif 'table' in b:
            if b.get('caption'):
                anchor = make_par(doc, b['caption'], style, anchor)
            anchor = new_table(doc, b['table']['header'], b['table']['rows'], anchor)
            anchor = make_par(doc, '', style, anchor)
        elif 'image' in b:
            ip = Path(b['image'])
            ip = ip if ip.is_absolute() else base_dir / ip
            if ip.exists():
                p = doc.add_paragraph()
                p.add_run().add_picture(str(ip), width=Cm(b.get('width_cm', 15)))
                anchor.addnext(p._p)
                anchor = p._p
            else:
                anchor = make_par(doc, f'【TBD-图片缺失 {ip.name}】', style, anchor)


def replace_placeholders(doc, mapping: dict):
    if not mapping:
        return

    def fix_par(p):
        if not any(k in p.text for k in mapping):
            return
        txt = p.text
        for k, v in mapping.items():
            txt = txt.replace(k, v)
        if p.runs:
            p.runs[0].text = txt
            for r in p.runs[1:]:
                r.text = ''
    for p in doc.paragraphs:
        fix_par(p)
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    fix_par(p)


def append_revision(doc, version, change, author, date):
    for t in doc.tables:
        hdr = ' '.join(c.text for c in t.rows[0].cells) if t.rows else ''
        if re.search(r'(?i)版本.*修订|version/revision', hdr) and re.search(r'(?i)修改内容|change content', hdr):
            cols = [c.text for c in t.rows[0].cells]

            def ci(rx):
                return next((i for i, h in enumerate(cols) if re.search(rx, h)), None)
            idx = {'no': ci(r'(?i)序号|no\.'), 'ver': ci(r'(?i)版本|version'), 'chg': ci(r'(?i)修改内容|change'),
                   'who': ci(r'(?i)修改人|modifier'), 'date': ci(r'(?i)日期|date')}
            for n, row in enumerate(list(t.rows)[1:], 1):
                if not any(row.cells[i].text.strip() for i in (idx['ver'], idx['chg']) if i is not None):
                    vals = {'no': str(n), 'ver': version, 'chg': change, 'who': author, 'date': date}
                    for k, i in idx.items():
                        if i is not None:
                            _set_cell(row.cells[i], vals[k])
                    return True
            return False
    return False


def last_version(doc):
    for t in doc.tables:
        hdr = ' '.join(c.text for c in t.rows[0].cells) if t.rows else ''
        if re.search(r'(?i)版本.*修订|version/revision', hdr):
            vers = [r.cells[1].text.strip() for r in list(t.rows)[1:] if len(r.cells) > 1 and r.cells[1].text.strip()]
            return vers[-1] if vers else None
    return None


def build(prj: Project, what: str, content: dict, change: str):
    key = {'strategy': 'strategy', 'guide': 'guide'}[what]
    name = prj.get(f'output.names.{key}').format(project=prj.get('project.name') or 'PROJECT', round='')
    out_dir = prj.resolve(prj.get('output.dir')) if prj.get('output.dir') else prj.wsp('out')
    out = out_dir / name
    reused = out.exists()
    src = out if reused else prj.template(key)
    if src.suffix.lower() == '.doc':
        src = convert(src, prj.wsp('templates'))
    doc = docx.Document(str(src))
    heads = find_headings(doc)
    missing = []
    for spec in content.get('sections', []):
        rx = re.compile(spec['match'])
        hits = [h for h in heads if rx.search(h[2])]
        nth = spec.get('nth', 0)
        if nth >= len(hits):
            missing.append(spec['match'])
            continue
        apply_section(doc, hits[nth][0], spec, prj.wsp('docs'))
    replace_placeholders(doc, content.get('placeholders', {}))
    prev = last_version(doc) if reused else None
    m = re.search(r'(\d+)\.(\d+)', prev or '')
    ver = f'V{m.group(1)}.{int(m.group(2)) + 1}' if m else 'V0.1'
    append_revision(doc, ver, change, prj.get('project.author', ''), dt.date.today().isoformat())
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    left = []
    for p in docx.Document(str(out)).paragraphs:
        if MARKERS.search(p.text) or '【TBD' in p.text:
            left.append(p.text.strip()[:80])
    return out, ver, missing, left


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--what', required=True, choices=['strategy', 'guide'])
    ap.add_argument('--content', type=Path)
    ap.add_argument('--change', default='')
    a = ap.parse_args()
    prj = Project(a.project)
    content = load_json(a.content or prj.wsp('docs', f'{a.what}_content.json'))
    out, ver, missing, left = build(prj, a.what, content,
                                    a.change or prj.text('按软件架构生成/更新', 'Generated / updated from the software architecture'))
    print(f'{a.what}: {out} ({ver})')
    for m in missing:
        print(f'  WARN no heading matches {m}')
    if left:
        print(f'  {len(left)} paragraph(s) still carry 【TBD】 / template markers, e.g.:')
        for t in left[:12]:
            print(f'    {t}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

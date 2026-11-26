#!/usr/bin/env python3
"""SAD (.docx / .md) -> sad_ir.json : a flat, ordered list of blocks.

Block kinds
  {"t":"h",   "lvl":4, "num":"9.1.1", "text":"DADC Component"}
  {"t":"p",   "text":"...", "style":"Normal", "imgs":["images/img_003.png"]}
  {"t":"tbl", "rows":[["SWAD_ID:","SWAD-47660"], ...], "imgs":[...]}
  {"t":"code","lang":"plantuml"|"mermaid", "text":"@startuml ..."}

Diagram source is preferred over images: PlantUML (@startuml..@enduml) and Mermaid
(```mermaid fences, or a paragraph run starting with a mermaid keyword) are lifted out of
plain paragraphs into "code" blocks so the model builder can parse them mechanically.
Images are exported next to the IR so Claude can read the ones that have no source.

Usage: extract.py <sad.docx|sad.md> -o <ws>/sad/sad_ir.json
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import file_sha256, norm, save_json, utf8_console  # noqa: E402

HEAD_NUM_RE = re.compile(r'^((?:\d+\.)*\d+)\.?\s+(?:\d+\s+)?(.*)$')
MERMAID_START = re.compile(r'^\s*(sequenceDiagram|stateDiagram(?:-v2)?|flowchart|graph\s+(?:TD|LR|TB|RL|BT))\b')


def split_heading(raw: str) -> tuple[str, str]:
    raw = norm(raw)
    m = HEAD_NUM_RE.match(raw)
    if m:
        return m.group(1), norm(m.group(2))
    return '', raw


# --------------------------------------------------------------------------- docx

def _heading_level(par, style_name: str) -> int:
    s = (style_name or '').lower()
    m = re.match(r'(?:heading|标题)\s*(\d)', s)
    if m:
        return int(m.group(1))
    # outline level set directly on the paragraph
    try:
        ol = par._p.pPr.outlineLvl if par._p.pPr is not None else None
        if ol is not None:
            return int(ol.val) + 1
    except Exception:
        pass
    return 0


R_NS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def _to_png(path: Path) -> Path:
    """EMF/WMF previews (Visio OLE objects) -> PNG so they can be read; keep original on failure."""
    if path.suffix.lower() not in ('.emf', '.wmf'):
        return path
    try:
        from PIL import Image
        with Image.open(path) as im:
            png = path.with_suffix('.png')
            im.save(png)
        path.unlink()
        return png
    except Exception:
        return path


def _vsdx_text(blob: bytes) -> list[str]:
    """Shape texts of an embedded Visio drawing: hints for transcribing the diagram."""
    import io
    import zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except Exception:
        return []
    texts = []
    for n in sorted(z.namelist()):
        if re.match(r'visio/pages/page\d+\.xml$', n):
            xml = z.read(n).decode('utf-8', 'replace')
            for t in re.findall(r'<Text>(.*?)</Text>', xml, re.S):
                t = norm(html.unescape(re.sub(r'<[^>]+>', '', t)))
                if t:
                    texts.append(t)
    return texts


def _export_blips(el, part, img_dir: Path, counter: list[int], rel_prefix: str, hints: list | None = None) -> list[str]:
    out = []
    rids = []
    for blip in el.xpath('.//*[local-name()="blip"]'):
        rids.append(blip.get(R_NS + 'embed'))
    for vi in el.xpath('.//*[local-name()="imagedata"]'):
        rids.append(vi.get(R_NS + 'id'))
    for rid in rids:
        if not rid or rid not in part.related_parts:
            continue
        ip = part.related_parts[rid]
        ext = Path(str(getattr(ip, 'partname', 'x.png'))).suffix or '.png'
        counter[0] += 1
        f = img_dir / f'img_{counter[0]:03d}{ext}'
        f.write_bytes(ip.blob)
        f = _to_png(f)
        out.append(f'{rel_prefix}/{f.name}')
    if hints is not None:
        for ole in el.xpath('.//*[local-name()="OLEObject"]'):
            rid = ole.get(R_NS + 'id')
            if rid and rid in part.related_parts:
                txt = _vsdx_text(part.related_parts[rid].blob)
                if txt:
                    hints.append({'prog_id': ole.get('ProgID', ''), 'texts': txt})
    return out


def _cell_rows(tbl) -> list[list[str]]:
    rows = []
    for r in tbl.rows:
        cells, prev = [], None
        for c in r.cells:
            if c._tc is prev:          # horizontally merged cell repeats
                continue
            prev = c._tc
            cells.append(' / '.join(x for x in (norm(ln) for ln in c.text.splitlines()) if x))
        rows.append(cells)
    return rows


def extract_docx(path: Path, img_dir: Path, rel_prefix: str) -> list[dict]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    part = d.part
    blocks: list[dict] = []
    counter = [0]
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit('}', 1)[-1]
        if tag == 'p':
            par = Paragraph(el, d)
            text = par.text
            lvl = _heading_level(par, par.style.name if par.style is not None else '')
            hints = []
            imgs = _export_blips(el, part, img_dir, counter, rel_prefix, hints)
            if lvl and norm(text):
                num, title = split_heading(text)
                blocks.append({'t': 'h', 'lvl': lvl, 'num': num, 'text': title})
                continue
            if norm(text) or imgs:
                blk = {'t': 'p', 'text': text.rstrip(), 'style': par.style.name if par.style is not None else '',
                       'imgs': imgs}
                if hints:
                    blk['diagram_hints'] = hints
                blocks.append(blk)
        elif tag == 'tbl':
            tbl = Table(el, d)
            imgs = _export_blips(el, part, img_dir, counter, rel_prefix)
            blocks.append({'t': 'tbl', 'rows': _cell_rows(tbl), 'imgs': imgs})
    return lift_diagram_source(blocks)


def lift_diagram_source(blocks: list[dict]) -> list[dict]:
    """Turn paragraph runs that carry PlantUML / Mermaid source into code blocks."""
    out: list[dict] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        txt = b.get('text', '') if b['t'] == 'p' else ''
        s = txt.strip()
        if s.startswith('@startuml'):
            buf, j = [], i
            while j < len(blocks) and blocks[j]['t'] == 'p':
                buf.append(blocks[j]['text'])
                if blocks[j]['text'].strip().startswith('@enduml'):
                    break
                j += 1
            out.append({'t': 'code', 'lang': 'plantuml', 'text': '\n'.join(buf)})
            i = j + 1
            continue
        if s.startswith('```mermaid') or MERMAID_START.match(s):
            fenced = s.startswith('```')
            buf, j = ([] if fenced else [txt]), i + 1
            if fenced and s != '```mermaid':
                buf.append(s[len('```mermaid'):])
            while j < len(blocks) and blocks[j]['t'] == 'p':
                t = blocks[j]['text']
                if fenced and t.strip().startswith('```'):
                    j += 1
                    break
                if not fenced and not t.strip():
                    break
                buf.append(t)
                j += 1
            out.append({'t': 'code', 'lang': 'mermaid', 'text': '\n'.join(buf)})
            i = j
            continue
        out.append(b)
        i += 1
    return out


# --------------------------------------------------------------------------- markdown

MD_HEAD = re.compile(r'^(#{1,9})\s+(.*?)\s*#*\s*$')
MD_IMG = re.compile(r'!\[[^\]]*\]\(([^)\s]+)')
MD_FENCE = re.compile(r'^\s*```\s*([\w-]*)')


def _md_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|'):
        s = s[:-1]
    return [norm(c.replace('<br>', ' / ').replace('<br/>', ' / ')) for c in re.split(r'(?<!\\)\|', s)]


def extract_md(path: Path, img_dir: Path, rel_prefix: str) -> list[dict]:
    lines = path.read_text(encoding='utf-8').splitlines()
    blocks: list[dict] = []
    counter = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        m = MD_FENCE.match(line)
        if m:
            lang = (m.group(1) or '').lower()
            j = i + 1
            buf = []
            while j < len(lines) and not MD_FENCE.match(lines[j]):
                buf.append(lines[j])
                j += 1
            text = '\n'.join(buf)
            if lang in ('plantuml', 'puml', 'uml') or text.lstrip().startswith('@startuml'):
                blocks.append({'t': 'code', 'lang': 'plantuml', 'text': text})
            elif lang == 'mermaid':
                blocks.append({'t': 'code', 'lang': 'mermaid', 'text': text})
            else:
                blocks.append({'t': 'p', 'text': text, 'style': f'code:{lang}', 'imgs': []})
            i = j + 1
            continue
        m = MD_HEAD.match(line)
        if m:
            num, title = split_heading(re.sub(r'[*`]', '', m.group(2)))
            blocks.append({'t': 'h', 'lvl': len(m.group(1)), 'num': num, 'text': title})
            i += 1
            continue
        if line.strip().startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                r = _md_row(lines[i])
                if not all(re.fullmatch(r':?-{2,}:?', c) or c == '' for c in r):
                    rows.append([re.sub(r'[*`]', '', c) for c in r])
                i += 1
            blocks.append({'t': 'tbl', 'rows': rows, 'imgs': []})
            continue
        if line.strip():
            imgs = []
            for src in MD_IMG.findall(line):
                sp = (path.parent / src).resolve()
                if sp.exists():
                    counter += 1
                    name = f'img_{counter:03d}{sp.suffix}'
                    shutil.copyfile(sp, img_dir / name)
                    imgs.append(f'{rel_prefix}/{name}')
            blocks.append({'t': 'p', 'text': line.rstrip(), 'style': 'md', 'imgs': imgs})
        i += 1
    return blocks


# --------------------------------------------------------------------------- main

def extract(src: Path, out: Path) -> dict:
    img_dir = out.parent / 'images'
    if img_dir.exists():
        shutil.rmtree(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == '.docx':
        blocks = extract_docx(src, img_dir, 'images')
    elif src.suffix.lower() in ('.md', '.markdown'):
        blocks = extract_md(src, img_dir, 'images')
    else:
        raise SystemExit(f'unsupported SAD format {src.suffix}: give .docx or .md '
                         f'(convert .doc with scripts/docs/convert.py first)')
    ir = {'source': str(src), 'sha256': file_sha256(src), 'format': src.suffix.lower().lstrip('.'),
          'blocks': blocks}
    save_json(out, ir)
    return ir


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sad', type=Path)
    ap.add_argument('-o', '--out', type=Path, required=True)
    a = ap.parse_args()
    ir = extract(a.sad, a.out)
    kinds = {}
    for b in ir['blocks']:
        kinds[b['t']] = kinds.get(b['t'], 0) + 1
    nimg = sum(len(b.get('imgs', [])) for b in ir['blocks'])
    print(f"extracted {a.sad.name}: {kinds}, images={nimg} -> {a.out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

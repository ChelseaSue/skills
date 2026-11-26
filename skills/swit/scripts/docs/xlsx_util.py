"""openpyxl helpers for filling company templates without breaking their layout.

- locate sheets / header columns by bilingual header text (never fixed coordinates)
- read dropdown vocab from the template's data validation
- insert rows while keeping merged cells, data validation and row styles intact
- append revision-log rows, refresh cover dates
"""
from __future__ import annotations

import copy
import datetime as dt
import re

from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.cell_range import CellRange

SKIP_SHEETS = re.compile(r'(?i)cover|封面|template revision|revision of template|模板修订|filling|填写说明|wpsreserved')
REVLOG_SHEET = re.compile(r'(?i)(document revision|revision history|文档修订|修订记录|修订履历)')


def norm(v) -> str:
    return re.sub(r'\s+', ' ', str(v or '')).strip()


def find_sheet(wb, regex, exclude=SKIP_SHEETS):
    rx = re.compile(regex)
    for ws in wb.worksheets:
        if rx.search(ws.title) and not (exclude and exclude.search(ws.title) and not rx.search(exclude.pattern)):
            return ws
    return None


def data_sheets(wb):
    return [ws for ws in wb.worksheets if not SKIP_SHEETS.search(ws.title) and not REVLOG_SHEET.search(ws.title)]


def find_cell(ws, regex, rows=None, cols=None):
    rx = re.compile(regex)
    r0, r1 = rows or (1, ws.max_row)
    for row in ws.iter_rows(min_row=r0, max_row=min(r1, ws.max_row)):
        for c in row:
            if cols and c.column not in cols:
                continue
            if c.value is not None and rx.search(norm(c.value)):
                return c
    return None


def header_cols(ws, spec: dict, rows=(1, 6)):
    """spec: {key: regex} -> {key: column index}; missing keys are omitted."""
    out = {}
    for key, rx in spec.items():
        c = find_cell(ws, rx, rows)
        if c is not None:
            out[key] = c.column
    return out


# --------------------------------------------------------------------------- vocab

def dv_values(ws, col: int, row: int):
    """Allowed values of the list validation covering (row, col), or []."""
    for dv in ws.data_validations.dataValidation:
        if dv.type != 'list' or not dv.formula1:
            continue
        for rng in str(dv.sqref).split():
            try:
                c0, r0, c1, r1 = range_boundaries(rng)
            except ValueError:
                continue
            if c0 <= col <= c1 and r0 <= row <= r1:
                f = dv.formula1.strip()
                if f.startswith('"'):
                    return [x.strip() for x in f.strip('"').split(',') if x.strip()]
    return []


def pick_vocab(values, key_regex, fallback):
    for v in values:
        if re.search(key_regex, v):
            return v
    return fallback


# --------------------------------------------------------------------------- rows

def _shift_range(rng: str, idx: int, n: int) -> str:
    c0, r0, c1, r1 = range_boundaries(rng)
    if r0 >= idx:
        r0 += n
        r1 += n
    elif r1 >= idx:
        r1 += n
    return f'{get_column_letter(c0)}{r0}:{get_column_letter(c1)}{r1}'


def insert_rows(ws, idx: int, n: int, style_row: int | None = None):
    """Insert n rows before idx, shifting merged cells / validations / heights; new rows copy
    the style (and the horizontal merge pattern) of style_row (default idx-1)."""
    if n <= 0:
        return
    style_row = style_row or (idx - 1)
    merges = [str(m) for m in ws.merged_cells.ranges]
    pattern = []
    for m in merges:
        c0, r0, c1, r1 = range_boundaries(m)
        if r0 == r1 == style_row:
            pattern.append((c0, c1))
    for m in merges:
        ws.unmerge_cells(m)
    heights = {r: ws.row_dimensions[r].height for r in range(idx, ws.max_row + 1)}
    ws.insert_rows(idx, n)
    for r, h in sorted(heights.items(), reverse=True):
        ws.row_dimensions[r + n].height = h
    for m in merges:
        ws.merge_cells(_shift_range(m, idx, n))
    for dv in ws.data_validations.dataValidation:
        parts = []
        for rng in str(dv.sqref).split():
            if ':' not in rng:
                rng = f'{rng}:{rng}'
            try:
                parts.append(_shift_range(rng, idx, n))
            except ValueError:
                parts.append(rng)
        dv.sqref = ' '.join(parts)
    src = style_row if style_row < idx else style_row + n
    for r in range(idx, idx + n):
        for c in range(1, ws.max_column + 1):
            s = ws.cell(src, c)
            d = ws.cell(r, c)
            if s.has_style:
                d._style = copy.copy(s._style)
        ws.row_dimensions[r].height = ws.row_dimensions[src].height
        for c0, c1 in pattern:
            ws.merge_cells(start_row=r, start_column=c0, end_row=r, end_column=c1)


def copy_row_style(ws, src: int, dst: int, max_col: int):
    for c in range(1, max_col + 1):
        s = ws.cell(src, c)
        if s.has_style:
            ws.cell(dst, c)._style = copy.copy(s._style)
    if ws.row_dimensions[src].height:
        ws.row_dimensions[dst].height = ws.row_dimensions[src].height


def clear_block(ws, r0: int, r1: int, c0: int, c1: int):
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            cell = ws.cell(r, c)
            if type(cell).__name__ != 'MergedCell':
                cell.value = None


def extend_validations(ws, col: int, r0: int, r1: int):
    """Make every list validation that touches column col at row r0 cover r0..r1."""
    for dv in ws.data_validations.dataValidation:
        for rng in str(dv.sqref).split():
            try:
                c0, rr0, c1, rr1 = range_boundaries(rng if ':' in rng else f'{rng}:{rng}')
            except ValueError:
                continue
            if c0 <= col <= c1 and rr0 <= r0 <= rr1 and rr1 < r1:
                dv.sqref = f'{dv.sqref} {get_column_letter(col)}{rr1 + 1}:{get_column_letter(col)}{r1}'
                break


def set_cell(ws, r: int, c: int, value, number_format: str | None = None, wrap=True):
    cell = ws.cell(r, c)
    if type(cell).__name__ == 'MergedCell':
        return
    cell.value = value
    if number_format:
        cell.number_format = number_format
    if wrap and isinstance(value, str) and ('\n' in value or len(value) > 30):
        al = copy.copy(cell.alignment)
        al.wrap_text = True
        cell.alignment = al


# --------------------------------------------------------------------------- revision log / cover

def append_revision(wb, date: str, version: str, author: str, change: str, status: str = 'Draft'):
    ws = next((w for w in wb.worksheets if REVLOG_SHEET.search(w.title) and not re.search(r'(?i)template|模板', w.title)), None)
    if ws is None:
        return None
    hdr = find_cell(ws, r'(?i)^(日期 ?)?date|^日期', (1, 8))
    if hdr is None:
        return None
    cols = header_cols(ws, {'date': r'(?i)date|日期', 'version': r'(?i)version|版本', 'author': r'(?i)author|作者',
                            'change': r'(?i)change|record of changes|变更|履历', 'status': r'(?i)status|状态'},
                       (hdr.row, hdr.row))
    r = hdr.row + 1
    while any(ws.cell(r, c).value not in (None, '') for c in cols.values()):
        r += 1
    vals = {'date': date, 'version': version, 'author': author, 'change': change, 'status': status}
    for k, c in cols.items():
        set_cell(ws, r, c, vals[k], wrap=False)
    return r


def last_revision(wb):
    ws = next((w for w in wb.worksheets if REVLOG_SHEET.search(w.title) and not re.search(r'(?i)template|模板', w.title)), None)
    if ws is None:
        return None
    hdr = find_cell(ws, r'(?i)version|版本', (1, 8))
    if hdr is None:
        return None
    last = None
    for r in range(hdr.row + 1, ws.max_row + 1):
        v = ws.cell(r, hdr.column).value
        if v not in (None, ''):
            last = str(v)
    return last


def next_version(prev: str | None, major: bool = False) -> str:
    if not prev:
        return 'V0.1'
    m = re.search(r'(\d+)\.(\d+)', prev)
    if not m:
        return 'V0.1'
    a, b = int(m.group(1)), int(m.group(2))
    return f'V{a + 1}.0' if major else f'V{a}.{b + 1}'


def refresh_cover(wb, doc_number: str | None = None, date: dt.date | None = None, title_prefix: str | None = None):
    ws = next((w for w in wb.worksheets if re.search(r'(?i)cover|封面', w.title)), None)
    if ws is None:
        return
    date = date or dt.date.today()
    ds = date.strftime('%Y/%m/%d')
    for row in ws.iter_rows():
        for c in row:
            if not isinstance(c.value, str):
                continue
            v = c.value
            nv = re.sub(r'\d{4}/\d{1,2}/\d{1,2}(\s*(Release|Implement|发布|实施))', lambda m: ds + m.group(1), v)
            if doc_number:
                nv = re.sub(r'【AU-Q[RW]-R&D-\d+】', f'【{doc_number}】', nv)
            if nv != v:
                c.value = nv

#!/usr/bin/env python3
"""Fill the Excel deliverables from the case register, round results and the architecture model.

  cases       AU-QR-R&D-052  software integration test cases            (living document)
  record      AU-QR-R&D-236  software integration test record            (one file per first-type round)
  regression  AU-QR-R&D-237  software integration regression test record (one file per regression round)
  trace       AU-QR-R&D-022  SWE.5 traceability matrix, 8 sheets          (living document)
  report      AU-QR-R&D-238  software integration test report            (per round, cumulative)

Living documents are rebuilt on top of the previous output when it exists, so the revision log
is kept and a new entry appended. Columns are located by header text; dropdown values are read
from the template's data validation.

Usage:
  build_xlsx.py --project P --what cases|trace [--change "..."]
  build_xlsx.py --project P --what record|regression --round 1|R1 [--change "..."]
  build_xlsx.py --project P --what report --rounds 1 R1 ... [--change "..."]
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from common import Project, load_json, utf8_console  # noqa: E402
from rounds import CATS, by_category, load_round, metrics, ratio, verdict  # noqa: E402
import xlsx_util as X  # noqa: E402
from convert import convert  # noqa: E402

PCT = '0.0%'
CASE_COLS = {
    'id': r'(?i)标识符|identifier',
    'name': r'(?i)^名称|\bname\b',
    'priority': r'(?i)优先级|priority',
    'author': r'(?i)作者|author',
    'method': r'(?i)测试方法|test method',
    'design': r'(?i)设计方法|design method',
    'target': r'(?i)测试目标|test target',
    'pre': r'(?i)预置条件|preset condition|precondition',
    'steps': r'(?i)测试步骤|test step',
    'expected': r'(?i)预期输出|expected output',
    'criteria': r'(?i)判定准则|decision criteria',
}
RECORD_COLS = {
    'actual': r'(?i)实际输出|actual output',
    'verdict': r'(?i)判定结果|verdict',
    'defect': r'(?i)缺陷\s*id|defect id',
    'object': r'(?i)测试对象及版本|test objects? and versions?',
    'date': r'(?i)^时间|\bdate\b',
    'tester': r'(?i)测试人员|tester',
}


# --------------------------------------------------------------------------- shared

def template_book(prj: Project, key: str, out: Path, living: bool):
    if living and out.exists():
        return openpyxl.load_workbook(out), True
    src = prj.template(key)
    if src.suffix.lower() == '.xls':
        src = convert(src, prj.wsp('templates'))
    return openpyxl.load_workbook(src), False


def out_path(prj: Project, key: str, rnd: str = '') -> Path:
    name = prj.get(f'output.names.{key}').format(project=prj.get('project.name') or 'PROJECT', round=rnd)
    base = prj.resolve(prj.get('output.dir')) if prj.get('output.dir') else prj.wsp('out')
    return base / name


def finish(wb, prj: Project, out: Path, change: str, reused: bool, doc_key: str):
    prev = X.last_revision(wb)
    ver = X.next_version(prev) if reused else 'V0.1'
    X.append_revision(wb, dt.date.today().isoformat(), ver, prj.get('project.author', ''), change, 'Draft')
    X.refresh_cover(wb, prj.get(f'documents.{doc_key}.number'))
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out, ver


def vocab(prj, ws, col, row, group, key, regex):
    vals = X.dv_values(ws, col, row) if col else []
    return X.pick_vocab(vals, regex, prj.get(f'vocab.{group}.{key}'))


def comp_label(prj, c):
    if c.get('component'):
        return c['component']
    return {'dynamic': prj.text('动态行为', 'Dynamic Behavior'),
            'resource': prj.text('资源消耗', 'Resource Consumption'),
            'performance': prj.text('性能需求', 'Performance Requirement')}.get(c['category'], c['category'])


def ordered_cases(reg, model):
    order = {c['short']: i for i, c in enumerate(model['components'])}
    cat_order = {k: i for i, k in enumerate(CATS)}
    act = [c for c in reg['cases'] if c['status'] == 'Active']
    return sorted(act, key=lambda c: (cat_order.get(c['category'], 9), order.get(c.get('component') or '', 999), c['id']))


def method_text(prj, c):
    return prj.get(f"vocab.method.{c['method']}") or c['method']


def priority_text(prj, ws, col, row, c):
    rx = {'High': r'(?i)high|高', 'Medium': r'(?i)medium|中', 'Low': r'(?i)low|低'}[c.get('priority', 'Medium')]
    return vocab(prj, ws, col, row, 'priority', c.get('priority', 'Medium'), rx)


def case_sheet(wb, regex):
    for ws in X.data_sheets(wb):
        if re.search(regex, ws.title) and X.find_cell(ws, CASE_COLS['id'], (1, 6)):
            return ws
    for ws in X.data_sheets(wb):
        if X.find_cell(ws, CASE_COLS['id'], (1, 6)):
            return ws
    raise SystemExit('template has no sheet with an Identifiers/标识符 header')


def fill_case_rows(prj, ws, cases, extra=None):
    hdr = X.find_cell(ws, CASE_COLS['id'], (1, 6))
    hr = hdr.row
    cols = X.header_cols(ws, CASE_COLS, (hr - 1, hr))
    cols['comp'] = 1
    if extra:
        cols.update(X.header_cols(ws, extra, (hr - 1, hr)))
    start = hr + 1
    last_col = max(cols.values())
    styled_last = ws.max_row
    X.clear_block(ws, start, max(ws.max_row, start), 1, last_col)
    for i, c in enumerate(cases):
        r = start + i
        if r > styled_last:
            X.copy_row_style(ws, start, r, last_col)
        vals = {
            'comp': comp_label(prj, c), 'id': c['id'], 'name': c['name'],
            'priority': priority_text(prj, ws, cols.get('priority'), start, c),
            'author': c.get('author') or prj.get('project.author', ''), 'method': method_text(prj, c),
            'design': c['design_method'], 'target': c['target'], 'pre': c['precondition'],
            'steps': c['steps'], 'expected': c['expected'], 'criteria': c['criteria'],
        }
        if extra:
            vals.update(c.get('_record', {}))
        for k, col in cols.items():
            if k in vals:
                X.set_cell(ws, r, col, vals[k])
    end = start + max(len(cases), 1) - 1
    for k in ('priority', 'verdict'):
        if k in cols:
            X.extend_validations(ws, cols[k], start, end)
    return cols, start


# --------------------------------------------------------------------------- 052

def build_cases(prj, reg, model, change):
    out = out_path(prj, 'cases')
    wb, reused = template_book(prj, 'cases', out, living=True)
    ws = case_sheet(wb, r'(?i)test ?case|测试用例')
    cases = ordered_cases(reg, model)
    fill_case_rows(prj, ws, cases)
    return finish(wb, prj, out, change, reused, 'cases')


# --------------------------------------------------------------------------- 236 / 237

def build_record(prj, reg, model, rnd, change, regression):
    key = 'regression' if regression else 'record'
    out = out_path(prj, key, rnd['round'])
    wb, reused = template_book(prj, key, out, living=False)
    ws = case_sheet(wb, r'(?i)record|记录')
    by = {c['id']: c for c in reg['cases']}
    sel = [by[cid] for cid in rnd['selected'] if cid in by]
    order = {c['id']: i for i, c in enumerate(ordered_cases(reg, model))}
    sel.sort(key=lambda c: order.get(c['id'], 10 ** 6))
    hdr = X.find_cell(ws, CASE_COLS['id'], (1, 6))
    vcol = X.header_cols(ws, {'verdict': RECORD_COLS['verdict']}, (hdr.row - 1, hdr.row)).get('verdict')
    vmap = {
        'pass': vocab(prj, ws, vcol, hdr.row + 1, 'verdict', 'pass', r'P$|通过|pass'),
        'fail': vocab(prj, ws, vcol, hdr.row + 1, 'verdict', 'fail', r'F$|失败|fail'),
        'na': vocab(prj, ws, vcol, hdr.row + 1, 'verdict', 'na', r'NA$|不适用'),
        'blocked': vocab(prj, ws, vcol, hdr.row + 1, 'verdict', 'blocked', r'B$|阻塞'),
        'skipped': vocab(prj, ws, vcol, hdr.row + 1, 'verdict', 'skipped', r'S$|跳过'),
    }
    swver = f"{prj.get('project.software_name', '')} {rnd.get('software_version') or prj.get('project.software_version', '')}".strip()
    no_defect = prj.get('vocab.no_defect', 'NO')
    reason6 = prj.text(prj.get('swe6_transfer.reason_zh'), prj.get('swe6_transfer.reason_en'))
    ref6 = prj.get('swe6_transfer.reference') or ''
    for c in sel:
        res = rnd['results'].get(c['id'], {})
        v = verdict(rnd, c['id'])
        if c.get('execution') == 'swe6':
            v_txt = vmap['na']
            actual = prj.text('转 SWE.6：', 'Transferred to SWE.6: ') + reason6 + (f' ({ref6})' if ref6 else '')
        elif v == 'not_run':
            v_txt = ''
            actual = res.get('reason') or prj.text('未执行', 'Not run')
        else:
            v_txt = vmap.get(v, '')
            actual = res.get('actual', '')
        c['_record'] = {'actual': actual, 'verdict': v_txt,
                        'defect': ', '.join(res.get('defects', [])) or no_defect,
                        'object': swver, 'date': rnd.get('date', dt.date.today().isoformat()),
                        'tester': rnd.get('tester') or prj.get('project.tester', '')}
    fill_case_rows(prj, ws, sel, RECORD_COLS)
    if not regression:
        lab = X.find_cell(ws, r'(?i)一轮测试|first round', (1, 4))
        n = re.sub(r'\D', '', str(rnd['round'])) or '1'
        if lab is not None and n != '1':
            lab.value = prj.text(f'第{n}轮测试', f'Round {n} testing') if prj.lang() != 'bilingual' else f'第{n}轮测试 Round {n} testing'
    else:
        lab = X.find_cell(ws, r'(?i)回归测试|regression test', (1, 4))
        n = re.sub(r'\D', '', str(rnd['round'])) or '1'
        if lab is not None:
            lab.value = {'zh': f'第{n}轮回归测试', 'en': f'Regression round {n}'}.get(prj.lang(), f'第{n}轮回归测试 Regression round {n}')
    for c in sel:
        c.pop('_record', None)
    return finish(wb, prj, out, change, reused, key)


# --------------------------------------------------------------------------- 022

TRACE_SHEETS = {
    ('interface', 'fwd'): r'(?i)fwd.*\bif\b|正向.*接口', ('interface', 'bwd'): r'(?i)bwd.*\bif\b|反向.*接口',
    ('dynamic', 'fwd'): r'(?i)fwd.*dyn|正向.*动态', ('dynamic', 'bwd'): r'(?i)bwd.*dyn|反向.*动态',
    ('resource', 'fwd'): r'(?i)fwd.*res|正向.*资源', ('resource', 'bwd'): r'(?i)bwd.*res|反向.*资源',
    ('performance', 'fwd'): r'(?i)fwd.*perf|正向.*性能', ('performance', 'bwd'): r'(?i)bwd.*perf|反向.*性能',
}
TRACE_COLS = {
    'no': r'(?i)序号|^no\.?$|\bno\.',
    'case_name': r'(?i)用例名称|case name',
    'case_id': r'(?i)用例\s*id|case id',
    'anchor_name': r'(?i)(接口|动态行为|资源消耗|性能需求)名称|(interface|behavior|consumption|requirement) name',
    'anchor_id': r'(?i)(接口|动态行为|资源消耗|性能需求)\s*id|(interface|behavior|consumption|requirement) id',
    'remark': r'(?i)备注|remark',
}
MODEL_KEY = {'interface': 'interfaces', 'dynamic': 'dynamic', 'resource': 'resource', 'performance': 'performance'}


def _remark(prj, c):
    ex = c.get('execution')
    if ex == 'swe6':
        ref = prj.get('swe6_transfer.reference') or ''
        return prj.text('转 SWE.6 验证（需目标硬件测量）', 'Transferred to SWE.6 (target measurement)') + (f' {ref}' if ref else '')
    if ex == 'target-static':
        return prj.text('目标机构建产物静态核算', 'Static check on target build artefacts')
    if ex == 'review':
        return prj.text('集成检查', 'Integration review')
    return ''


def build_trace(prj, reg, model, change):
    out = out_path(prj, 'trace')
    wb, reused = template_book(prj, 'trace', out, living=True)
    act = [c for c in reg['cases'] if c['status'] == 'Active']
    stats = {}
    for cat in CATS:
        anchors = model[MODEL_KEY[cat]]
        cases = [c for c in act if c['category'] == cat]
        by_anchor = {}
        for c in cases:
            by_anchor.setdefault(c['anchor_key'], []).append(c)
        traced_anchors = sum(1 for a in anchors if by_anchor.get(a['key']))
        known = {a['key'] for a in anchors}
        traced_cases = sum(1 for c in cases if c['anchor_key'] in known)
        stats[cat] = {'anchors': len(anchors), 'cases': len(cases), 'traced_anchors': traced_anchors,
                      'traced_cases': traced_cases, 'coverage': ratio(traced_anchors, len(anchors))}
        for direction in ('fwd', 'bwd'):
            ws = X.find_sheet(wb, TRACE_SHEETS[(cat, direction)], exclude=None)
            if ws is None:
                continue
            rows = []
            if direction == 'fwd':
                amap = {a['key']: a for a in anchors}
                for c in sorted(cases, key=lambda x: x['id']):
                    a = amap.get(c['anchor_key'])
                    rows.append({'case_name': c['name'], 'case_id': c['id'],
                                 'anchor_name': a['name'] if a else c['anchor_name'],
                                 'anchor_id': (a or {}).get('id') or c.get('anchor_id') or 'NO-ID',
                                 'remark': _remark(prj, c)})
            else:
                for a in anchors:
                    cs = sorted(by_anchor.get(a['key'], []), key=lambda x: x['id'])
                    if not cs:
                        rows.append({'anchor_name': a['name'], 'anchor_id': a['id'] or 'NO-ID', 'case_name': '',
                                     'case_id': '', 'remark': prj.text('无用例（见策略裁剪说明）', 'No case (see strategy tailoring)')})
                    for c in cs:
                        rows.append({'anchor_name': a['name'], 'anchor_id': a['id'] or 'NO-ID',
                                     'case_name': c['name'], 'case_id': c['id'], 'remark': _remark(prj, c)})
            _fill_trace_sheet(ws, rows, stats[cat], direction)
    out_, ver = finish(wb, prj, out, change, reused, 'trace')
    return out_, ver, stats


def _fill_trace_sheet(ws, rows, st, direction):
    hdr = X.find_cell(ws, TRACE_COLS['no'], (1, 6))
    hr = hdr.row
    cols = X.header_cols(ws, TRACE_COLS, (hr, hr))
    start = hr + 1
    last = max(cols.values())
    stat_hdr = X.find_cell(ws, r'(?i)数据统计|statistics', (hr, hr))
    for m in [str(m) for m in ws.merged_cells.ranges]:
        c0, r0, c1, r1 = openpyxl.utils.range_boundaries(m)
        if r0 >= start and c1 <= last:
            ws.unmerge_cells(m)
    styled_last = ws.max_row
    X.clear_block(ws, start, max(ws.max_row, start), 1, last)
    for i, row in enumerate(rows):
        r = start + i
        if r > styled_last:
            X.copy_row_style(ws, start, r, last)
        X.set_cell(ws, r, cols['no'], i + 1, wrap=False)
        for k, v in row.items():
            if k in cols:
                X.set_cell(ws, r, cols[k], v)
    if stat_hdr is not None:
        lab_col = stat_hdr.column
        for r in range(start, start + 8):
            lab = X.norm(ws.cell(r, lab_col).value)
            if not lab:
                continue
            vc = ws.cell(r, lab_col + 1)
            if isinstance(vc.value, str) and vc.value.startswith('='):
                vc.number_format = PCT
                continue
            if re.search(r'(?i)覆盖率|coverage', lab):
                if direction == 'bwd':
                    vc.value = st['coverage']
                else:
                    vc.value = ratio(st['traced_cases'], st['cases'])
                vc.number_format = PCT
            elif re.search(r'(?i)追溯|traceable|traced', lab):
                vc.value = st['traced_anchors'] if direction == 'bwd' else st['traced_cases']
            elif re.search(r'(?i)架构|architecture', lab):
                vc.value = st['anchors']
            elif re.search(r'(?i)用例|test case', lab):
                vc.value = st['cases']


# --------------------------------------------------------------------------- 238

SEC_RE = re.compile(r'^\s*(\d)\s*[.、]')


def _sections(ws):
    out = {}
    for r in range(1, ws.max_row + 1):
        v = X.norm(ws.cell(r, 1).value)
        m = SEC_RE.match(v)
        if m:
            out[int(m.group(1))] = r
    return out


def _fill_table(ws, header_row, next_row, rows, colmap, keep_blank=1):
    """Write rows under header_row (data rows end before next_row - keep_blank), inserting rows as needed."""
    start = header_row + 1
    avail = (next_row - keep_blank) - start
    need = max(len(rows), 1)
    if need > avail:
        X.insert_rows(ws, start + avail, need - avail, style_row=start + max(avail - 1, 0))
    last_col = max(colmap.values())
    # a data-row merge that swallows two header columns would hide a value (e.g. 238 sec.4 F:G) -> split it
    mapped = set(colmap.values())
    for m in [str(m) for m in ws.merged_cells.ranges]:
        c0, r0, c1, r1 = openpyxl.utils.range_boundaries(m)
        if r0 == r1 and start <= r0 < start + max(need, avail) and len(mapped & set(range(c0, c1 + 1))) >= 2:
            ws.unmerge_cells(m)
    X.clear_block(ws, start, start + max(need, avail) - 1, 2, max(last_col, ws.max_column))
    for i, row in enumerate(rows):
        for k, v in row.items():
            if k in colmap and v is not None:
                fmt = PCT if isinstance(v, float) and k in ('actual', 'func', 'call', 'exec_rate', 'pass_rate') else None
                X.set_cell(ws, start + i, colmap[k], v, fmt)


def _final_verdicts(rounds):
    final = {}
    for rnd in rounds:
        for cid in rnd['selected']:
            v = verdict(rnd, cid)
            if v in ('pass', 'fail') or cid not in final:
                final[cid] = v
    return final


def build_report(prj, reg, model, rounds, defects, change):
    last = rounds[-1]
    out = out_path(prj, 'report', last['round'])
    wb, reused = template_book(prj, 'report', out, living=False)
    ws = X.find_sheet(wb, r'(?i)test report|测试报告', exclude=None)
    by = {c['id']: c for c in reg['cases']}
    act = [c for c in reg['cases'] if c['status'] == 'Active']
    T = prj.text
    kpi = prj.get('kpi')
    reach = {k: X.pick_vocab(X.dv_values(ws, 9, 5), rx, prj.get(f'vocab.reach.{k}'))
             for k, rx in (('yes', r'^(达成)?\s*Reach$|^达成'), ('no', r'Not Reach|未达成'))}

    # ---------- metrics
    final = _final_verdicts(rounds)
    first_sel = [cid for r in rounds if r['type'] == 'first' for cid in r['selected']]
    sel = list(dict.fromkeys(first_sel or rounds[0]['selected']))
    pseudo = {'selected': sel, 'results': {cid: {'verdict': v} for cid, v in final.items()}}
    m_all = metrics(by, pseudo)
    cov_round = next((r for r in reversed(rounds) if r.get('coverage', {}).get('total')), None)
    cov = (cov_round or {}).get('coverage', {})
    tot = cov.get('total', {})
    fcov = ratio(tot.get('functions_hit', 0), tot.get('functions_total', 0)) if tot else None
    ccov = ratio(tot.get('calls_hit', 0), tot.get('calls_total', 0)) if tot else None
    design = {}
    for cat in CATS:
        anchors = model[MODEL_KEY[cat]]
        keys = {c['anchor_key'] for c in act if c['category'] == cat}
        design[cat] = ratio(sum(1 for a in anchors if a['key'] in keys), len(anchors))
    dfx = defects or []
    fixed_states = ('fixed', 'verified', 'closed', 'rejected')
    closed = [d for d in dfx if d.get('status') in fixed_states]
    on_time = [d for d in closed if d.get('closed_on_time', True)]
    closure = ratio(len(on_time), len(dfx)) if dfx else None

    def row1(label, val, target, note=''):
        ok = val is None and note.startswith('NA') or (val is not None and val + 1e-9 >= target)
        return {'target': label, 'actual': val if val is not None else (note or T('未执行', 'Not run')),
                'reach': reach['yes'] if ok else reach['no'], 'note': '' if ok else note}

    transferred = m_all['transferred']
    sec1 = [
        row1(T('软件集成测试用例对软件组件接口的覆盖率', 'Integration test case coverage of software component interfaces'),
             design['interface'], kpi['interface_coverage']),
        row1(T('软件集成测试用例对动态行为的覆盖率', 'Integration test case coverage of dynamic behaviours'),
             design['dynamic'], kpi['dynamic_coverage']),
        row1(T('软件集成测试用例对资源消耗的覆盖率', 'Integration test case coverage of resource consumption'),
             design['resource'], kpi['interface_coverage']),
        row1(T('软件集成测试用例对性能需求的覆盖率', 'Integration test case coverage of performance requirements'),
             design['performance'], kpi['interface_coverage'],
             ''),
        row1(T('软件集成测试用例执行率', 'Software integration test case execution rate'), m_all['execution_rate'],
             kpi['execution_rate'], T(f"未执行 {m_all['not_executed']} 条", f"{m_all['not_executed']} cases not executed")),
        row1(T('软件集成测试用例通过率', 'Software integration test case pass rate'), m_all['pass_rate'], kpi['pass_rate'],
             T(f"失败 {m_all['failed']} 条", f"{m_all['failed']} cases failed")),
        row1(T('软件集成测试缺陷及时关闭率', 'Timely closure rate of software integration test defects'), closure,
             kpi['defect_closure_rate'], 'NA' + T('（本过程未发现缺陷）', ' (no defect found)') if not dfx else ''),
        row1(T('函数覆盖率', 'Function coverage'), fcov, kpi['function_coverage'],
             T('见第 3 节未达标分析', 'see the analysis in section 3') if fcov is not None else T('未采集', 'Not collected')),
        row1(T('调用覆盖率', 'Call coverage'), ccov, kpi['call_coverage'],
             T('见第 3 节未达标分析', 'see the analysis in section 3') if ccov is not None else T('未采集', 'Not collected')),
    ]
    if transferred:
        sec1[3]['note'] = T(f'含 {transferred} 条转 SWE.6 用例（判定 NA，不计入执行率/通过率）',
                            f'{transferred} cases transferred to SWE.6 (verdict NA, excluded from execution/pass rates)')

    # ---------- section 2: integration summary (from config, else TBD placeholders)
    integ = prj.get('integration.rounds') or []
    sec2 = []
    if integ:
        for ir in integ:
            for j, sw in enumerate(ir.get('software', [])):
                sec2.append({'round': ir.get('round') if j == 0 else None, 'sw': sw, 'ver': ir.get('version'),
                             'entry': ir.get('entry_ok'), 'isw': ir.get('integrated_software') if j == 0 else None,
                             'iver': ir.get('integrated_version') if j == 0 else None,
                             'exit': ir.get('exit_ok') if j == 0 else None})
    else:
        mods = {}
        scope = set(prj.get('scope.components') or [c['short'] for c in model['components']])
        for c in model['components']:
            if c['short'] in scope:
                mods.setdefault(c['module'], []).append(c['short'])
        tbd = T('【TBD-人工填写，取自 235 软件集成记录】', '【TBD-fill from AU-QR-R&D-235 integration record】')
        for j, (mod, comps) in enumerate(mods.items()):
            sec2.append({'round': T('首次集成', 'First time integration') if j == 0 else None,
                         'sw': '、'.join(comps), 'ver': last.get('software_version') or prj.get('project.software_version'),
                         'entry': tbd, 'isw': prj.get('project.software_name') if j == 0 else None,
                         'iver': last.get('software_version') if j == 0 else None, 'exit': tbd if j == 0 else None})

    # ---------- section 3: coverage per object
    sec3 = []
    for o in cov.get('objects', []):
        f = ratio(o.get('functions_hit', 0), o.get('functions_total', 0))
        cl = ratio(o.get('calls_hit', 0), o.get('calls_total', 0))
        ok = (f is not None and f + 1e-9 >= kpi['function_coverage']) and (cl is None or cl + 1e-9 >= kpi['call_coverage'])
        sec3.append({'obj': o['name'], 'ver': o.get('version') or last.get('software_version'), 'func': f,
                     'call': cl if cl is not None else T('无跨组件调用', 'No cross-component call'),
                     'ok': T('是', 'Yes') if ok else T('否', 'No'), 'why': o.get('analysis', '')})
    if not sec3:
        sec3.append({'obj': prj.get('project.software_name'), 'ver': last.get('software_version'),
                     'func': T('未执行', 'Not run'), 'call': T('未执行', 'Not run'), 'ok': T('否', 'No'),
                     'why': T('本轮未采集覆盖率', 'Coverage not collected in this round')})

    # ---------- section 4: implementation per round x category
    sec4 = []
    cat_name = {'interface': T('接口', 'Interfaces'), 'dynamic': T('动态行为', 'Dynamic Behaviors'),
                'resource': T('资源消耗', 'Resource Consumption'), 'performance': T('性能需求', 'Performance Requirements')}
    for rnd in rounds:
        bc = by_category(by, rnd)
        n = re.sub(r'\D', '', str(rnd['round'])) or '1'
        if rnd['type'] == 'first':
            label = T('一轮测试', 'First round of testing') if n == '1' else T(f'第{n}轮测试', f'Round {n} testing')
        else:
            label = T(f'第{n}轮回归测试', f'Regression round {n}')
        first_row = True
        for cat in CATS:
            m = bc[cat]
            if not (m['selected'] or m['transferred']):
                continue
            reason = []
            if m['not_executed']:
                reason.append(T(f"{m['not_executed']} 条未执行", f"{m['not_executed']} not run"))
            if m['transferred']:
                reason.append(T(f"{m['transferred']} 条转 SWE.6（NA）", f"{m['transferred']} transferred to SWE.6 (NA)"))
            sec4.append({'round': label if first_row else None, 'obj': cat_name[cat],
                         'ver': rnd.get('software_version') or prj.get('project.software_version'),
                         'sel': m['selected'], 'exe': m['executed'], 'nexe': m['not_executed'],
                         'why': '; '.join(reason) or 'NA', 'pass': m['passed'],
                         'exec_rate': m['execution_rate'] if m['execution_rate'] is not None else T('未执行', 'Not run'),
                         'pass_rate': m['pass_rate'] if m['pass_rate'] is not None else T('未执行', 'Not run'),
                         'env': (rnd.get('environment_difference') or prj.get('environment_difference') or '') if first_row else None})
            first_row = False

    # ---------- sections 5-7
    open_d = [d for d in dfx if d.get('status') not in fixed_states]
    sev = {}
    for d in dfx:
        sev[d.get('severity', '?')] = sev.get(d.get('severity', '?'), 0) + 1
    analysis = (T(f"本过程共发现 {len(dfx)} 个缺陷（按严重度：{sev}），已修正 {len(closed)} 个，未修正 {len(open_d)} 个。",
                  f"{len(dfx)} defects found in this process (by severity: {sev}); {len(closed)} corrected, {len(open_d)} open. ")
                + ' '.join(f"{d['id']}: {d.get('title') or d.get('description', '')}" for d in dfx[:10])) if dfx else \
        T('本过程未发现缺陷。', 'No defect was found in this process.')
    sec6 = [{'id': d['id'], 'desc': d.get('description') or d.get('title', ''), 'sev': d.get('severity', ''),
             'why': d.get('legacy_reason') or T('【TBD-遗留原因】', '【TBD-legacy reason】'),
             'measure': d.get('measure') or T('【TBD-后继措施】', '【TBD-follow-up measure】')} for d in open_d]
    kpis_ok = all(r['reach'] == reach['yes'] for r in sec1)
    blocking = [d for d in open_d if str(d.get('severity', '')).upper() in ('A', 'B', 'S', 'CRITICAL', 'MAJOR')]
    if kpis_ok and not open_d:
        concl = prj.get('vocab.conclusion.pass')
    elif kpis_ok and not blocking:
        concl = prj.get('vocab.conclusion.conditional')
    else:
        concl = prj.get('vocab.conclusion.fail')
    concl_vals = X.dv_values(ws, 3, _sections(ws).get(7, 49) + 1)
    concl = X.pick_vocab([v.strip() for v in concl_vals], re.escape(concl.strip()) + '$', concl)
    clar = T(f"架构覆盖：接口 {design['interface']:.0%}、动态行为 {design['dynamic']:.0%}；执行率/通过率见第1节；"
             f"{transferred} 条需目标硬件的用例转 SWE.6；未关闭缺陷 {len(open_d)} 个。",
             f"Architecture coverage: interfaces {design['interface']:.0%}, dynamic behaviours {design['dynamic']:.0%}; "
             f"execution/pass rates see section 1; {transferred} target-hardware cases transferred to SWE.6; "
             f"{len(open_d)} open defects.") if design['interface'] is not None else ''

    # ---------- write bottom-up so inserted rows do not shift sections still to be written
    sec = _sections(ws)
    r7 = sec.get(7)
    if r7:
        cc = X.find_cell(ws, r'(?i)测试结论|test conclusion', (r7, r7 + 3))
        cl = X.find_cell(ws, r'(?i)^说明|clarification', (r7, r7 + 4))
        if cc:
            X.set_cell(ws, cc.row, cc.column + 1, concl.strip())
        if cl:
            X.set_cell(ws, cl.row, cl.column + 1, clar)
    r6, r5, r4, r3, r2, r1 = (sec.get(k) for k in (6, 5, 4, 3, 2, 1))
    h6 = X.find_cell(ws, r'(?i)缺陷\s*id|defect id', (r6 + 1, r6 + 3), cols=range(2, 30))
    if h6:
        _fill_table(ws, h6.row, r7, sec6, X.header_cols(ws, {
            'id': r'(?i)缺陷\s*id|defect id', 'desc': r'(?i)缺陷描述|defect description', 'sev': r'(?i)严重|severity',
            'why': r'(?i)遗留原因|legacy', 'measure': r'(?i)后继措施|successor|measure'}, (h6.row, h6.row)))
    h5 = X.find_cell(ws, r'(?i)发现的缺陷|defects found', (r5 + 1, r5 + 3), cols=range(2, 30))
    if h5:
        cols5 = X.header_cols(ws, {'found': r'(?i)发现的缺陷|defects found', 'fixed': r'(?i)修正的缺陷|defects corrected',
                                   'open': r'(?i)未修正|not corrected'}, (h5.row, h5.row))
        for k, v in (('found', len(dfx)), ('fixed', len(closed)), ('open', len(open_d))):
            if k in cols5:
                X.set_cell(ws, h5.row + 1, cols5[k], v, wrap=False)
        an = X.find_cell(ws, r'(?i)整体分析|overall analysis', (h5.row, r6))
        if an:
            X.set_cell(ws, an.row + 1, 2, analysis)
    h4 = X.find_cell(ws, r'(?i)测试轮次|test session', (r4 + 1, r4 + 3), cols=range(2, 30))
    if h4:
        _fill_table(ws, h4.row, r5, sec4, X.header_cols(ws, {
            'round': r'(?i)测试轮次|test session', 'obj': r'(?i)测试对象|test object', 'ver': r'(?i)对象版本|object version',
            'sel': r'(?i)选择用例|select', 'exe': r'(?i)^执行用例|number of executed', 'nexe': r'(?i)未执行用例数|unexecuted',
            'why': r'(?i)未执行理由|reasons', 'pass': r'(?i)通过用例数|adoption of the number',
            'exec_rate': r'(?i)执行率|executed? +rate|implementation rate', 'pass_rate': r'(?i)通过率|pass rate',
            'env': r'(?i)环境差异|differences in test environment'}, (h4.row, h4.row)))
    h3 = X.find_cell(ws, r'(?i)被测对象|tested object', (r3 + 1, r3 + 3), cols=range(2, 30))
    if h3:
        _fill_table(ws, h3.row, r4, sec3, X.header_cols(ws, {
            'obj': r'(?i)被测对象|tested object', 'ver': r'(?i)^版本|^version', 'func': r'(?i)函数覆盖|function',
            'call': r'(?i)调用覆盖|call', 'ok': r'(?i)是否达标|attainment', 'why': r'(?i)未达标|analysis'}, (h3.row, h3.row)))
    h2 = X.find_cell(ws, r'(?i)集成轮次|integration round', (r2 + 1, r2 + 3), cols=range(2, 30))
    if h2:
        _fill_table(ws, h2.row, r3, sec2, X.header_cols(ws, {
            'round': r'(?i)集成轮次|integration round', 'sw': r'(?i)待集成软件|software to be integrated',
            'ver': r'(?i)待集成版本|version to be integrated', 'entry': r'(?i)准入|compliance with access',
            'isw': r'(?i)^集成软件 |^集成软件$|integration software', 'iver': r'(?i)集成软件版本|integrated software version',
            'exit': r'(?i)准出|adoption of integrated'}, (h2.row, h2.row)))
    h1 = X.find_cell(ws, r'(?i)^测试目标|^test target', (r1 + 1, r1 + 4), cols=range(2, 30))
    if h1:
        _fill_table(ws, h1.row, r2, sec1, X.header_cols(ws, {
            'target': r'(?i)测试目标|test target', 'actual': r'(?i)实际达成|actual achievement',
            'reach': r'(?i)达成判定|reaching a decision', 'note': r'(?i)未达成情况|non-achievement'}, (h1.row, h1.row)))
        X.extend_validations(ws, 9, h1.row + 1, h1.row + len(sec1))
    out_, ver = finish(wb, prj, out, change, reused, 'report')
    return out_, ver, {'kpi_rows': sec1, 'conclusion': concl, 'metrics': m_all}


# --------------------------------------------------------------------------- CLI

def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--what', required=True, choices=['cases', 'record', 'regression', 'trace', 'report'])
    ap.add_argument('--round')
    ap.add_argument('--rounds', nargs='*')
    ap.add_argument('--change', default='')
    a = ap.parse_args()
    prj = Project(a.project)
    reg = load_json(prj.wsp('cases', 'cases.json'))
    model = load_json(prj.wsp('sad', 'arch_model.json'))
    change = a.change or prj.text('按软件架构生成/更新', 'Generated / updated from the software architecture')
    if a.what == 'cases':
        out, ver = build_cases(prj, reg, model, change)
    elif a.what in ('record', 'regression'):
        rnd = load_round(prj.wsp('results', f'round_{a.round}.json'))
        out, ver = build_record(prj, reg, model, rnd, change, a.what == 'regression')
    elif a.what == 'trace':
        out, ver, st = build_trace(prj, reg, model, change)
        for k, v in st.items():
            cov = 'n/a' if v['coverage'] is None else f"{v['coverage']:.1%}"
            print(f"  {k:12s} anchors={v['anchors']:4d} cases={v['cases']:4d} traced={v['traced_anchors']:4d} coverage={cov}")
    else:
        rounds = [load_round(prj.wsp('results', f'round_{r}.json')) for r in (a.rounds or [])]
        defects = load_json(prj.resolve(prj.get('defects_file')), default=[]) if prj.get('defects_file') else []
        out, ver, info = build_report(prj, reg, model, rounds, defects, change)
        print(f"  conclusion: {info['conclusion']}")
    print(f'{a.what}: {out} ({ver})')
    return 0


if __name__ == '__main__':
    sys.exit(main())

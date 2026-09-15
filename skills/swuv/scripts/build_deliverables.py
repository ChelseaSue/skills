#!/usr/bin/env python3
"""Write the three SWE.4 deliverables from the generated cases.

  cases  -> AU-QR-R&D-046 software unit test cases   (one sheet per component)
  trace  -> AU-QR-R&D-038 traceability matrix        (forward + backward)
  report -> AU-QR-R&D-048 unit test report           (objectives / static / coverage / execution)

The report and traceability templates are .xlsx and are cloned so the cover,
revision sheets and company formatting survive.  The case template ships as a
legacy .xls, which openpyxl cannot write, so that workbook is rebuilt from the
column contract recorded in references/template-structure.md; the column order
and the five header rows are reproduced exactly.

Usage:
  python build_deliverables.py --cases cases.json --spec ut_spec.json --all
  python build_deliverables.py --cases cases.json --spec ut_spec.json --only trace
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
except ImportError:  # pragma: no cover
    print("error: openpyxl is required (pip install openpyxl)", file=sys.stderr)
    raise

THIN = Side(style='thin', color='808080')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill('solid', fgColor='D9E1F2')
WRAP = Alignment(vertical='top', wrap_text=True)
PERCENT_FMT = '0.0%'

# Column contract of AU-QR-R&D-046, verified against the reviewed deliverable.
CASE_COLUMNS = [
    ('模块/Module', 14, 'module'),
    ('优先级/Priority', 10, 'priority'),
    ('标识符/Flag', 14, 'case_id'),
    ('名称/Name', 30, 'case_name'),
    ('软件单元ID/Software Unit ID', 18, 'unit_id'),
    ('软件单元名称/Software Unit Name', 26, 'unit_name'),
    ('测试方法/Test Method', 12, 'test_method'),
    ('设计方法/Design Method', 26, 'design_method'),
    ('测试目标/Test Target', 22, 'test_target'),
    ('预置条件/Precondition', 20, 'precondition'),
    ('测试步骤/Test Steps', 48, 'steps'),
    ('预期输出/Expect Output', 34, 'expected'),
    ('判定准则/Criteria', 30, 'verdict'),
]


def _as_percent(cell) -> None:
    """Render a ratio cell as a percentage.

    The value stays numeric so the sheet can still be totalled; only the
    display format changes.  Without this a coverage of 1.0 shows up as a bare
    "1", which reads as a count rather than 100%.
    """
    if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
        cell.number_format = PERCENT_FMT


def _style_header(ws, row: int, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(bold=True)
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(vertical='center', horizontal='center', wrap_text=True)
        cell.border = BORDER


def build_cases(cases: list[dict], spec: dict, out: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = spec.get('component', 'Cases')[:31]

    ws.cell(row=1, column=1, value='测试级别/Test level').font = Font(bold=True)
    ws.cell(row=1, column=2, value='SWE.4')
    ws.cell(row=2, column=1, value='测试用例/Test case').font = Font(bold=True)
    ws.cell(row=3, column=1, value=f"模块/Module: {spec.get('component', '')}")
    ws.cell(row=4, column=1,
            value=f"覆盖率目标/Coverage target: statement "
                  f"{spec.get('coverage_targets', {}).get('statement', 1.0):.0%}, branch "
                  f"{spec.get('coverage_targets', {}).get('branch', 1.0):.0%}"
                  + ('' if spec.get('coverage_targets', {}).get('mcdc') is None
                     else f", MC/DC {spec['coverage_targets']['mcdc']:.0%}"))

    header_row = 5
    for i, (title, width, _) in enumerate(CASE_COLUMNS, 1):
        ws.cell(row=header_row, column=i, value=title)
        ws.column_dimensions[ws.cell(row=header_row, column=i).column_letter].width = width
    _style_header(ws, header_row, len(CASE_COLUMNS))
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    r = header_row + 1
    prev_unit = None
    for case in cases:
        for i, (_, _, key) in enumerate(CASE_COLUMNS, 1):
            value = case.get(key, '')
            # The reviewed deliverable leaves the unit id/name blank on
            # continuation rows of the same function group.
            if key in ('unit_id', 'unit_name') and case['unit_name'] == prev_unit:
                value = ''
            cell = ws.cell(row=r, column=i, value=value)
            cell.alignment = WRAP
            cell.border = BORDER
        prev_unit = case['unit_name']
        r += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def _clone_template(template: Path | None, out: Path) -> openpyxl.Workbook:
    if template and template.is_file() and template.suffix.lower() == '.xlsx':
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, out)
        return openpyxl.load_workbook(out)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    return wb


def _sheet(wb: openpyxl.Workbook, *names: str):
    """First sheet whose title contains any of the given fragments."""
    for name in names:
        for ws in wb.worksheets:
            if name.lower() in ws.title.lower():
                return ws
    return None


def _reset_sheet(ws) -> None:
    """Clear a cloned template sheet before refilling it.

    Merged ranges inherited from the template must go first: openpyxl silently
    drops writes to any cell of a merged range other than its anchor, which
    would blank out scattered rows of the regenerated table.
    """
    for rng in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(rng))
    if ws.max_row:
        ws.delete_rows(1, ws.max_row)
    # Example pictures / charts the template author left on a data sheet (the
    # 048 static-results sheet carries a screenshot of a naming-rule table)
    # survive delete_rows and would sit on top of the regenerated table.
    ws._images = []
    ws._charts = []
    # Cell comments belong to the example rows that were just deleted.
    for row in ws.iter_rows():
        for c in row:
            c.comment = None


def build_trace(cases: list[dict], model: dict, spec: dict,
                template: Path | None, out: Path) -> Path:
    wb = _clone_template(template, out)

    units = model['units']
    unit_ids = {u['name']: u['unit_id'] for u in units}
    by_unit: dict[str, list[dict]] = {}
    for c in cases:
        by_unit.setdefault(c['unit_name'], []).append(c)

    traced = sum(1 for u in units if by_unit.get(u['name']))
    stats = [
        ('软件单元测试用例数量/Number of test cases', len(cases)),
        ('软件详设单元数量/Number of design units', len(units)),
        ('追溯的软件详设数量/Traced design units', traced),
        ('软件详设覆盖率/Design coverage', (traced / len(units)) if units else 0.0),
    ]
    PCT_STAT = len(stats) - 1          # only the last stat is a ratio

    fwd = _sheet(wb, '正向', 'forward') or wb.create_sheet('正向')
    _reset_sheet(fwd)
    fwd.cell(row=1, column=1, value='软件单元测试追溯矩阵（软件单元测试用例-软件详设）').font = Font(bold=True)
    head = ['序号/No.', '软件单元测试用例ID', '软件单元测试用例名称', '软件详设ID', '软件详设名称', '备注/Remarks']
    for i, h in enumerate(head, 1):
        fwd.cell(row=2, column=i, value=h)
    _style_header(fwd, 2, len(head))
    for n, c in enumerate(cases, 1):
        fwd.cell(row=2 + n, column=1, value=n)
        fwd.cell(row=2 + n, column=2, value=c['case_id'])
        fwd.cell(row=2 + n, column=3, value=c['case_name'])
        fwd.cell(row=2 + n, column=4, value=unit_ids.get(c['unit_name'], ''))
        fwd.cell(row=2 + n, column=5, value=c['unit_name'])
    for i, (label, value) in enumerate(stats):
        fwd.cell(row=3 + i, column=8, value=label)
        cell = fwd.cell(row=3 + i, column=9, value=value)
        if i == PCT_STAT:
            _as_percent(cell)
    for col, width in zip('ABCDEFGHI', (8, 16, 30, 18, 28, 14, 3, 40, 12)):
        fwd.column_dimensions[col].width = width

    bwd = _sheet(wb, '反向', 'backward') or wb.create_sheet('反向')
    _reset_sheet(bwd)
    bwd.cell(row=1, column=1, value='软件单元测试追溯矩阵（软件详设-软件单元测试）').font = Font(bold=True)
    head_b = ['序号/No.', '软件详设ID', '软件详设名称', '软件单元测试用例ID', '软件单元测试用例名称', '备注/Remarks']
    for i, h in enumerate(head_b, 1):
        bwd.cell(row=2, column=i, value=h)
    _style_header(bwd, 2, len(head_b))
    r, n = 3, 0
    for u in units:
        group = by_unit.get(u['name'], [])
        if not group:
            n += 1
            bwd.cell(row=r, column=1, value=n)
            bwd.cell(row=r, column=2, value=u['unit_id'])
            bwd.cell(row=r, column=3, value=u['name'])
            bwd.cell(row=r, column=6, value='无对应测试用例/NOT COVERED')
            r += 1
            continue
        for j, c in enumerate(group):
            n += 1
            bwd.cell(row=r, column=1, value=n)
            if j == 0:
                bwd.cell(row=r, column=2, value=u['unit_id'])
                bwd.cell(row=r, column=3, value=u['name'])
            bwd.cell(row=r, column=4, value=c['case_id'])
            bwd.cell(row=r, column=5, value=c['case_name'])
            r += 1
    for i, (label, value) in enumerate(stats):
        bwd.cell(row=3 + i, column=8, value=label)
        cell = bwd.cell(row=3 + i, column=9, value=value)
        if i == PCT_STAT:
            _as_percent(cell)
    for col, width in zip('ABCDEFGHI', (8, 18, 28, 16, 30, 22, 3, 40, 12)):
        bwd.column_dimensions[col].width = width

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def build_report(cases: list[dict], model: dict, spec: dict, static: dict | None,
                 coverage: dict | None, template: Path | None, out: Path) -> Path:
    wb = _clone_template(template, out)
    ws = _sheet(wb, '报告', 'summary', 'verification') or wb.create_sheet('报告')
    _reset_sheet(ws)

    tgt = spec.get('coverage_targets', {})
    cov = coverage or {}
    static = static or {}
    r = 1

    def section(title: str) -> None:
        nonlocal r
        ws.cell(row=r, column=1, value=title).font = Font(bold=True, size=12)
        r += 1

    def table(head: list[str], rows: list[list],
              percent_cols: set[int] | None = None,
              percent_skip_rows: set[int] | None = None) -> None:
        """Write one titled table.

        `percent_cols` lists the 1-based columns holding ratios, and
        `percent_skip_rows` the 0-based rows within `rows` to leave alone -
        needed where a ratio column also carries non-ratio numbers, such as the
        cyclomatic-complexity row of the objectives table.
        """
        nonlocal r
        percent_cols = percent_cols or set()
        percent_skip_rows = percent_skip_rows or set()
        for i, h in enumerate(head, 1):
            ws.cell(row=r, column=i, value=h)
        _style_header(ws, r, len(head))
        r += 1
        for n, row in enumerate(rows):
            for i, v in enumerate(row, 1):
                cell = ws.cell(row=r, column=i, value=v)
                cell.alignment = WRAP
                cell.border = BORDER
                if i in percent_cols and n not in percent_skip_rows:
                    _as_percent(cell)
            r += 1
        r += 1

    def reached(actual, target) -> str:
        if actual is None or target is None:
            return '未执行/Not run'
        return '达成/Reach' if actual >= target else '未达成/Not Reach'

    def coverage_gap() -> str:
        """Why the coverage target was missed, in reviewable terms.

        A bare "not reached" gets a deliverable bounced at review, so the
        uncovered line numbers are quoted directly.  Code that is not part of
        the detailed design - dead functions the SWDD excluded - is the usual
        and legitimate reason, and naming the lines lets the reviewer confirm
        that rather than take it on trust.
        """
        gaps = [f for f in (cov.get('coverage_files') or []) if f.get('uncovered_lines')]
        if not gaps:
            return ''
        parts = [f"{Path(f['file']).name} 未覆盖行 {f['uncovered_lines']}" for f in gaps]
        return ('；'.join(parts)
                + '。请逐条确认属于详设已排除的死代码或不可达的防御性分支，并在此说明理由')

    section('1. 测试目标总结/Summary of Test Objectives')
    table(['测试目标/Test objectives', '工具/Tool', '实际达成/Actual', '达成判定/Decision',
           '未达成说明/Fact sheet not reached'],
          [['100%覆盖软件详细设计/100% cover software detailed design',
            '/', cov.get('design_coverage'), reached(cov.get('design_coverage'), 1.0), ''],
           ['单元语句覆盖率/Statement coverage', 'gcovr',
            cov.get('statement'), reached(cov.get('statement'), tgt.get('statement')),
            '' if reached(cov.get('statement'), tgt.get('statement')).startswith('达成')
            else coverage_gap()],
           ['单元分支覆盖率/Branch coverage', 'gcovr',
            cov.get('branch'), reached(cov.get('branch'), tgt.get('branch')),
            '' if reached(cov.get('branch'), tgt.get('branch')).startswith('达成')
            else coverage_gap()],
           ['用例执行率/Use case execution rate', 'Ceedling',
            cov.get('execution_rate'), reached(cov.get('execution_rate'), 1.0), ''],
           ['测试通过率/Test pass rate', 'Ceedling',
            cov.get('pass_rate'), reached(cov.get('pass_rate'), 1.0), ''],
           ['圈复杂度/Cyclomatic complexity <= %s' % spec.get('static', {}).get('cyclomatic_max', 15),
            static.get('tool', 'cppcheck'), static.get('cyclomatic_max_found'),
            '达成/Reach' if static.get('cyclomatic_ok') else '未达成/Not Reach', ''],
           ['编码规则/Coding rules (MISRA C:2012)', static.get('tool', 'cppcheck'),
            static.get('misra_summary', ''),
            '达成/Reach' if static.get('misra_ok') else '未达成/Not Reach', '']],
          percent_cols={3}, percent_skip_rows={5, 6})

    section('2. 静态验证情况总结/Summary of static validation')
    table(['静态验证/Static Verify', '验证对象及版本/Object and version', '验证项/Validation items',
           '通过标准/Standard', '结果说明/Results', '是否通过/Pass'],
          [['一轮静态验证/First round', static.get('object', spec.get('component', '')),
            '编码规则 MISRA C:2012 / 圈复杂度',
            'MISRA mandatory=0; 圈复杂度<=%s' % spec.get('static', {}).get('cyclomatic_max', 15),
            (static.get('summary', '未执行/Not run')
             + (f"；报告/Report：{static['report']}" if static.get('report') else '')),
            ('not run' if not static.get('summary')
             else 'Pass' if static.get('misra_ok') and static.get('cyclomatic_ok')
             else 'Pass with conditions' if static.get('misra_ok')
             else 'Fail')]])

    section('3. 覆盖率情况总结/Summary of coverage situation')
    mcdc_target = tgt.get('mcdc')
    table(['被测对象/Object', '用例版本/Case version', '语句覆盖/Statement', '分支覆盖/Branch',
           'MC/DC', '是否达标/Pass', '证据/Evidence'],
          [[spec.get('component', ''), date.today().isoformat(),
            cov.get('statement'), cov.get('branch'),
            '不适用/N.A. (ASIL %s)' % spec.get('asil', 'QM') if mcdc_target is None else cov.get('mcdc'),
            reached(cov.get('branch'), tgt.get('branch')),
            (spec.get('coverage_report_path', '') + ('  ' + coverage_gap() if coverage_gap() else ''))]],
          percent_cols={3, 4, 5})

    section('4. 测试实施情况总结/Summary of test implementation')
    total = len(cases)
    executed = cov.get('executed', 0) or 0
    passed = cov.get('passed', 0) or 0
    table(['测试轮次/Round', '测试对象/Object', '选择用例数/Selected', '执行用例数/Executed',
           '未执行用例数/Not executed', '通过用例数/Passed', '用例执行率/Execution rate',
           '测试通过率/Pass rate'],
          [['一轮测试/First round', spec.get('component', ''), total, executed,
            total - executed, passed,
            (executed / total) if total else 0, (passed / executed) if executed else 0]],
          percent_cols={7, 8})

    section('5. 缺陷解决情况总结/Summary of defect resolution')
    table(['发现的缺陷个数/Found', '修正的缺陷个数/Corrected', '未修正的缺陷个数/Uncorrected',
           '整体分析/Overall analysis'],
          [[cov.get('defects_found', 0), cov.get('defects_fixed', 0),
            (cov.get('defects_found', 0) - cov.get('defects_fixed', 0)), '']])

    for col, width in zip('ABCDEFGH', (46, 26, 18, 20, 22, 18, 18, 16)):
        ws.column_dimensions[col].width = width

    if static.get('findings'):
        sv = _sheet(wb, '静态验证结果', 'static validation') or wb.create_sheet('静态验证结果')
        _reset_sheet(sv)
        head = ['序号/No.', '规范/Rule', '文件/File', '行/Line', '严重度/Severity',
                '说明/Description', '是否符合/Compliant']
        for i, h in enumerate(head, 1):
            sv.cell(row=1, column=i, value=h)
        _style_header(sv, 1, len(head))
        for n, f in enumerate(static['findings'], 1):
            for i, key in enumerate(['rule', 'file', 'line', 'severity', 'message'], 2):
                sv.cell(row=1 + n, column=i, value=f.get(key, ''))
            sv.cell(row=1 + n, column=1, value=n)
            sv.cell(row=1 + n, column=7, value='Fail')
        for col, width in zip('ABCDEFG', (8, 28, 40, 8, 12, 70, 14)):
            sv.column_dimensions[col].width = width

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cases', type=Path, required=True)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--spec', type=Path, required=True)
    ap.add_argument('--static', type=Path, help='static analysis result json')
    ap.add_argument('--coverage', type=Path, help='coverage/execution result json')
    ap.add_argument('--root', type=Path, default=Path('.'), help='project root for template paths')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--only', choices=['cases', 'trace', 'report'])
    args = ap.parse_args()

    cases = json.loads(args.cases.read_text(encoding='utf-8'))['cases']
    model = json.loads(args.model.read_text(encoding='utf-8'))
    spec = json.loads(args.spec.read_text(encoding='utf-8'))
    static = json.loads(args.static.read_text(encoding='utf-8')) if args.static and args.static.is_file() else None
    coverage = json.loads(args.coverage.read_text(encoding='utf-8')) if args.coverage and args.coverage.is_file() else None

    outdir = args.root / spec.get('output_dir', 'unit_test')
    comp = spec.get('component', 'component')
    tpl = spec.get('templates', {})

    def tpl_path(key: str) -> Path | None:
        p = tpl.get(key)
        return (args.root / p) if p else None

    want = {args.only} if args.only else {'cases', 'trace', 'report'}
    if 'cases' in want:
        print('cases :', build_cases(cases, spec, outdir / f'{comp}_软件单元测试用例.xlsx'))
    if 'trace' in want:
        print('trace :', build_trace(cases, model, spec, tpl_path('trace'),
                                     outdir / f'{comp}_软件单元测试追溯矩阵.xlsx'))
    if 'report' in want:
        print('report:', build_report(cases, model, spec, static, coverage, tpl_path('report'),
                                      outdir / f'{comp}_软件单元测试报告.xlsx'))
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Build the reviewable execution / coverage evidence report.

The three Excel deliverables state *results*; a reviewer also has to be able to
see the *process* behind them - which test ran, what it fed in, what it
expected, and which source lines the run actually reached.  Commercial tools
ship that as one page (VectorCAST's "full report").  This script assembles the
same thing from the open-source chain:

  gcovr --html-details   -> line-by-line annotated source   (Aggregate Coverage)
  gcovr --json           -> per-function statement/branch   (Metrics)
  Ceedling .pass/.fail   -> per-test verdict and duration   (Testcase Management)
  cases.json             -> inputs and expectations         (Test Case Data)
  static.json            -> cyclomatic complexity           (Metrics)

What this chain does and does not reproduce of a commercial tool's report is a
verification-strategy question, not per-module evidence, so it is documented
once in references/tool-migration.md and deliberately kept out of the generated
page: a controlled deliverable states facts about the software under test, not
arguments about the toolchain.

Never emit a page that looks fine but is empty: the Ceedling gcov plugin's own
report does exactly that under the whole-translation-unit pattern, which is the
defect this script exists to replace.  Any gcovr failure exits non-zero.

Usage:
  python build_evidence.py --spec ut_spec.json --build unit_test/<c>/build \
      --cases cases.json --model swdd_model.json --static static.json \
      --coverage coverage.json --root .
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_coverage import _gcovr_cmd          # same filter contract, on purpose

# Marker comments above each test, in the three shapes the deliverables use:
#   /* O2_UpdatePressGate.004 - covers branch 1: why this case exists */
#   /* SUT-00007 O2_SanitizeSeatGear.001 - covers branch 1 */      (id first)
#   /* SUT-00011..15 O2_GearToDuty.001..005 - covers branches 1..5 */
#       (a range documenting the run of test functions that follows)
# A case reference may sit anywhere in the comment, so it is searched for
# rather than anchored, and every hit is validated against the real case
# names - which is what keeps incidental text such as "SWE.4" out.
COMMENT_RE = re.compile(r'^\s*(?:/\*|\*)')
CASE_REF_RE = re.compile(r'([A-Za-z_]\w*)\.(\d{1,3})(?:\s*\.\.\s*(\d{1,3}))?')
MARKER_BRANCH_RE = re.compile(r'covers\s+branch(?:es)?\s+([\d/,\s]+)')
# A supplementary test exists beyond the generated case set - extra coverage a
# reviewer should see declared rather than discover.  It states what it adds,
# not a whole path, so it is never matched against a case's branch set.
MARKER_ADDS_RE = re.compile(r'adds\s+branch(?:es)?\s+([\d/,\s]+)')
MARKER_SUPP_RE = re.compile(r'supplementary|补充测试', re.I)
TEST_DEF_RE = re.compile(r'^\s*(?:static\s+)?void\s+(test_\w+)\s*\(')


def source_filters(spec: dict) -> list[str]:
    """Identical to collect_coverage: full path, never a bare directory name."""
    filters = [f'.*{re.escape(Path(d).as_posix())}/.*\\.c$'
               for d in spec.get('source_dirs', [])]
    return filters or ['.*\\.c$']


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, errors='replace')


def annotated_source(build: Path, root: Path, filters: list[str],
                     out_dir: Path, title: str) -> tuple[Path | None, str]:
    """gcovr's per-line annotated pages - the Aggregate Coverage equivalent."""
    cov_dir = out_dir / 'coverage'
    cov_dir.mkdir(parents=True, exist_ok=True)
    index = cov_dir / 'index.html'
    proc = _run(_gcovr_cmd(build, root, filters)
                + ['--html-details', str(index), '--html-title', title])
    if proc.returncode != 0 or not index.is_file():
        return None, (proc.stderr or 'gcovr produced no HTML').strip()[:400]
    return index, ''


def per_function_metrics(build: Path, root: Path,
                         filters: list[str]) -> tuple[list[dict], str]:
    """Statements and branches per function, aggregated from gcovr's line data.

    gcovr's JSON lists functions and lines separately, and only the line
    entries carry `function_name` - so the per-function totals that VectorCAST
    prints in its Metrics table have to be summed here.
    """
    proc = _run(_gcovr_cmd(build, root, filters) + ['--json', '-'])
    if proc.returncode != 0 or not proc.stdout.strip():
        return [], (proc.stderr or 'gcovr produced no JSON').strip()[:400]
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return [], f'cannot parse gcovr JSON: {exc}'

    acc: dict[str, dict] = {}

    def slot(name: str, filename: str) -> dict:
        return acc.setdefault(name, {
            'unit': name, 'file': filename, 'lineno': None, 'calls': 0,
            'st_total': 0, 'st_cov': 0, 'br_total': 0, 'br_cov': 0})

    for f in data.get('files', []):
        fname = f.get('file', '')
        for fn in f.get('functions', []):
            row = slot(fn.get('name', ''), fname)
            row['lineno'] = fn.get('lineno')
            row['calls'] = fn.get('execution_count', 0)
        for line in f.get('lines', []):
            name = line.get('function_name')
            if not name:
                continue
            row = slot(name, fname)
            row['st_total'] += 1
            if (line.get('count') or 0) > 0:
                row['st_cov'] += 1
            for br in line.get('branches') or []:
                row['br_total'] += 1
                if (br.get('count') or 0) > 0:
                    row['br_cov'] += 1

    return sorted(acc.values(), key=lambda r: (r['file'], r['lineno'] or 0)), ''


def per_test_results(build: Path) -> list[dict]:
    """Every executed test with its verdict, from Ceedling's result files.

    collect_coverage.test_counts() reads the same files for the totals only;
    the detail is what turns a bare "79/79 passed" into a reviewable list.
    """
    status_of = {'successes': 'PASS', 'failures': 'FAIL', 'ignores': 'IGNORED'}
    out: list[dict] = []
    for results in (build / 'test' / 'results', build / 'gcov' / 'results'):
        files = sorted(list(results.glob('*.pass')) + list(results.glob('*.fail')))             if results.is_dir() else []
        if not files:
            # `ceedling gcov:all` leaves build/test/results present but empty;
            # taking it would report zero tests while the results sit next door.
            continue
        for path in files:
            text = path.read_text(encoding='utf-8', errors='replace')
            m = re.search(r':file:\s*(\S+)', text)
            src = m.group(1) if m else path.stem
            section, cur = None, None
            for raw in text.splitlines():
                s = raw.strip()
                if s in (':successes:', ':failures:', ':ignores:'):
                    section = s.strip(':')
                    continue
                if s.startswith('- :test:'):
                    cur = {'test': s.split(':test:', 1)[1].strip(), 'source': src,
                           'status': status_of.get(section, '?'),
                           'line': '', 'message': '', 'time': ''}
                    out.append(cur)
                    continue
                if cur is None:
                    continue
                for key, field in ((':line:', 'line'), (':message:', 'message'),
                                   (':unity_test_time:', 'time')):
                    if s.startswith(key):
                        cur[field] = s.split(key, 1)[1].strip().strip("'")
        break        # build/test wins over build/gcov; they duplicate each other
    return out


def case_refs(line: str, known: dict) -> list:
    """Every real case name referenced by one comment line, in order.

    `O2_GearToDuty.001..005` expands to the five names it abbreviates; a marker
    written that way documents the whole run of test functions beneath it.
    Anything that is not an actual case name is dropped, which is what keeps
    incidental text such as "SWE.4" or "SUT-00011..15" out of the mapping.
    """
    found = []
    for unit, first, last in CASE_REF_RE.findall(line):
        width = len(first)
        lo, hi = int(first), int(last or first)
        if hi < lo or hi - lo > 99:
            continue
        for n in range(lo, hi + 1):
            name = '%s.%0*d' % (unit, width, n)
            if name in known and name not in found:
                found.append(name)
    return found


def map_tests_to_cases(spec: dict, root: Path, known: dict) -> dict:
    """Test function -> the case it implements, via the marker comment.

    The marker above each test is the mandated convention in
    references/ceedling-setup.md.  Deliberately NOT falling back to the
    function name: test functions are numbered independently of the cases they
    implement - test_O2_UpdatePressGate_001 implements case
    O2_UpdatePressGate.004 - so guessing from the name would map silently and
    wrongly.  A test whose marker names no case is reported unmapped, which is
    the honest outcome for a test written beyond the generated case set.

    `known` maps case name -> unit name.  A queued case is only handed to a
    test whose own name carries that unit, so a marker range that runs out
    cannot bleed into the next unit's tests.
    """
    units = sorted(set(known.values()), key=len, reverse=True)

    def unit_of(test: str):
        body = test[len('test_'):] if test.startswith('test_') else test
        return next((u for u in units if body.startswith(u + '_') or body == u), None)

    out_dir = root / spec.get('output_dir', 'unit_test')
    mapping = {}
    for src in sorted((out_dir / 'test').glob('test_*.c')):
        queue, branches, group, adds, supp = [], '', False, '', False
        last_comment = -10
        for lineno, raw in enumerate(
                src.read_text(encoding='utf-8', errors='replace').splitlines()):
            if COMMENT_RE.match(raw):
                if lineno - last_comment > 1:
                    # A new comment block starts here.  `supplementary` and
                    # `adds branches` describe one test and must not survive the
                    # block they were written in, otherwise a file header that
                    # merely explains the convention mislabels the first test
                    # below it.  The case queue is deliberately NOT reset: one
                    # marker may document a run of the tests that follow.
                    adds, supp = '', False
                last_comment = lineno
                refs = case_refs(raw, known)
                if refs:
                    queue, branches = refs, ''
                    group = len(refs) > 1
                if MARKER_SUPP_RE.search(raw):
                    supp = True
                ma = MARKER_ADDS_RE.search(raw)
                if ma:
                    adds = ' '.join(ma.group(1).split())
                    supp = True
                mb = MARKER_BRANCH_RE.search(raw)
                if mb and not group:
                    # A marker covering several cases at once ("...001..005 -
                    # covers branches 1..5") states the branches of the group,
                    # not of any one test.  Attaching that text to each test
                    # would assert a coverage the test does not have, so the
                    # per-test branch set is left unknown instead.
                    branches = ' '.join(mb.group(1).split())
                continue
            md = TEST_DEF_RE.match(raw)
            if not md:
                continue
            test = md.group(1)
            # `supplementary` / `adds branches` must sit in the comment block
            # directly above the function.  A queued case name may legitimately
            # come from further up (one marker can document a run of tests), but
            # a supplementary declaration cannot: the word appearing anywhere
            # earlier in the file - a file header explaining the convention, say
            # - would otherwise mislabel the next test it meets.
            if lineno - last_comment > 1:
                adds, supp = '', False
            case_name = None
            if queue and known.get(queue[0]) == unit_of(test):
                case_name = queue.pop(0)
            elif queue:
                queue = []          # the range ended; do not bleed across units
            mapping[test] = {'case_name': case_name, 'branches': branches,
                             'adds': adds, 'supp': supp, 'file': src.name}
            if not queue:
                branches, group = '', False
            adds, supp = '', False
    return mapping


def _resolve_tool(name: str) -> str | None:
    """Absolute path of a CLI tool, tolerating the Windows launcher suffixes.

    Ruby and npm install their entry points as `<name>.bat` / `<name>.cmd`, and
    `subprocess` without a shell does not apply PATHEXT, so a bare name can miss
    a tool that works fine when typed in a terminal.
    """
    suffixes = ("", ".bat", ".cmd", ".exe") if os.name == "nt" else ("",)
    for suffix in suffixes:
        found = shutil.which(name + suffix)
        if found:
            return found
    return None


VERSION_LINE_RE = re.compile(r'\d+\.\d+')


def _version_text(name: str, output: str) -> str:
    """Pull the version out of a tool banner.

    "first non-empty line" is not enough: `ceedling version` opens with
    "Welcome to Ceedling!" and prints the number further down, so the first
    line that actually carries a version is taken instead.  For Ceedling the
    bundled CMock and Unity versions are recorded too - they are part of the
    framework that produced the results.
    """
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if not lines:
        return '未返回版本号/no version reported'
    versioned = [ln for ln in lines if VERSION_LINE_RE.search(ln)]
    if not versioned:
        return lines[0]
    if name == 'ceedling':
        wanted = [ln for ln in versioned
                  if ln.split('=>')[0].strip() in ('Ceedling', 'CMock', 'Unity')]
        if wanted:
            return '; '.join(wanted)
    return versioned[0]


def tool_versions(spec: dict) -> list[tuple[str, str]]:
    """Versions of the toolchain that produced these results.

    A controlled deliverable has to record *which* tools ran, so the path may
    be pinned per project under `spec["tools"]`.  That matters when a tool is
    installed but not on PATH - Ceedling ships as a Ruby gem shim and its bin
    directory is frequently left off the system PATH, which would otherwise
    print "not found" right next to the test results it produced and invite an
    obvious review question.
    """
    pinned = spec.get('tools') or {}
    probes = [('gcovr', [sys.executable, '-m', 'gcovr', '--version']),
              ('gcc', ['gcc', '--version']),
              ('ceedling', ['ceedling', 'version']),
              ('cppcheck', ['cppcheck', '--version'])]
    rows = []
    for name, cmd in probes:
        override = pinned.get(name)
        if override:
            exe = str(Path(override).expanduser())
            if not Path(exe).exists():
                rows.append((name, f'配置的路径不存在/pinned path missing: {exe}'))
                continue
            cmd = [exe] + cmd[1:]
        elif cmd[0] != sys.executable:
            resolved = _resolve_tool(cmd[0])
            if resolved is None:
                rows.append((name, '不在 PATH 上/not on PATH — '
                                   '可在 ut_spec.json 的 "tools" 中钉住其路径'))
                continue
            cmd = [resolved] + cmd[1:]
        try:
            proc = _run(cmd)
            text = (proc.stdout or '') + (proc.stderr or '')
            rows.append((name, _version_text(name, text)))
        except OSError as exc:
            rows.append((name, f'调用失败/call failed: {exc}'))
    return rows


# ---------------------------------------------------------------- rendering --

CSS = """
body{font-family:"Segoe UI","Microsoft YaHei",Arial,sans-serif;margin:0;
  background:#f5f6f8;color:#23272b;font-size:14px;line-height:1.55}
.wrap{max-width:1180px;margin:0 auto;padding:24px 28px 64px}
h1{font-size:26px;margin:0 0 4px;border-bottom:3px solid #b0b6bc;padding-bottom:10px}
h2{font-size:19px;margin:34px 0 10px;border-bottom:1px solid #ccd2d8;padding-bottom:6px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;margin:10px 0 18px;background:#fff}
th,td{border:1px solid #d7dbe0;padding:6px 9px;text-align:left;vertical-align:top}
th{background:#e8edf3;font-weight:600;white-space:nowrap}
td.num{text-align:right;white-space:nowrap}
tr:nth-child(even) td{background:#fafbfc}
.pass{color:#1a7f37;font-weight:600}
.fail{color:#b70032;font-weight:600}
.warn{background:#fff4e5;border-left:4px solid #e08a00;padding:10px 14px;margin:14px 0}
.err{background:#fdecec;border-left:4px solid #b70032;padding:10px 14px;margin:14px 0}
.ok{background:#eaf6ec;border-left:4px solid #1a7f37;padding:10px 14px;margin:14px 0}
.meta{color:#5b6470;font-size:13px}
pre{margin:0;font-family:Consolas,monospace;font-size:12.5px;white-space:pre-wrap}
.kv td:first-child{width:230px;font-weight:600;background:#f2f5f8}
a{color:#0b5cad}
"""


class Raw(str):
    """Marks a cell whose content is already escaped HTML."""


def esc(v) -> str:
    return html.escape('' if v is None else str(v))


def pct(cov, total) -> str:
    return f'{cov}/{total} ({cov / total * 100:.1f}%)' if total else f'{cov}/0 (-)'


def table(head: list[str], rows: list[list], numeric: set[int] | None = None,
          cls: str = '') -> str:
    numeric = numeric or set()
    out = [f'<div class="scroll"><table{f" class={cls!r}" if cls else ""}><thead><tr>'
           + ''.join(f'<th>{esc(h)}</th>' for h in head) + '</tr></thead><tbody>']
    for row in rows:
        cells = []
        for i, v in enumerate(row, 1):
            attr = ' class="num"' if i in numeric else ''
            cells.append(f'<td{attr}>{v if isinstance(v, Raw) else esc(v)}</td>')
        out.append('<tr>' + ''.join(cells) + '</tr>')
    out.append('</tbody></table></div>')
    return '\n'.join(out)


def verdict(status: str) -> Raw:
    cls = 'pass' if status == 'PASS' else ('fail' if status == 'FAIL' else 'meta')
    return Raw(f'<span class="{cls}">{esc(status)}</span>')


def render(ctx: dict) -> str:
    spec, cov, cases, static = ctx['spec'], ctx['coverage'], ctx['cases'], ctx['static']
    tgt = spec.get('coverage_targets', {})
    p: list[str] = [
        '<!doctype html><html lang="zh"><head><meta charset="utf-8">',
        f'<title>{esc(ctx["title"])}</title><style>{CSS}</style></head>',
        '<body><div class="wrap">',
        f'<h1>{esc(ctx["title"])}</h1>',
        f'<p class="meta">生成时间/Generated {esc(ctx["now"])} &nbsp;|&nbsp; '
        f'ASIL {esc(spec.get("asil", "QM"))} &nbsp;|&nbsp; '
        '本报告是 AU-QR-R&amp;D-048 软件单元测试报告的证据附件，'
        '报告中的每一项指标都可在此逐条核对。</p>',
    ]
    for msg in ctx['errors']:
        p.append(f'<div class="err"><b>数据采集失败/Collection failed：</b>{esc(msg)}</div>')

    # 1 -----------------------------------------------------------------
    p.append('<h2>1. 配置数据/Configuration Data</h2>')
    mcdc = tgt.get('mcdc')
    p.append(table(['项/Item', '值/Value'], [
        ['项目/Project', spec.get('project', '')],
        ['被测组件/Component under test', spec.get('component', '')],
        ['软件详细设计/SWDD', spec.get('swdd', '')],
        ['源码目录/Source dirs', '; '.join(spec.get('source_dirs', []))],
        ['覆盖率目标/Coverage target',
         f"statement {tgt.get('statement', 1.0):.0%}, branch {tgt.get('branch', 1.0):.0%}, "
         f"MC/DC {'不适用/N.A.' if mcdc is None else format(mcdc, '.0%')}"],
    ] + [[f'工具/Tool - {n}', v] for n, v in ctx['tools']], cls='kv'))

    # 2 -----------------------------------------------------------------
    p.append('<h2>2. 总体结果/Overall Results</h2>')
    dc = cov.get('design_coverage')
    p.append(table(['指标/Metric', '结果/Result', '判定/Verdict'], [
        ['测试用例/Test cases', f"{cov.get('passed', 0)} / {cov.get('selected', 0)}",
         verdict('PASS' if cov.get('selected')
                 and cov.get('passed') == cov.get('selected')
                 and not cov.get('failed') else 'FAIL')],
        ['测试函数/Test functions', f"{ctx['tests_passed']} / {len(ctx['tests'])}",
         verdict('PASS' if ctx['tests'] and not ctx['tests_failed'] else 'FAIL')],
        ['语句覆盖/Statement coverage',
         pct(cov.get('lines_covered', 0), cov.get('lines_total', 0)),
         verdict('PASS' if (cov.get('statement') or 0) >= (tgt.get('statement') or 1)
                 else 'FAIL')],
        ['分支覆盖/Branch coverage',
         pct(cov.get('branches_covered', 0), cov.get('branches_total', 0)),
         verdict('PASS' if (cov.get('branch') or 0) >= (tgt.get('branch') or 1) else 'FAIL')],
        ['详设单元追溯/Design units traced',
         f"{ctx['units_traced']} / {ctx['units_total']}"
         + (f' ({dc:.1%})' if isinstance(dc, float) else ''),
         verdict('PASS' if dc == 1 else 'FAIL')],
        ['圈复杂度上限/Max cyclomatic complexity',
         f"{static.get('cyclomatic_max_found', '-')} "
         f"(限值/limit {static.get('cyclomatic_limit', '-')})",
         verdict('PASS' if static.get('cyclomatic_ok') else 'FAIL')],
        ['MISRA C:2012', static.get('misra_summary', '-'),
         verdict('PASS' if static.get('misra_ok') else 'FAIL')],
    ]))
    if cov.get('note'):
        p.append(f'<div class="warn">{esc(cov["note"])}</div>')

    # 3 -----------------------------------------------------------------
    p.append('<h2>3. 用例执行清单/Testcase Management</h2>')
    # One row per test function, because each carries its own verdict and
    # duration - that is the evidence this section exists to provide.  Several
    # tests may implement one case (a second input value for the same path), so
    # the repeated unit/case cells are blanked on the continuation rows and the
    # group reads as one block without hiding any individual result.
    exec_rows = []
    prev_case = None
    for n, t in enumerate(ctx['rows_exec'], 1):
        same = t['case_id'] != '—' and t['case_id'] == prev_case
        exec_rows.append([n,
                          '' if same else t['unit'],
                          '' if same else t['case_id'],
                          '' if same else t['case_name'],
                          t['test'], t['branches'], t['time'],
                          verdict(t['status'])])
        prev_case = t['case_id']
    p.append(table(['序号/No.', '软件单元/Unit', '用例ID/Case ID', '用例名称/Case',
                    '测试函数/Test function', '覆盖分支号/Branch IDs', '耗时/Time(s)',
                    '结果/Result'], exec_rows, numeric={1, 7}))
    # "2/3" is two branch numbers, not two-thirds.  The slash is kept because it
    # is the separator the SWDD test target and the case table already use, so
    # the three documents read alike; the ambiguity is removed by the header and
    # this note rather than by diverging from them.
    p.append('<p class="meta">“覆盖分支号”列是该测试走过的详设分支编号，以 / 分隔，'
             '<b>不是分数</b>。位数不同是路径长度不同所致：在前面的判断处提前返回的路径，'
             '经过的判断本来就少。</p>')

    extra = [t for t in ctx['unmapped'] if t['branches']]
    bare = [t for t in ctx['unmapped'] if not t['branches']]
    if ctx['extra_tests']:
        p.append('<div class="ok"><b>补充测试/Supplementary tests '
                 f'({len(ctx["extra_tests"])})：</b>'
                 '用例集之外的额外测试，已在注释中声明，属正常情况。<ul>'
                 + ''.join(f'<li><code>{esc(t["test"])}</code>'
                           + (f' — 新增分支 {esc(t["branches"])}' if t['branches'] else '')
                           + f' <span class="meta">({esc(t["source"])})</span></li>'
                           for t in ctx['extra_tests']) + '</ul></div>')
    if extra:
        p.append('<div class="warn"><b>覆盖了分支但没有对应用例的测试/Tests covering '
                 'branches with no matching case：</b>'
                 '这些测试声明了覆盖分支，却匹配不到用例表中的任何一条。'
                 '常见原因是用例生成器枚举出的路径在源码上不可行，实现时改走了可行路径，'
                 '但用例表没有同步更新。跑 <code>reconcile_cases.py</code> 修。<ul>'
                 + ''.join(f'<li><code>{esc(t["test"])}</code> — 覆盖分支 '
                           f'{esc(t["branches"])} <span class="meta">'
                           f'({esc(t["source"])})</span></li>' for t in extra)
                 + '</ul></div>')
    if bare:
        p.append('<div class="warn"><b>缺少标记注释的测试/Tests without a marker '
                 'comment：</b>请在函数上方补 '
                 '<code>/* &lt;单元&gt;.NNN - covers branch N */</code>。'
                 '评审检查单第 19/20 项要求测试脚本与用例可逐条对应。<ul>'
                 + ''.join(f'<li><code>{esc(t["test"])}</code> '
                           f'<span class="meta">({esc(t["source"])})</span></li>'
                           for t in bare) + '</ul></div>')
    if not ctx['unmapped']:
        p.append('<div class="ok">全部测试函数均已通过标记注释关联到用例或声明为补充测试。</div>')

    if ctx['cases_untested']:
        p.append('<div class="warn"><b>无测试函数实现的用例/Cases with no test：</b>'
                 '追溯矩阵的正向追溯在这几条上是断的，交付前必须闭环。<ul>'
                 + ''.join(f'<li><code>{esc(c["case_name"])}</code>（{esc(c["unit_name"])}，'
                           f'{esc(c["test_target"])}）</li>' for c in ctx['cases_untested'])
                 + '</ul></div>')

    # 4 -----------------------------------------------------------------
    p.append('<h2>4. 用例明细/Test Case Detail</h2>')
    p.append('<p class="meta">逐条列出输入、期望与判定，字段与 AU-QR-R&amp;D-046 '
             '软件单元测试用例同名；步骤末尾的 <code>--N</code> 是该步命中的详设分支号。</p>')
    rows = []
    for c in cases:
        impl = ctx['case_to_tests'].get(c['case_name'], [])
        if not impl:
            status = '未执行/Not run'
        elif any(t['status'] == 'FAIL' for t in impl):
            status = 'FAIL'
        else:
            status = 'PASS'
        rows.append([
            c['case_id'], c['case_name'], c['unit_name'], c.get('priority', ''),
            c.get('test_method', ''), c.get('design_method', ''),
            c.get('test_target', ''), c.get('precondition', ''),
            Raw('<pre>' + esc(c.get('steps', '')) + '</pre>'),
            Raw('<pre>' + esc(c.get('expected', '')) + '</pre>'),
            Raw('<br>'.join(esc(t['test']) for t in impl) or '<span class="meta">-</span>'),
            verdict(status)])
    p.append(table(['用例ID/Case ID', '用例名称/Case', '软件单元/Unit', '优先级/Priority',
                    '测试方法/Test method', '设计方法/Design method', '测试目标/Target',
                    '预置条件/Precondition', '测试步骤/Steps', '预期输出/Expected',
                    '实现测试函数/Implemented by', '结果/Result'], rows))

    # 5 -----------------------------------------------------------------
    p.append('<h2>5. 代码指标/Metrics</h2>')
    p.append('<p class="meta">圈复杂度取自详设判定数（CCN = 判定数 + 1）；'
             '语句与分支由 gcovr 的逐行数据按函数聚合。'
             '“详设单元”为否的函数不在 SWDD 范围内，其未覆盖是预期的。</p>')
    p.append(table(['软件单元/Unit', '详设单元/In SWDD', '圈复杂度/Complexity',
                    '调用次数/Calls', '语句/Statements', '分支/Branches'],
                   [[m['unit'], '是/Yes' if m['unit'] in ctx['unit_names'] else '否/No',
                     ctx['ccn'].get(m['unit'], '-'), m['calls'],
                     pct(m['st_cov'], m['st_total']), pct(m['br_cov'], m['br_total'])]
                    for m in ctx['metrics']], numeric={3, 4}))

    # 6 -----------------------------------------------------------------
    p.append('<h2>6. 覆盖率明细/Coverage</h2>')
    if ctx['coverage_index']:
        p.append(f'<p><a href="{esc(ctx["coverage_index"])}">'
                 '打开逐行标注的源码覆盖率报告 / Open the line-by-line annotated source</a>'
                 '（gcovr --html-details）</p>')
    gaps = [f for f in (cov.get('coverage_files') or []) if f.get('uncovered_lines')]
    if gaps:
        p.append(table(['文件/File', '未覆盖行/Uncovered lines', '语句/Statements',
                        '分支/Branches'],
                       [[g['file'], g['uncovered_lines'],
                         pct(g.get('lines_covered', 0), g.get('lines_total', 0)),
                         pct(g.get('branches_covered', 0), g.get('branches_total', 0))]
                        for g in gaps]))
        p.append('<div class="warn">未覆盖行须逐条确认属于详设已排除的死代码或不可达的防御性分支，'
                 '并在 AU-QR-R&amp;D-048 的“未达成说明”列写明理由。</div>')
    else:
        p.append('<div class="ok">无未覆盖行。</div>')

    p.append('</div></body></html>')
    return '\n'.join(p)


# -------------------------------------------------------------------- main --

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', type=Path, required=True)
    ap.add_argument('--build', type=Path, required=True)
    ap.add_argument('--cases', type=Path, required=True)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--static', type=Path)
    ap.add_argument('--coverage', type=Path)
    ap.add_argument('--root', type=Path, default=Path('.'))
    ap.add_argument('-o', '--out', type=Path)
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text(encoding='utf-8'))
    cases = json.loads(args.cases.read_text(encoding='utf-8'))['cases']
    model = json.loads(args.model.read_text(encoding='utf-8'))
    static = (json.loads(args.static.read_text(encoding='utf-8'))
              if args.static and args.static.is_file() else {})
    coverage = (json.loads(args.coverage.read_text(encoding='utf-8'))
                if args.coverage and args.coverage.is_file() else {})

    out = args.out or (args.root / spec.get('output_dir', 'unit_test')
                       / 'report' / 'unit_verification_evidence.html')
    out.parent.mkdir(parents=True, exist_ok=True)

    title = f"{spec.get('component', '')} 软件单元验证证据报告 / Unit Verification Evidence"
    filters = source_filters(spec)
    errors: list[str] = []

    index, err = annotated_source(args.build, args.root, filters, out.parent, title)
    if err:
        errors.append(f'逐行覆盖率报告/annotated coverage: {err}')
    metrics, err = per_function_metrics(args.build, args.root, filters)
    if err:
        errors.append(f'每函数指标/per-function metrics: {err}')
    if not metrics and not errors:
        errors.append('gcovr 返回了 0 个函数：filter 与源码目录不匹配，报告将是空的')

    tests = per_test_results(args.build)
    by_name = {c['case_name']: c for c in cases}
    mapping = map_tests_to_cases(
        spec, args.root, {c['case_name']: c['unit_name'] for c in cases})

    rows_exec, unmapped, extra_tests = [], [], []
    case_to_tests: dict[str, list[dict]] = {}
    for t in tests:
        mark = mapping.get(t['test'], {})
        case_name = mark.get('case_name')
        case = by_name.get(case_name or '')
        supp = bool(mark.get('supp'))
        row = {**t,
               'unit': (case or {}).get('unit_name', ''),
               'case_id': (case or {}).get('case_id', '—'),
               'case_name': case_name or ('补充测试/supplementary' if supp else '—'),
               'branches': mark.get('branches') or mark.get('adds', ''),
               'supp': supp}
        rows_exec.append(row)
        if case:
            case_to_tests.setdefault(case_name, []).append(t)
        elif supp:
            extra_tests.append(row)
        else:
            unmapped.append(row)

    units = model.get('units', [])
    traced = {c['unit_name'] for c in cases}

    ctx = {
        'title': title,
        'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'spec': spec, 'coverage': coverage, 'cases': cases, 'static': static,
        'tools': tool_versions(spec),
        'tests': tests,
        'tests_passed': sum(1 for t in tests if t['status'] == 'PASS'),
        'tests_failed': sum(1 for t in tests if t['status'] == 'FAIL'),
        'rows_exec': rows_exec,
        'unmapped': unmapped,
        'extra_tests': extra_tests,
        'cases_untested': [c for c in cases if c['case_name'] not in case_to_tests],
        'case_to_tests': case_to_tests,
        'metrics': metrics,
        'ccn': {r['unit']: r['ccn'] for r in static.get('cyclomatic_rows', [])},
        'unit_names': {u['name'] for u in units},
        'units_total': len(units),
        'units_traced': sum(1 for u in units if u['name'] in traced),
        'coverage_index': (index.relative_to(out.parent).as_posix() if index else ''),
        'errors': errors,
    }

    out.write_text(render(ctx), encoding='utf-8')
    print(f'evidence: {out}')
    if index:
        print(f'coverage: {index}')
    print(f"tests {ctx['tests_passed']}/{len(tests)} passed, "
          f"{len(unmapped)} unmapped, {len(ctx['cases_untested'])} cases without a test")

    if errors:
        for e in errors:
            print(f'error: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

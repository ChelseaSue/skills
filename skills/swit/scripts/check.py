#!/usr/bin/env python3
"""Release gate for the SWE.5 work products. FAIL blocks release; WARN needs a look; TODO is human work.

Checks
  config        project name / author, templates resolvable, environment difference stated
  architecture  anchors without SAD ID, image-only diagrams not transcribed, unverified transcriptions
  cases         ID format SWIT-\\d{5}, unique, no draft/stale text, no placeholders, every anchor has a case
  results       every selected case has a verdict; NA only for SWE.6 transfers; a SWE.6 case is never Pass;
                tests without SWIT marker; markers naming unknown cases; failed cases without defect ID
  deliverables  the files due for the mode exist; no 【TBD / 人工填写 / template markers left inside them;
                regression mode produced 237 + 238 and no 236 for that round

Usage: check.py --project P --mode full|sad-change|execute|regression [--round 1] [--rounds 1 R1]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CASE_ID_RE, Project, load_json, utf8_console  # noqa: E402

LEFTOVER = re.compile(r'【TBD|人工填写|【样本示例|【填写说明|待填')
DUE = {'full': ['strategy', 'guide', 'cases', 'trace', 'record', 'report'],
       'sad-change': ['strategy', 'guide', 'cases', 'trace', 'record', 'report'],
       'execute': ['record', 'report'],
       'regression': ['regression', 'report']}


def out_file(prj, key, rnd=''):
    name = prj.get(f'output.names.{key}').format(project=prj.get('project.name') or 'PROJECT', round=rnd)
    base = prj.resolve(prj.get('output.dir')) if prj.get('output.dir') else prj.wsp('out')
    return base / name


def scan_leftovers(path: Path):
    hits = []
    if path.suffix == '.xlsx':
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for v in row:
                    if isinstance(v, str) and LEFTOVER.search(v):
                        hits.append(f'{ws.title}: {v.strip()[:70]}')
    elif path.suffix == '.docx':
        import docx
        d = docx.Document(str(path))
        texts = [p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells]
        hits = [t.strip()[:70] for t in dict.fromkeys(texts) if LEFTOVER.search(t)]
    return hits


def run(prj: Project, mode: str, rnd_names):
    issues = []

    def add(level, msg):
        issues.append((level, msg))
    # ---- config
    if not prj.get('project.name'):
        add('FAIL', 'project.name 未配置')
    if not prj.get('project.author') or '【TBD' in str(prj.get('project.author')):
        add('TODO', 'project.author 未填写（用例作者/修订记录）')
    if not prj.get('environment_difference'):
        add('FAIL', 'environment_difference 为空：宿主机测试必须说明与目标环境的差异（AU-QW-R&D-40）')
    for key in DUE[mode]:
        try:
            prj.template(key)
        except Exception as e:
            add('FAIL', f'模板 {key}: {e}')
    # ---- architecture
    model = load_json(prj.wsp('sad', 'arch_model.json'), default={})
    if not model:
        add('FAIL', '没有 arch_model.json：先 swit.py ingest')
        return issues
    for w in model.get('warnings', []):
        if w['code'] in ('NO-ID',):
            add('WARN', f"SAD: {w['msg']}")
        elif w['code'] in ('IMAGE-ONLY', 'UNVERIFIED'):
            add('TODO', f"SAD: {w['msg']}")
        elif w['level'] == 'FAIL':
            add('FAIL', f"SAD: {w['msg']}")
    # ---- cases
    reg = load_json(prj.wsp('cases', 'cases.json'), default={'cases': []})
    ids = [c['id'] for c in reg['cases']]
    bad = [i for i in ids if not CASE_ID_RE.match(i)]
    if bad:
        add('FAIL', f'用例 ID 不符合 SWIT-XXXXX：{", ".join(bad[:8])}')
    if len(ids) != len(set(ids)):
        add('FAIL', '用例 ID 重复')
    act = [c for c in reg['cases'] if c['status'] == 'Active']
    pend = [c['id'] for c in act if c.get('text_status') != 'filled']
    if pend:
        add('FAIL', f'{len(pend)} 条用例仍是草稿/待复核（draft/stale），不得进入交付物：{", ".join(pend[:8])}{" ..." if len(pend) > 8 else ""}')
    keys = {c['anchor_key'] for c in act}
    for cat, mk in (('interface', 'interfaces'), ('dynamic', 'dynamic'), ('resource', 'resource'), ('performance', 'performance')):
        miss = [a['name'] for a in model.get(mk, []) if a['key'] not in keys]
        if miss:
            add('FAIL', f'{cat}: {len(miss)} 个架构锚点没有用例：{", ".join(miss[:6])}')
    by = {c['id']: c for c in reg['cases']}
    # ---- results
    for rn in rnd_names:
        rp = prj.wsp('results', f'round_{rn}.json')
        if not rp.exists():
            add('FAIL', f'没有第 {rn} 轮结果 {rp.name}：先 swit.py run')
            continue
        rnd = load_json(rp)
        for cid in rnd['selected']:
            r = rnd['results'].get(cid)
            c = by.get(cid, {})
            if r is None:
                add('FAIL', f'{rn}: {cid} 没有判定')
                continue
            if r['verdict'] == 'na' and c.get('execution') != 'swe6':
                add('FAIL', f'{rn}: {cid} 判 NA 但不是转 SWE.6 的用例')
            if c.get('execution') == 'swe6' and r['verdict'] == 'pass':
                add('FAIL', f'{rn}: {cid} 是转 SWE.6 的用例却判 Pass（只能判 NA）')
            if r['verdict'] == 'fail' and not r.get('defects'):
                add('WARN', f'{rn}: {cid} 失败但未关联缺陷 ID（登记缺陷后写入 round_{rn}.json 的 defects）')
        nr = [cid for cid in rnd['selected'] if rnd['results'].get(cid, {}).get('verdict') == 'not_run']
        if nr:
            add('WARN', f'{rn}: {len(nr)} 条用例未执行（报告会如实统计执行率）')
        if rnd.get('unmarked_tests'):
            add('WARN', f"{rn}: 测试函数缺少 SWIT 标记：{', '.join(rnd['unmarked_tests'][:6])}")
        if rnd.get('unknown_case_ids'):
            add('FAIL', f"{rn}: 标记引用了不存在/已废弃的用例：{', '.join(rnd['unknown_case_ids'][:6])}")
        und = (rnd.get('coverage') or {}).get('undocumented_public_functions')
        if und:
            add('WARN', f"{rn}: 代码中有 SAD 未定义的公开函数（架构漂移，登记为发现）：{', '.join(und[:6])}")
    # ---- deliverables
    last = rnd_names[-1] if rnd_names else ''
    for key in DUE[mode]:
        rn = last if key in ('record', 'regression', 'report') else ''
        f = out_file(prj, key, rn)
        if not f.exists():
            add('FAIL', f'缺少交付物 {f.name}')
            continue
        left = scan_leftovers(f)
        if left:
            add('FAIL', f'{f.name}: {len(left)} 处仍有 【TBD/人工填写/模板示例 字样，例如「{left[0]}」')
    if mode == 'regression' and last:
        if out_file(prj, 'record', last).exists():
            add('FAIL', f'回归轮次 {last} 不应输出软件集成测试记录（236）')
    return issues


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--mode', required=True, choices=list(DUE))
    ap.add_argument('--round')
    ap.add_argument('--rounds', nargs='*')
    a = ap.parse_args()
    prj = Project(a.project)
    rounds = a.rounds or ([a.round] if a.round else [])
    issues = run(prj, a.mode, rounds)
    order = {'FAIL': 0, 'WARN': 1, 'TODO': 2}
    for lvl, msg in sorted(issues, key=lambda x: order[x[0]]):
        print(f'{lvl:4s} {msg}')
    n = sum(1 for l, _ in issues if l == 'FAIL')
    print(f'\n{n} FAIL, {sum(1 for l, _ in issues if l == "WARN")} WARN, {sum(1 for l, _ in issues if l == "TODO")} TODO'
          + ('  -> 不可发布' if n else '  -> 可提交评审'))
    return 1 if n else 0


if __name__ == '__main__':
    sys.exit(main())

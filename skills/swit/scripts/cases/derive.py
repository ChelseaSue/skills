#!/usr/bin/env python3
"""arch_model.json -> cases.json (the SWE.5 test case register).

Each architecture anchor opens one or more case *slots*:
  interface      one per interface (or per consumer with cases.per_consumer)
  dynamic        one per sequence diagram / mode; plus one per state transition (cases.per_transition)
  resource       one per anchor, execution by cases.resource_disposition (target-static | host | review)
  performance    one per anchor, execution by cases.performance_disposition (host | target-static | swe6)

The register is incremental and IDs are stable:
  - an existing slot keeps its SWIT ID; if the anchor content hash changed the case becomes
    text_status="stale" (Claude must re-check the text) and is listed as modified
  - a slot that disappeared from the SAD -> status="Obsolete" (ID never reused)
  - a new slot -> next free SWIT ID, text_status="draft" with a skeleton text

Skeleton text is only a starting point: concrete inputs, observation points and expected values
must come from the SAD constraints and source constants (case_text.json, merged by apply_text.py).

Usage: derive.py --project swit_project.json [--model ws/sad/arch_model.json] [--cases ws/cases/cases.json] [--summary]
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import Project, load_json, save_json, utf8_console  # noqa: E402

TEXT_FIELDS = ('name', 'target', 'precondition', 'steps', 'expected', 'criteria', 'design_method')


def _disposition(rules, name):
    for r in rules:
        if re.search(r['regex'], name or ''):
            return r['execution']
    return 'host'


# --------------------------------------------------------------------------- slots

def slots_from_model(model, prj: Project):
    per_consumer = prj.get('cases.per_consumer', False)
    per_transition = prj.get('cases.per_transition', True)
    out = []
    for itf in model['interfaces']:
        base = dict(category='interface', kind='interface', anchor=itf, component=itf['component'],
                    module=itf['module'], execution='host')
        consumers = itf['consumers'] or [None]
        if per_consumer and itf['consumers']:
            for c in consumers:
                out.append(dict(base, slot=f"{itf['key']}@{c}", consumer=c))
        else:
            out.append(dict(base, slot=itf['key'], consumer=None))
    for a in model['dynamic']:
        comp = _owner(a, model)
        out.append(dict(category='dynamic', kind=a['kind'], anchor=a, component=comp, module='',
                        execution='host', slot=a['key']))
        if per_transition and a['kind'] == 'state_machine':
            trans = list(a['transitions'])
            for d in a['diagrams']:
                trans += d.get('transitions', [])
            seen = set()
            for t in trans:
                k = f"{t['from']}->{t['to']}"
                if k in seen:
                    continue
                seen.add(k)
                out.append(dict(category='dynamic', kind='state_transition', anchor=a, component=comp,
                                module='', execution='host', slot=f"{a['key']}#{k}", transition=t))
    for a in model['resource']:
        out.append(dict(category='resource', kind='resource', anchor=a, component='', module='',
                        execution=_disposition(prj.get('cases.resource_disposition'), a['name']), slot=a['key']))
    for a in model['performance']:
        out.append(dict(category='performance', kind='performance', anchor=a, component='', module='',
                        execution=_disposition(prj.get('cases.performance_disposition'), a['name']), slot=a['key']))
    return out


def _owner(anchor, model):
    """Component that owns a dynamic behaviour: '... - ABBSM Component' style names, else ''."""
    shorts = {c['short'] for c in model['components']}
    for tok in re.findall(r'[A-Za-z][A-Za-z0-9_]+', anchor['name']):
        if tok in shorts:
            return tok
    return ''


# --------------------------------------------------------------------------- skeleton text

def skeleton(s, prj: Project, model):
    T = prj.text
    a = s['anchor']
    kind = s['kind']
    ex = s['execution']
    if kind == 'interface':
        cons = ', '.join(a['consumers']) or T('（SAD 依赖表未列出使用方，由测试直接驱动）', '(no consumer listed in the SAD dependency tables; driven by the test)')
        params = '; '.join(a['params_in']) or '/'
        return {
            'name': T(f"{a['name']} 接口集成测试", f"{a['name']} interface integration test"),
            'target': T(f"验证 {a['component']} 提供的接口 {a['signature']} 在与使用方（{cons}）集成后，参数/返回值的传递与架构定义一致",
                        f"Verify that interface {a['signature']} provided by {a['component']} passes parameters and return values "
                        f"consistently with the architecture definition when integrated with its consumers ({cons})"),
            'precondition': T(f"{a['component']} 及其使用方以真实代码链接；边界组件以桩替代；{a['component']} 已完成初始化",
                              f"{a['component']} and its consumers linked with real code; boundary components stubbed; "
                              f"{a['component']} initialised"),
            'steps': T(f"1. 初始化被集成组件\n2. 以有效等价类输入调用 {a['name']}（入参：{params}）\n"
                       f"3. 以边界值/无效值输入调用 {a['name']}\n4. 在使用方观察接收到的数据与返回值",
                       f"1. Initialise the integrated components\n2. Call {a['name']} with valid-class inputs (in: {params})\n"
                       f"3. Call {a['name']} with boundary / invalid inputs\n4. Observe the data and return value received by the consumer"),
            'expected': T(f"返回值：{a['returns'] or '/'}；使用方接收值与提供方输出一致",
                          f"Return value: {a['returns'] or '/'}; the value received by the consumer equals the provider output"),
            'criteria': T('使用方接收值 == 提供方返回值；返回码符合架构定义；无非预期的边界调用',
                          'Consumer-side value == provider return; return code as defined in the architecture; no unexpected boundary calls'),
            'design_method': T('基于需求分析、接口分析、等价类、边界值', 'Requirement analysis, interface analysis, equivalence partitioning, boundary value analysis'),
        }
    if kind == 'state_transition':
        t = s['transition']
        return {
            'name': T(f"{a['name']}：{t['from']} → {t['to']} 状态转移", f"{a['name']}: transition {t['from']} -> {t['to']}"),
            'target': T(f"验证集成后满足条件「{t['label'] or '见 SAD'}」时由 {t['from']} 转移到 {t['to']}",
                        f"Verify that the integrated software moves from {t['from']} to {t['to']} when "
                        f"'{t['label'] or 'see SAD'}' holds"),
            'precondition': T(f"软件处于 {t['from']}", f"Software in {t['from']}"),
            'steps': T(f"1. 使软件进入 {t['from']}\n2. 施加转移条件：{t['label'] or '见 SAD'}\n3. 推进调度节拍直至判定窗口结束\n4. 读取当前模式/状态",
                       f"1. Bring the software into {t['from']}\n2. Apply the transition condition: {t['label'] or 'see SAD'}\n"
                       f"3. Advance scheduler ticks until the decision window has elapsed\n4. Read the current mode/state"),
            'expected': T(f"状态为 {t['to']}；条件不满足时保持 {t['from']}", f"State is {t['to']}; stays in {t['from']} while the condition is false"),
            'criteria': T('状态与转移条件表一致，无中间非法状态', 'State matches the transition table; no illegal intermediate state'),
            'design_method': T('基于需求分析、状态转移分析', 'Requirement analysis, state transition analysis'),
        }
    if s['category'] == 'dynamic':
        steps_en, steps_zh = [], []
        msgs = [m for d in a['diagrams'] for m in d.get('messages', []) if not m.get('reply')]
        for i, m in enumerate(msgs[:20], 1):
            steps_en.append(f"{i}. {m['from']} -> {m['to']}: {m['label']}")
            steps_zh.append(f"{i}. {m['from']} → {m['to']}：{m['label']}")
        if not msgs:
            hint = [h for x in a.get('diagram_hints', []) for h in x['texts'] if '(' in h][:12]
            steps_en = [f"{i}. Trigger / observe {h}" for i, h in enumerate(hint, 1)] or ['1. 【TBD】 derive the steps from the SAD sequence diagram']
            steps_zh = [f"{i}. 触发/观察 {h}" for i, h in enumerate(hint, 1)] or ['1. 【TBD】按 SAD 时序图派生步骤']
        return {
            'name': T(f"{a['name']} 时序集成测试", f"{a['name']} integration test"),
            'target': T(f"验证集成后「{a['name']}」的跨组件交互顺序、数据传递与 SAD 动态行为一致",
                        f"Verify that the cross-component interaction order and data flow of '{a['name']}' match the SAD dynamic behaviour"),
            'precondition': T('参与组件以真实代码链接，边界以桩替代，调度节拍由测试驱动', 'Participating components linked with real code, boundary stubbed, scheduler tick driven by the test'),
            'steps': T('\n'.join(steps_zh), '\n'.join(steps_en)),
            'expected': T('各步骤调用按时序图顺序发生，传递的数据与架构定义一致', 'Calls occur in the order of the sequence diagram and the data passed matches the architecture'),
            'criteria': T('单周期内调用顺序为时序图的子序列；观察值与期望一致', 'Within one cycle the observed call order is a subsequence of the diagram; observed values equal expected'),
            'design_method': T('基于需求分析、时序分析', 'Requirement analysis, sequence analysis'),
        }
    # resource / performance
    meas = '; '.join(m['text'] for m in a['measures'][:6]) or T('见 SAD', 'see SAD')
    if ex == 'swe6':
        return {
            'name': T(f"{a['name']} 目标机测量（转 SWE.6）", f"{a['name']} target measurement (transferred to SWE.6)"),
            'target': T(f"验证「{a['name']}」满足 {meas}", f"Verify '{a['name']}' meets {meas}"),
            'precondition': T('目标硬件、调试器/示波器可用', 'Target hardware with debugger / oscilloscope available'),
            'steps': T('1. 在目标硬件上运行集成软件\n2. 以 GPIO 翻转/周期计数器测量\n3. 记录最大值', '1. Run the integrated software on target\n2. Measure via GPIO toggle / cycle counter\n3. Record the maximum'),
            'expected': T(f"测量值满足 {meas}", f"Measured value meets {meas}"),
            'criteria': T('需目标硬件测量，本过程判定 用例不适用NA，转 SWE.6 验证', 'Needs target measurement: verdict NA in SWE.5, verified in SWE.6'),
            'design_method': T('基于需求分析', 'Requirement analysis'),
        }
    if ex == 'target-static':
        return {
            'name': T(f"{a['name']} 资源核算", f"{a['name']} resource check"),
            'target': T(f"以目标机构建产物（链接 map / 栈用量）核算「{a['name']}」满足 {meas}",
                        f"Check '{a['name']}' against {meas} from the target build artefacts (linker map / stack usage)"),
            'precondition': T('目标机构建成功，生成 map 文件与 .su 文件', 'Target build succeeded; map file and .su files generated'),
            'steps': T('1. 解析链接 map，统计 ROM/RAM 按段/按组件用量\n2. 解析 .su 计算最坏栈深\n3. 与 SAD 预算比较',
                       '1. Parse the linker map; sum ROM/RAM by section and component\n2. Parse .su files; compute worst-case stack\n3. Compare with the SAD budget'),
            'expected': T(f"用量满足 {meas}", f"Usage within {meas}"),
            'criteria': T('实测用量 ≤ 预算', 'Measured usage <= budget'),
            'design_method': T('基于需求分析、静态分析', 'Requirement analysis, static analysis'),
        }
    if ex == 'review':
        return {
            'name': T(f"{a['name']} 集成检查", f"{a['name']} integration review"),
            'target': T(f"检查集成后「{a['name']}」的实现与架构定义一致", f"Check that the integrated implementation of '{a['name']}' is consistent with the architecture"),
            'precondition': T('集成代码与 SAD 基线可用', 'Integrated code and SAD baseline available'),
            'steps': T('1. 对照 SAD 条目逐项检查代码中的资源分配与保护\n2. 记录不一致项', '1. Compare resource allocation / protection in the code against each SAD item\n2. Record deviations'),
            'expected': T('与 SAD 一致', 'Consistent with the SAD'),
            'criteria': T('无不一致项', 'No deviation'),
            'design_method': T('基于需求分析、评审', 'Requirement analysis, review'),
        }
    return {
        'name': T(f"{a['name']} 时序/性能测试（宿主机节拍）", f"{a['name']} timing test (host ticks)"),
        'target': T(f"以调度节拍计数验证「{a['name']}」满足 {meas}", f"Verify '{a['name']}' meets {meas}, counted in scheduler ticks"),
        'precondition': T('调度节拍由测试驱动，1 拍 = 基础时基', 'Scheduler tick driven by the test; 1 tick = base time base'),
        'steps': T('1. 复位节拍计数\n2. 推进 N 拍\n3. 统计周期任务/超时触发的拍数', '1. Reset tick counter\n2. Advance N ticks\n3. Count the ticks at which the periodic task / timeout fires'),
        'expected': T(f"拍数换算后满足 {meas}", f"Tick count converts to {meas}"),
        'criteria': T('触发拍数与周期/超时定义一致（宿主机墙钟时间不作判据）', 'Firing ticks match the period / timeout (host wall-clock is not a criterion)'),
        'design_method': T('基于需求分析、边界值', 'Requirement analysis, boundary value analysis'),
    }


def method_of(s):
    if s['category'] == 'interface':
        return 'interface'
    if s['category'] in ('resource', 'performance'):
        return 'performance'
    return 'functional'


def priority_of(s, prj):
    if s['execution'] == 'swe6':
        return 'Medium'
    rx = prj.get('cases.high_priority_regex')
    nm = s['anchor']['name']
    if rx and re.search(rx, nm):
        return 'High'
    return prj.get('cases.default_priority', {}).get(s['category'], 'Medium')


# --------------------------------------------------------------------------- register

def derive(model, prj: Project, reg: dict):
    today = dt.date.today().isoformat()
    prefix = prj.get('project.case_id_prefix', 'SWIT-')
    digits = int(prj.get('project.case_id_digits', 5))
    cases = reg.setdefault('cases', [])
    by_slot = {c['slot']: c for c in cases}
    used = [int(c['id'][len(prefix):]) for c in cases if c['id'].startswith(prefix) and c['id'][len(prefix):].isdigit()]
    nxt = max([reg.get('meta', {}).get('next_seq', 1) - 1] + used) + 1
    report = {'added': [], 'modified': [], 'obsoleted': [], 'revived': [], 'unchanged': 0}
    live = set()
    for s in slots_from_model(model, prj):
        a = s['anchor']
        live.add(s['slot'])
        anchor_hash = a['hash'] + (f"|{s.get('consumer')}" if s.get('consumer') else '')
        c = by_slot.get(s['slot'])
        common = {
            'slot': s['slot'], 'category': s['category'], 'kind': s['kind'], 'execution': s['execution'],
            'anchor_key': a['key'], 'anchor_id': a['id'], 'anchor_name': a['name'],
            'component': s['component'], 'module': s['module'],
            'consumer': s.get('consumer'), 'transition': s.get('transition'),
            'requirements': [r['id'] for r in a.get('upstream', [])],
            'method': method_of(s),
        }
        if c is None:
            cid = f"{prefix}{nxt:0{digits}d}"
            nxt += 1
            c = dict(common, id=cid, status='Active', priority=priority_of(s, prj),
                     author=prj.get('project.author', ''), anchor_hash=anchor_hash,
                     text_status='draft', created=today, modified=today, **skeleton(s, prj, model))
            cases.append(c)
            by_slot[s['slot']] = c
            report['added'].append(cid)
            continue
        c.update(common)
        if c['status'] == 'Obsolete':
            c['status'] = 'Active'
            c['text_status'] = 'stale'
            report['revived'].append(c['id'])
        if c.get('anchor_hash') != anchor_hash:
            c['anchor_hash'] = anchor_hash
            if c.get('text_status') == 'filled':
                c['text_status'] = 'stale'
            c['modified'] = today
            report['modified'].append(c['id'])
        else:
            report['unchanged'] += 1
    for c in cases:
        if c['slot'] not in live and c['status'] != 'Obsolete':
            c['status'] = 'Obsolete'
            c['obsolete_reason'] = f"anchor {c.get('anchor_id') or c['anchor_key']} no longer in SAD ({today})"
            c['modified'] = today
            report['obsoleted'].append(c['id'])
    reg['meta'] = {'next_seq': nxt, 'sad_sha256': model['meta']['sha256'], 'sad_source': model['meta']['source'],
                   'updated': today, 'id_prefix': prefix}
    cases.sort(key=lambda c: c['id'])
    return report


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--model', type=Path)
    ap.add_argument('--cases', type=Path)
    ap.add_argument('--summary', action='store_true')
    a = ap.parse_args()
    prj = Project(a.project)
    model_p = a.model or prj.wsp('sad', 'arch_model.json')
    cases_p = a.cases or prj.wsp('cases', 'cases.json')
    model = load_json(model_p)
    reg = load_json(cases_p, default={'meta': {}, 'cases': []})
    rep = derive(model, prj, reg)
    save_json(cases_p, reg)
    if a.summary:
        act = [c for c in reg['cases'] if c['status'] == 'Active']
        by = {}
        for c in act:
            by.setdefault((c['category'], c['execution']), 0)
            by[(c['category'], c['execution'])] += 1
        print(f"cases: {len(act)} active, {len(reg['cases']) - len(act)} obsolete -> {cases_p}")
        for (cat, ex), n in sorted(by.items()):
            print(f"  {cat:12s} {ex:14s} {n:4d}")
        for k in ('added', 'modified', 'revived', 'obsoleted'):
            if rep[k]:
                ids = rep[k]
                print(f"  {k:10s} {len(ids):4d}  {', '.join(ids[:8])}{' ...' if len(ids) > 8 else ''}")
        print(f"  unchanged  {rep['unchanged']:4d}")
        ts = {}
        for c in act:
            ts[c['text_status']] = ts.get(c['text_status'], 0) + 1
        print(f"  text status: {ts}  (draft/stale 需 Claude 写 case_text.json 并 apply_text.py 合并)")
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Draft the content JSON of the strategy (AU-QR-R&D-050) and guide (AU-QW-R&D-56) from the
architecture model, case register, project config and the installed tool versions.

Everything mechanical is filled here (integration objects + the four anchor lists, environment and
tool versions, method selection tables, case attributes, criteria, traceability, workflow steps).
Decisions that belong to people are written as 【TBD-...】: organisation, schedule, communication,
ASIL rationale. Claude reviews ws/docs/<what>_content.json (wording, project-specific rationale),
the user decides the TBDs, then build_docx.py renders it.

Usage: draft_docs.py --project P --what strategy|guide [--force]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import Project, load_json, save_json, utf8_console  # noqa: E402


def tool_version(cmd):
    exe = shutil.which(cmd[0])
    if not exe:
        return ''
    try:
        r = subprocess.run([exe] + cmd[1:], capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace',
                           shell=sys.platform == 'win32' and exe.lower().endswith(('.bat', '.cmd')))
        out = (r.stdout + r.stderr)
        m = re.search(r'(\d+\.\d+(?:\.\d+)?)', out.split('Ceedling =>')[-1] if 'Ceedling' in out else out)
        return m.group(1) if m else ''
    except Exception:
        return ''


def ctx(prj: Project):
    model = load_json(prj.wsp('sad', 'arch_model.json'))
    reg = load_json(prj.wsp('cases', 'cases.json'), default={'cases': []})
    act = [c for c in reg['cases'] if c['status'] == 'Active']
    return model, act


def anchor_tables(prj, model, act):
    T = prj.text
    cases_of = {}
    for c in act:
        cases_of.setdefault(c['anchor_key'], []).append(c['id'])

    def ids(k):
        v = cases_of.get(k, [])
        return f'{v[0]}…{v[-1]} ({len(v)})' if len(v) > 3 else ', '.join(v)
    by_comp = {}
    for i in model['interfaces']:
        by_comp.setdefault(i['component'], []).append(i)
    rows_if = []
    for n, c in enumerate(model['components'], 1):
        its = by_comp.get(c['short'], [])
        rows_if.append([str(n), c['module'], c['short'], c['id'] or 'NO-ID',
                        '; '.join(f"{i['name']} ({i['id'] or 'NO-ID'})" for i in its) or '-', str(len(its))])
    rows_dyn = [[str(n), a['name'], a['id'] or 'NO-ID', {'state_machine': T('状态机/模式', 'State machine / mode'),
                                                          'sequence': T('时序', 'Sequence')}.get(a['kind'], a['kind']),
                 ids(a['key'])] for n, a in enumerate(model['dynamic'], 1)]

    def disp(a):
        ex = {c['execution'] for c in act if c['anchor_key'] == a['key']}
        lab = {'host': T('宿主机集成测试（节拍计数）', 'Host integration test (tick counting)'),
               'target-static': T('目标机构建产物静态核算', 'Static check of target build artefacts'),
               'swe6': T('转 SWE.6（需目标硬件测量）', 'Transferred to SWE.6 (target measurement)'),
               'review': T('集成检查', 'Integration review')}
        return '; '.join(lab.get(e, e) for e in sorted(ex)) or '-'
    rows_perf = [[str(n), a['name'], a['id'] or 'NO-ID', '; '.join(m['text'] for m in a['measures'][:4]) or '-', disp(a)]
                 for n, a in enumerate(model['performance'], 1)]
    rows_res = [[str(n), a['name'], a['id'] or 'NO-ID', str(len(a['members'])) if a['members'] else '-', disp(a)]
                for n, a in enumerate(model['resource'], 1)]
    return [
        {'p': T('集成对象的架构锚点（取自软件架构设计，ID 原样引用）：', 'Architecture anchors of the integration objects (IDs quoted verbatim from the software architecture design):')},
        {'table': {'header': [T('序号', 'No.'), T('模块', 'Module'), T('组件', 'Component'), 'ID', T('接口（ID）', 'Interfaces (ID)'), T('接口数', 'Count')],
                   'rows': rows_if}, 'caption': T('组件与接口', 'Components and interfaces')},
        {'table': {'header': [T('序号', 'No.'), T('动态行为', 'Dynamic behaviour'), 'ID', T('类型', 'Type'), T('用例', 'Cases')],
                   'rows': rows_dyn}, 'caption': T('动态行为', 'Dynamic behaviours')},
        {'table': {'header': [T('序号', 'No.'), T('性能需求', 'Performance requirement'), 'ID', T('指标', 'Figures'), T('验证方式', 'Verification')],
                   'rows': rows_perf}, 'caption': T('性能需求', 'Performance requirements')},
        {'table': {'header': [T('序号', 'No.'), T('资源消耗', 'Resource consumption'), 'ID', T('成员条目', 'Items'), T('验证方式', 'Verification')],
                   'rows': rows_res}, 'caption': T('资源消耗', 'Resource consumption')},
    ]


def tools_rows(prj):
    T = prj.text
    gcc = tool_version([prj.get('toolchain.gcc', 'gcc'), '--version'])
    ceed = tool_version([prj.get('toolchain.ceedling', 'ceedling'), 'version'])
    gcovr = tool_version([prj.get('toolchain.gcovr', 'gcovr'), '--version'])
    py = '.'.join(map(str, sys.version_info[:3]))
    rows = [
        ['1', T('测试工具', 'Test tools'), 'Ceedling + Unity + CMock', T('开源 MIT', 'Open source (MIT)'), ceed or 'TBD',
         T('宿主机集成测试构建、桩生成与执行', 'Host integration test build, mock generation, execution')],
        ['2', T('软件资源', 'Software resources'), 'gcc (host)', 'GPL', gcc or 'TBD',
         T('宿主机编译；-fcallgraph-info 提供调用点（调用覆盖率）', 'Host compiler; -fcallgraph-info supplies call sites (call coverage)')],
        ['3', T('测试工具', 'Test tools'), 'gcov / gcovr', T('开源', 'Open source'), gcovr or 'TBD',
         T('函数覆盖率与逐行证据', 'Function coverage and line-level evidence')],
        ['4', T('软件资源', 'Software resources'), 'Python + openpyxl / python-docx', T('开源', 'Open source'), py,
         T('用例派生、结果采集、交付物生成（swit）', 'Case derivation, result collection, deliverable generation (swit)')],
    ]
    for i, t in enumerate(prj.get('environment.extra_tools', []), len(rows) + 1):
        rows.append([str(i)] + t)
    if prj.get('target.map_file'):
        rows.append([str(len(rows) + 1), T('软件资源', 'Software resources'), T('目标机工具链（链接 map）', 'Target toolchain (linker map)'),
                     '-', prj.get('environment.target_toolchain', '【TBD-目标工具链版本】'),
                     T('ROM/RAM 静态核算的数据来源', 'Source of the ROM/RAM static check')])
    return rows


def methods_values(prj, kind):
    """Selection columns of the ISO 26262-6 method tables, by method id (1a, 1b, ...)."""
    T = prj.text
    yes, no = T('是', 'Yes'), T('否', 'No')
    sel = prj.get(f'strategy.methods.{kind}') or {}
    defaults = {
        'test': {'1a': (yes, '--'), '1b': (yes, '--'),
                 '1c': (no, T('【TBD-故障注入：按 ASIL 决定；QM 项目不要求】', '【TBD-fault injection: per ASIL; not required for QM】')),
                 '1d': (yes, T('ROM/RAM 由目标机 map 静态核算；CPU 负载/执行时间转 SWE.6', 'ROM/RAM checked statically on the target map; CPU load / execution time transferred to SWE.6')),
                 '1e': (no, T('【TBD-无模型生成代码时不适用】', '【TBD-not applicable without model-generated code】')),
                 '1f': (yes, T('时序用例 + 跨组件调用覆盖率验证控制流/数据流', 'Sequence cases + cross-component call coverage verify control / data flow')),
                 '1g': (no, T('静态代码分析已在 SWE.4 完成（准入条件）', 'Static code analysis done in SWE.4 (entry criterion)')),
                 '1h': (no, T('【TBD-按 ASIL 决定】', '【TBD-per ASIL】'))},
        'coverage': {'1a': (yes, '--'), '1b': (yes, '--'), '1c': (yes, '--'), '1d': (yes, '--')},
        'generation': {'1a': (yes, '--'), '1b': (yes, '--'), '1c': (yes, '--'), '1d': (yes, T('基于集成问题经验补充用例', 'Cases added from integration experience'))},
    }[kind]
    defaults.update({k: tuple(v) for k, v in sel.items()})
    return ({rf'^\s*{k}\b': v[0] for k, v in defaults.items()}, {rf'^\s*{k}\b': v[1] for k, v in defaults.items()})


def set_methods(prj, kind, table=0):
    w, r = methods_values(prj, kind)
    return [{'set_column': table, 'col': 6, 'values': w, 'match_col': 0, 'header_rows': 2},
            {'set_column': table, 'col': 7, 'values': r, 'match_col': 0, 'header_rows': 2}]


def strategy(prj: Project):
    T = prj.text
    model, act = ctx(prj)
    name = prj.get('project.name')
    sad = Path(model['meta']['source']).name
    k = prj.get('kpi')
    comps_by_mod = {}
    for c in model['components']:
        comps_by_mod.setdefault(c['module'], []).append(c['short'])
    src_root = prj.resolve(prj.get('sources.root'))
    units = {}
    for c in model['components']:
        d = prj.get('sources.component_dirs', {}).get(c['short'])
        if d and src_root and (src_root / d).is_dir():
            units[c['short']] = ', '.join(p.name for p in sorted((src_root / d).glob('*.c')))
    obj_rows = [[str(n), c['module'], c['short'], units.get(c['short'], T('【TBD-源文件】', '【TBD-source files】'))]
                for n, c in enumerate(model['components'], 1)]
    order = prj.get('integration.sequence') or [
        {'round': T('第1轮', 'Round 1'), 'components': comps_by_mod.get(m, []), 'note': m}
        for m in [x['short'] for x in model['modules']]]
    seq_rows = [[str(i), r['round'], ', '.join(r['components']), r.get('note', '')] for i, r in enumerate(order, 1)]
    excl = prj.get('scope.exclusions') or []
    envdiff = prj.get('environment_difference') or T('【TBD-宿主机与目标机环境差异说明】', '【TBD-host vs target environment differences】')
    n_cases = len(act)
    by_ex = {}
    for c in act:
        by_ex[c['execution']] = by_ex.get(c['execution'], 0) + 1
    sections = [
        {'match': r'(?i)^目的|^purpose', 'blocks': [{'p': T(
            f'本策略描述 {name} 项目的软件集成和集成测试（SWE.5）策略与计划，明确集成对象、集成方法与顺序、测试方法、覆盖率目标、环境、用例管理与缺陷管理，作为集成测试设计、执行与总结的依据。',
            f'This strategy describes the software integration and integration test (SWE.5) strategy and plan of project {name}: '
            'integration objects, integration method and sequence, test methods, coverage targets, environment, test case and defect '
            'management. It is the basis for integration test design, execution and reporting.')}]},
        {'match': r'(?i)^范围|^scope', 'blocks': [
            {'p': T(f'适用于 {name} 项目 {prj.get("project.phase", "【TBD-样件阶段】")} 的软件集成和集成测试，被测软件 {prj.get("project.software_name")} {prj.get("project.software_version")}，对标软件架构设计《{sad}》。',
                    f'Applies to the software integration and integration test of project {name}, phase {prj.get("project.phase", "【TBD-sample phase】")}; '
                    f'software under test {prj.get("project.software_name")} {prj.get("project.software_version")}, verified against the software architecture design "{sad}".')},
            {'p': T('测试目标为：', 'The test objectives are:')},
            {'bullets': [T(f'用例对软件架构接口/动态行为/资源消耗/性能需求的覆盖率 {k["interface_coverage"]:.0%}', f'Case coverage of architecture interfaces / dynamic behaviours / resource consumption / performance requirements {k["interface_coverage"]:.0%}'),
                         T(f'用例执行率 {k["execution_rate"]:.0%}，通过率 {k["pass_rate"]:.0%}', f'Case execution rate {k["execution_rate"]:.0%}, pass rate {k["pass_rate"]:.0%}'),
                         T(f'函数覆盖率 {k["function_coverage"]:.0%}，调用覆盖率 {k["call_coverage"]:.0%}', f'Function coverage {k["function_coverage"]:.0%}, call coverage {k["call_coverage"]:.0%}'),
                         T(f'缺陷及时关闭率 {k["defect_closure_rate"]:.0%}', f'Timely defect closure rate {k["defect_closure_rate"]:.0%}')]}]},
        {'match': r'(?i)^读者对象|target audience', 'blocks': [{'bullets': [T('项目经理', 'Project manager'), T('软件工程师 / 集成测试工程师', 'Software / integration test engineers'), T('系统工程师', 'System engineers'), 'QA']}]},
        {'match': r'(?i)^参考资料|^references', 'blocks': [{'bullets': [
            T(f'软件架构设计规格说明书：{sad}', f'Software architecture design specification: {sad}'),
            T('AU-QW-R&D-40 软件集成和集成测试过程规范', 'AU-QW-R&D-40 Software integration and integration testing process specification'),
            T('AU-QW-R&D-56 软件集成测试指南', 'AU-QW-R&D-56 Software integration test guide'),
            'ISO 26262-6:2018 §10, ASPICE 3.1/4.0 SWE.5']}]},
        {'match': r'(?i)^术语和缩写|terminology', 'blocks': [{'fill_table': 0, 'rows': [
            ['1', 'SWE.5', T('软件集成和集成测试过程', 'Software integration and integration test process')],
            ['2', 'SIL', T('软件在环：宿主机上链接真实组件代码执行测试', 'Software-in-the-loop: real component code linked and tested on the host')],
            ['3', T('调用覆盖率', 'Call coverage'), T('已执行的跨组件调用点 / 全部跨组件调用点（ISO 26262-6 表 12 1b）', 'Executed cross-component call sites / all cross-component call sites (ISO 26262-6 Table 12 1b)')],
            ['4', T('边界桩', 'Boundary stub'), T('本轮集成范围外组件/底层驱动的替身，由 CMock 生成', 'Stand-in for out-of-scope components / low-level drivers, generated by CMock')],
            ['5', 'NA (SWE.6)', T('需目标硬件测量的用例转软件合格性测试验证，本过程判定 用例不适用NA', 'Cases needing target measurement are verified in SWE.6; verdict NA in this process')]]}]},
        {'match': r'(?i)^组织和职责|organization and responsibilities', 'blocks': [{'fill_table': 0, 'rows': prj.get('strategy.organization') or [
            ['1', prj.get('project.author') or '【TBD】', T('集成测试工程师', 'Integration test engineer'), T('编写策略/用例，搭建环境，执行测试，记录结果，编写报告', 'Writes strategy / cases, builds environment, executes, records, reports'), ''],
            ['2', prj.get('project.reviewer') or '【TBD】', T('评审人', 'Reviewer'), T('评审策略、用例、记录、报告', 'Reviews strategy, cases, records, report'), '']]}]},
        {'match': r'(?i)^软件集成及测试环境|^software integration and test environment$', 'blocks': [{'fill_table': 0, 'rows': tools_rows(prj)}]},
        {'match': r'(?i)环境搭建|environment setup', 'blocks': [{'fill_table': 0, 'rows': [[T(
            '1) 宿主机 SIL：本轮集成组件以真实源码编译链接（Ceedling :paths :source），边界（MCAL/BSW/范围外组件）以同名替身头 + CMock 桩替代；'
            '调度节拍由测试驱动；编译加 -fcallgraph-info 与 gcov 插桩。\n2) 目标机静态核算：使用被测版本的目标机构建产物（链接 map / .su）核算 ROM/RAM/栈。\n'
            '3) 需目标硬件测量的执行时间/CPU 负载/中断延迟转 SWE.6。',
            '1) Host SIL: components of the round are compiled and linked from real sources (Ceedling :paths :source); the boundary '
            '(MCAL / BSW / out-of-scope components) is replaced by same-named stand-in headers mocked with CMock; the scheduler tick is '
            'driven by the test; -fcallgraph-info and gcov instrumentation are enabled.\n2) Target static check: ROM / RAM / stack are '
            'checked on the target build artefacts (linker map / .su) of the version under test.\n3) Execution time, CPU load and '
            'interrupt latency need the target and are transferred to SWE.6.')]], 'header_rows': 1}]},
        {'match': r'(?i)功能安全集成测试环境|consistency control', 'blocks': [
            {'p': T(f'项目 ASIL 等级：{prj.get("project.asil")}。', f'Project ASIL: {prj.get("project.asil")}.')},
            {'p': T('宿主机与目标机环境差异：', 'Differences between host and target environment: ') + envdiff},
            {'p': T('安全相关用例如需在量产一致的目标硬件上复现，转 SWE.6 执行并记录硬件/软件/工具版本。',
                    'Safety-related cases that must be reproduced on production-equivalent hardware are executed in SWE.6 with hardware / software / tool versions recorded.')}]},
        {'match': r'(?i)^集成对象|^integration objects', 'blocks': [{'fill_table': 0, 'rows': obj_rows}] + anchor_tables(prj, model, act) + (
            [{'p': T('不集成也不打桩的对象：', 'Objects neither integrated nor stubbed:')},
             {'bullets': [f"{e['name']}: {e['reason']}" for e in excl]}] if excl else [])},
        {'match': r'(?i)^集成方法|^integration methods', 'blocks': [{'p': prj.get('strategy.method_text') or T(
            '采用自底而上集成：先集成驱动层（DRV）与硬件抽象层（HAL），再集成应用层（APP），最后集成系统服务层（SSL）与启动/调度。依据：软件架构为严格分层，'
            '上层只依赖下层接口，自底而上可让每一轮的被依赖组件都已集成并验证，边界清晰、缺陷易定位。',
            'Bottom-up integration: driver layer (DRV) and hardware abstraction layer (HAL) first, then the application layer (APP), then '
            'the system service layer (SSL) with start-up / scheduling. Rationale: the architecture is strictly layered and upper layers '
            'only depend on lower-layer interfaces, so every round builds on already integrated and verified components and defects '
            'are easy to locate.')}]},
        {'match': r'(?i)^集成顺序|^integration sequence', 'blocks': [
            {'p': T('集成顺序（每轮的范围写入 swit_project.json 的 scope.components）：', 'Integration sequence (the scope of each round is set in swit_project.json scope.components):')},
            {'table': {'header': [T('序号', 'No.'), T('轮次', 'Round'), T('集成组件', 'Components'), T('说明', 'Note')], 'rows': seq_rows}}]},
        {'match': r'(?i)集成过程管理|integrated process management', 'blocks': [{'fill_table': 0, 'rows': [
            [T('准入准则', 'Entry criteria'), T('各组件通过软件单元验证（SWE.4）并纳入配置管理；软件架构设计已评审基线化；宿主机集成工程编译通过（probe 无错误）。',
                                             'Components passed software unit verification (SWE.4) and are under configuration management; the architecture design is reviewed and baselined; the host integration build compiles (probe clean).')],
            [T('通过准则', 'Exit criteria'), T('本轮组件全部集成并编译链接通过；冒烟测试通过（235 集成记录）；集成测试 KPI 达标或偏差已评审。',
                                            'All components of the round integrated, compiled and linked; smoke test passed (235 integration record); integration test KPIs met or deviations reviewed.')]],
            'header_rows': 1}]},
        {'match': r'(?i)集成测试方法|integration test methodology', 'blocks': set_methods(prj, 'test')},
        {'match': r'(?i)集成测试内容|integration test content', 'blocks': [
            {'p': T(f'用例由软件架构锚点派生，共 {n_cases} 条（宿主机 {by_ex.get("host", 0)}、目标机静态核算 {by_ex.get("target-static", 0)}、集成检查 {by_ex.get("review", 0)}、转 SWE.6 {by_ex.get("swe6", 0)}）。',
                    f'Cases are derived from the architecture anchors: {n_cases} in total (host {by_ex.get("host", 0)}, target static check '
                    f'{by_ex.get("target-static", 0)}, review {by_ex.get("review", 0)}, transferred to SWE.6 {by_ex.get("swe6", 0)}).')},
            {'fill_table': 0, 'rows': [
                ['1', prj.get('project.software_name'), T('软件架构设计中定义的全部接口', 'All interfaces defined in the architecture'), '', T('接口测试', 'Interface testing'), 'Ceedling/CMock (host SIL)'],
                ['2', prj.get('project.software_name'), T('状态机/运行模式及组件间动态行为（时序）', 'State machines / operating modes and dynamic behaviour (sequences)'), '', T('功能测试', 'Functional testing'), 'Ceedling/CMock (host SIL)'],
                ['3', prj.get('project.software_name'), T('周期/时基/超时（节拍计数）', 'Periods / time bases / timeouts (tick counting)'), '', T('性能测试', 'Performance testing'), 'Ceedling (host SIL)'],
                ['4', prj.get('project.software_name'), T('资源消耗', 'Resource consumption'), 'ROM / RAM', T('性能测试', 'Performance testing'), T('目标机链接 map', 'Target linker map')],
                ['5', prj.get('project.software_name'), T('资源消耗', 'Resource consumption'), T('CPU 负载/执行时间', 'CPU load / execution time'), T('性能测试', 'Performance testing'), T('转 SWE.6', 'Transferred to SWE.6')]]}]},
        {'match': r'(?i)结构化覆盖率|structured coverage', 'blocks': set_methods(prj, 'coverage')},
        {'match': r'(?i)测试任务安排|organization of testing tasks', 'blocks': [{'p': T('参见《项目进度计划》；集成轮次见第 4.3 节。', 'See the project schedule; integration rounds see section 4.3.')}]},
        {'match': r'(?i)测试用例产生方法|test case generation methods', 'blocks': set_methods(prj, 'generation')},
        {'match': r'(?i)测试用例属性|test case properties', 'blocks': [{'fill_table': 0, 'rows': [
            ['1', T('标识符', 'Identifier'), 'SWIT-XXXXX', T('5 位流水号，由用例注册表分配，永不复用；废弃用例保留 ID 标记 Obsolete', '5-digit serial allocated by the case register, never reused; obsolete cases keep their ID'), ''],
            ['2', T('优先级', 'Priority'), 'H', T('初始化/看门狗/故障/复位/休眠唤醒等安全或时序关键交互', 'Safety- or timing-critical interactions (init, watchdog, fault, reset, sleep/wake-up)'), ''],
            ['2', T('优先级', 'Priority'), 'M', T('一般接口与资源项', 'Ordinary interfaces and resource items'), ''],
            ['2', T('优先级', 'Priority'), 'L', T('辅助接口', 'Auxiliary interfaces'), ''],
            ['3', T('测试内容', 'Test content'), T('接口/功能/性能测试', 'Interface / functional / performance test'), T('接口锚点→接口测试；动态行为→功能测试；资源/性能→性能测试', 'Interface anchors -> interface test; dynamic behaviour -> functional test; resource / performance -> performance test'), ''],
            ['4', T('设计方法', 'Design method'), T('需求分析、等价类、边界值、错误推测', 'Requirement analysis, equivalence classes, boundary values, error guessing'), T('等价类划分与边界取值写在测试步骤中', 'Partitions and boundary values are stated in the test steps'), ''],
            ['5', T('预置条件', 'Precondition'), '', T('集成范围、桩的默认返回值、初始化状态', 'Integration scope, stub default returns, initial state'), ''],
            ['6', T('测试步骤', 'Test step'), '', T('输入取自 SAD 约束与源码常量的真实数值', 'Inputs use real values from SAD constraints and source constants'), ''],
            ['7', T('预期输出', 'Expected output'), '', T('使用方接收值与提供方输出一致；状态/时序符合 SAD', 'Consumer value equals provider output; state / sequence as in the SAD'), ''],
            ['8', T('判定准则', 'Decision criteria'), '', T('判据可机械判定（数值、状态、调用顺序、节拍数）', 'Mechanically decidable (values, states, call order, tick counts)'), '']]}]},
        {'match': r'(?i)^测试用例选择|test case selection', 'blocks': [
            {'p': T('首轮执行全部有效用例；架构变更时按变更影响增删改用例；回归按上一轮记录（失败/未执行/缺陷关联）与代码变更影响选择。',
                    'The first round runs all active cases; on architecture change cases are added / changed / obsoleted per impact; regression selects from the previous record (failed / not run / defect-linked) plus code-change impact.')},
            {'fill_table': 0, 'rows': prj.get('strategy.selection_rows') or [
                [T('首次/架构变更', 'First / architecture change'), T('全部有效用例', 'All active cases')],
                [T('软件版本更新（架构未变）', 'New software version (architecture unchanged)'), T('全部有效用例', 'All active cases')],
                [T('回归', 'Regression'), T('上一轮失败/未执行/缺陷关联用例 + 变更组件影响用例 + 高优先级冒烟集', 'Failed / not-run / defect-linked cases of the previous round + cases impacted by changed components + high-priority smoke set')]]}]},
        {'match': r'(?i)测试用例维护|test case maintenance', 'blocks': [{'bullets': [
            T('新增：SAD 新增锚点自动派生新用例并分配新 ID', 'Add: new SAD anchors derive new cases with new IDs'),
            T('修改：锚点内容变化的用例标记 stale，复核后更新文本', 'Change: cases whose anchor changed are marked stale and re-checked'),
            T('删除：SAD 删除的锚点对应用例标 Obsolete，ID 不复用', 'Delete: cases of removed anchors become Obsolete; IDs are never reused')]}]},
        {'match': r'(?i)^测试准则|^testing guidelines', 'blocks': [{'fill_table': 0, 'rows': [
            ['1', T('测试准入准则', 'Entry'), T('软件集成通过（235）；集成工程编译通过；用例评审通过', 'Software integration passed (235); integration build compiles; cases reviewed')],
            ['2', T('测试中止准则', 'Suspension'), T('构建失败或阻塞性缺陷导致 50% 以上用例无法执行', 'Build failure or blocking defects make more than 50% of the cases unexecutable')],
            ['3', T('测试再进入准则', 'Resumption'), T('阻塞问题已修复并通过冒烟', 'Blocking issue fixed and smoke test passed')],
            ['4', T('测试准出准则', 'Exit'), T('执行率 100%（不含转 SWE.6 的 NA 用例）；KPI 达标；A/B 级缺陷关闭', 'Execution rate 100% (excluding NA cases transferred to SWE.6); KPIs met; A/B defects closed')],
            ['5', T('判定口径', 'Verdict rules'), T('未执行不计通过；NA 仅用于转 SWE.6 的用例；用例的全部测试通过才判通过', 'Not run never counts as passed; NA only for cases transferred to SWE.6; a case passes only when all its tests pass')]]}]},
        {'match': r'(?i)^回归测试|^regression testing', 'blocks': [{'p': T(
            '回归输入为上一轮软件集成测试记录（236/237）；选择失败、阻塞、未执行、缺陷关联用例，以及代码变更组件的提供/使用接口用例与相关动态行为用例；输出回归测试记录（237）与测试报告（238），不再输出 236。',
            'Regression takes the previous integration test record (236/237) as input; it re-runs failed, blocked, not-run and defect-linked cases plus the interface and dynamic-behaviour cases of changed components; it produces the regression record (237) and the report (238), no new 236.')}]},
        {'match': r'(?i)测试数据管理|test data management', 'blocks': [{'p': T(
            '测试工程（project.yml、测试源码、替身头）、用例注册表、每轮结果 JSON 与覆盖率证据存放于 swit 工作区并纳入配置管理；交付物按版本基线化。',
            'The test project (project.yml, test sources, stand-in headers), the case register, per-round result JSON and coverage evidence live in the swit workspace under configuration management; deliverables are baselined per version.')}]},
        {'match': r'(?i)追溯一致性|retroactive consistency', 'blocks': [{'fill_table': 0, 'rows': [
            ['1', T('架构接口 ↔ 用例 双向追溯', 'Architecture interfaces <-> cases'), T('用例注册表记录锚点 ID；022 正/反向 sheet', 'Case register stores the anchor ID; 022 forward / backward sheets'), T('swit 自检：每个锚点有用例或裁剪理由', 'swit self-check: every anchor has a case or a tailoring reason')],
            ['2', T('动态行为 ↔ 用例', 'Dynamic behaviour <-> cases'), T('同上', 'Same'), T('同上', 'Same')],
            ['3', T('用例 ↔ 测试结果', 'Cases <-> results'), T('测试函数上方 SWIT 标记注释', 'SWIT marker above each test function'), T('结果采集按标记对账，无标记测试报警', 'Results reconciled through markers; unmarked tests reported')],
            ['4', T('测试结果 ↔ 缺陷', 'Results <-> defects'), T('记录缺陷 ID 列', 'Defect ID column of the record'), T('缺陷清单与问题系统一致', 'Defect list consistent with the issue tracker')]]}]},
        {'match': r'(?i)^缺陷管理|^defect management', 'blocks': [{'p': T(
            '缺陷在问题管理系统登记，ID 写入测试记录；缺陷只由失败的测试或可复现证据确认；修复后通过回归验证关闭。集成发现的架构违规（越层依赖、未文档化接口、资源超预算）同样登记。',
            'Defects are registered in the issue tracker and their IDs written into the record; a defect is only confirmed by a failing test or reproducible evidence; it is closed after regression verification. Architecture violations found by integration (layer violations, undocumented interfaces, resource budget overruns) are registered as well.')}]},
        {'match': r'(?i)沟通管理|communication management', 'blocks': [{'fill_table': 0, 'rows': prj.get('strategy.communication') or [
            ['1', '【TBD】', T('集成测试策略评审', 'Strategy review'), T('会议', 'Meeting'), T('项目组', 'Project team'), '【TBD】']]}]},
    ]
    return {'what': 'strategy', 'placeholders': {'ＸＸＸＸＸ': name, 'XXXXX': name, 'XXXX': name}, 'sections': sections}


def guide(prj: Project):
    T = prj.text
    model, act = ctx(prj)
    name = prj.get('project.name')
    sad = Path(model['meta']['source']).name
    itf_rows = []
    cid = {}
    for c in act:
        cid.setdefault(c['anchor_key'], []).append(c['id'])
    for i in model['interfaces']:
        itf_rows.append([', '.join(cid.get(i['key'], [])) or '-', f"{i['id'] or 'NO-ID'}" + (f" / {', '.join(r['id'] for r in i['upstream'][:3])}" if i['upstream'] else ''),
                         i['signature'], f"{i['module']}/{i['component']}", (T('使用方：', 'consumers: ') + ', '.join(i['consumers'])) if i['consumers'] else ''])
    sections = [
        {'match': r'(?i)^目的|purpose', 'blocks': [{'p': T(f'规定 {name} 软件集成测试（SWE.5）的执行方法，使测试可重复、结果可追溯。',
                                                           f'Defines how the software integration test (SWE.5) of {name} is performed so that it is repeatable and traceable.')}]},
        {'match': r'(?i)适用范围|scope', 'blocks': [{'p': T(f'适用于 {name} 软件 {prj.get("project.software_name")} 的集成测试；对标《{sad}》。',
                                                            f'Applies to the integration test of {prj.get("project.software_name")} in {name}, against "{sad}".')}]},
        {'match': r'(?i)参考文档|reference document', 'blocks': [{'fill_table': 0, 'rows': [
            [sad, '-', T('软件架构设计（测试依据）', 'Software architecture design (test basis)')],
            ['AU-QW-R&D-40', '-', T('软件集成和集成测试过程规范', 'Integration process specification')],
            [f'{name} SWE.5 strategy', '-', T('软件集成和集成测试策略', 'Integration and integration test strategy')]]}]},
        {'match': r'(?i)^缩写\s*abbreviation$|^abbreviation$', 'blocks': [{'fill_table': 0, 'rows': [
            ['SWE.5', 'Software Integration and Integration Test'], ['SIL', 'Software-in-the-Loop'], ['SAD', 'Software Architecture Design'],
            ['SWIT', 'Software Integration Test (case ID prefix)'], ['CMock', 'Mock generator for C (boundary stubs)']]}]},
        {'match': r'(?i)^定义\s*terminology$|^definitions?$', 'blocks': [{'fill_table': 0, 'rows': [
            [T('架构锚点', 'Architecture anchor'), T('SAD 中带 ID 的接口/动态行为/资源消耗/性能需求条目', 'Interface / dynamic behaviour / resource / performance item with an ID in the SAD')],
            [T('调用覆盖率', 'Call coverage'), T('已执行跨组件调用点 / 全部跨组件调用点', 'Executed cross-component call sites / all cross-component call sites')],
            [T('替身头', 'Stand-in header'), T('与真实头同名、只含原型的边界头，放在 support/ 并被 CMock 打桩', 'Same-named, prototype-only boundary header in support/, mocked by CMock')]]}]},
        {'match': r'(?i)职责和权限|responsibility and authority', 'blocks': [{'fill_table': 0, 'rows': [
            [T('集成测试工程师', 'Integration test engineer'), T('设计用例、搭建环境、执行与记录', 'Designs cases, builds the environment, executes and records'), '052 / 236 / 237 / 238 / 022'],
            [T('软件架构师', 'Software architect'), T('澄清架构锚点，处理 SAD 问题', 'Clarifies anchors, resolves SAD findings'), 'SAD'],
            [T('评审人', 'Reviewer'), T('评审用例、记录与报告', 'Reviews cases, records, report'), T('评审记录', 'Review records')]]}]},
        {'match': r'(?i)制定软件集成测试计划|develop software integration test plan', 'blocks': [{'fill_table': 0, 'rows': [
            [T('测试依据', 'Test basis'), sad], [T('集成范围', 'Integration scope'), ', '.join(prj.get('scope.components') or [c['short'] for c in model['components']])],
            [T('环境', 'Environment'), T('宿主机 SIL（Ceedling/Unity/CMock + gcc/gcov）+ 目标机构建产物静态核算', 'Host SIL (Ceedling/Unity/CMock + gcc/gcov) + static check of target build artefacts')],
            [T('覆盖率目标', 'Coverage targets'), T(f"函数 {prj.get('kpi.function_coverage'):.0%} / 调用 {prj.get('kpi.call_coverage'):.0%}", f"Function {prj.get('kpi.function_coverage'):.0%} / call {prj.get('kpi.call_coverage'):.0%}")],
            [T('进度', 'Schedule'), T('【TBD-见项目计划】', '【TBD-see project plan】')],
            [T('交付物', 'Deliverables'), '050 / 056 / 052 / 236 / 237 / 238 / 022']]}]},
        {'match': r'(?i)测试项与接口清单|test items & interface list', 'blocks': [{'fill_table': 0, 'rows': itf_rows}]},
        {'match': r'(?i)用例模板与最小字段|mandatory fields', 'blocks': [{'fill_table': 0, 'rows': [
            [T('标识符', 'Identifier'), 'SWIT-XXXXX'], [T('名称', 'Name'), T('接口/行为名 + 验证点', 'Interface / behaviour + check')],
            [T('测试目标', 'Test target'), T('引用的架构锚点及其约束', 'Referenced architecture anchor and its constraint')],
            [T('预置条件', 'Precondition'), T('集成范围、桩默认值、初始状态', 'Scope, stub defaults, initial state')],
            [T('测试步骤', 'Test steps'), T('具体输入数值，含等价类与边界', 'Concrete input values incl. partitions and boundaries')],
            [T('预期输出/判定准则', 'Expected / criteria'), T('可机械判定', 'Mechanically decidable')]]}]},
        {'match': r'(?i)通过/失败判定|pass/fail', 'blocks': [{'bullets': [
            T('用例的全部测试通过才判通过；任一失败判失败', 'A case passes only when all its tests pass; any failure fails it'),
            T('TEST_IGNORE 或未实现的测试判未执行，不计通过', 'TEST_IGNORE / unimplemented tests are "not run", never passed'),
            T('需目标硬件测量的用例判 用例不适用NA 并注明转 SWE.6', 'Cases needing target measurement get NA with the SWE.6 transfer noted'),
            T('偏差（环境差异、桩假设）写入报告第 4 节', 'Deviations (environment, stub assumptions) go into report section 4')]}]},
        {'match': r'(?i)^执行步骤|execution steps', 'blocks': [{'fill_table': 0, 'rows': [
            ['1', 'swit ingest / design', T('arch_model.json、cases.json', 'arch_model.json, cases.json')],
            ['2', 'gen_ceedling yml / standins / probe', T('project.yml、替身头、编译探测结果', 'project.yml, stand-in headers, compile probe result')],
            ['3', T('编写/完善测试（SWIT 标记）', 'Write tests (SWIT markers)'), 'test/test_swit_*.c'],
            ['4', 'ceedling gcov:all + collect + check_resources', 'results/round_<n>.json'],
            ['5', 'swit build', '236/237, 238, 022']]}]},
        {'match': r'(?i)结果分析与缺陷管理|result analysis', 'blocks': [{'p': T(
            '失败用例逐条分析：测试错误则修正测试；软件或架构问题登记缺陷并关联用例；缺陷只由失败测试或可复现证据确认。',
            'Every failure is analysed: test mistakes are fixed in the test; software or architecture issues become defects linked to the case; a defect is only confirmed by a failing test or reproducible evidence.')}]},
        {'match': r'(?i)报告最小内容|report minimum content', 'blocks': [{'fill_table': 0, 'rows': [
            ['1', T('测试目标达成（覆盖率/执行率/通过率/缺陷关闭率）', 'Objectives (coverage / execution / pass / defect closure)')],
            ['2', T('集成情况（取自 235）', 'Integration summary (from 235)')], ['3', T('函数/调用覆盖率', 'Function / call coverage')],
            ['4', T('各轮实施情况与环境差异', 'Rounds and environment differences')], ['5', T('缺陷与遗留缺陷', 'Defects and residual defects')],
            ['6', T('结论', 'Conclusion')]]}]},
        {'match': r'(?i)本文件产生的记录|related records', 'blocks': [{'fill_table': 0, 'rows': [
            [T('软件集成和集成测试策略', 'Strategy'), 'AU-QR-R&D-050', 'SVN', T('项目周期', 'Project lifetime')],
            [T('软件集成测试用例', 'Test cases'), 'AU-QR-R&D-052', 'SVN', T('项目周期', 'Project lifetime')],
            [T('软件集成测试记录', 'Test record'), 'AU-QR-R&D-236', 'SVN', T('项目周期', 'Project lifetime')],
            [T('软件集成回归测试记录', 'Regression record'), 'AU-QR-R&D-237', 'SVN', T('项目周期', 'Project lifetime')],
            [T('软件集成测试报告', 'Test report'), 'AU-QR-R&D-238', 'SVN', T('项目周期', 'Project lifetime')],
            [T('软件集成测试追溯矩阵', 'Traceability matrix'), 'AU-QR-R&D-022', 'SVN', T('项目周期', 'Project lifetime')]]}]},
        {'match': r'(?i)附件a|test case template', 'blocks': [{'fill_table': 0, 'rows': [
            [T('标识符', 'Identifier'), 'SWIT-00001'], [T('名称', 'Name'), 'DADC_vidInit interface integration test'],
            [T('测试方法', 'Test method'), T('接口测试', 'Interface test')], [T('设计方法', 'Design method'), T('需求分析、等价类、边界值', 'Requirement analysis, equivalence, boundary')],
            [T('测试目标', 'Test target'), T('架构锚点 ID 与约束', 'Anchor ID and constraint')], [T('预置条件', 'Precondition'), '...'],
            [T('测试步骤', 'Test steps'), '...'], [T('预期输出', 'Expected output'), '...'], [T('判定准则', 'Decision criteria'), '...']]}]},
        {'match': r'(?i)附件b|traceability matrix', 'blocks': [{'fill_table': 0, 'rows': [['SWAD-xxxxx', 'SWIT-xxxxx', 'P/F/NA', 'test_swit_*.c::test_*', '']]}]},
        {'match': r'(?i)附件c|environment configuration record', 'blocks': [{'fill_table': 0, 'rows': [
            [r[2], r[4]] for r in tools_rows(prj)] + [[T('被测软件', 'Software under test'), f"{prj.get('project.software_name')} {prj.get('project.software_version')}"]]}]},
    ]
    return {'what': 'guide', 'placeholders': {'ＸＸＸＸＸ': name, 'XXXXX': name, 'XXXX': name}, 'sections': sections}


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--what', required=True, choices=['strategy', 'guide'])
    ap.add_argument('--force', action='store_true', help='overwrite an existing (possibly hand-edited) content file')
    a = ap.parse_args()
    prj = Project(a.project)
    out = prj.wsp('docs', f'{a.what}_content.json')
    if out.exists() and not a.force:
        print(f'{out} exists (may contain reviewed wording); use --force to redraft')
        return 1
    save_json(out, strategy(prj) if a.what == 'strategy' else guide(prj))
    print(f'drafted {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

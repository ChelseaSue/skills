#!/usr/bin/env python3
"""swit - SWE.5 software integration test, one entry point.

  init      create swit_project.json from the template (does not overwrite)
  status    detect the mode and list the deliverables due:
              full        no baseline yet (first test of the project)
              sad-change  SAD anchors differ from the baseline
              execute     SAD unchanged -> records + report only
              regression  asked for with --regression (needs --previous record)
  ingest    SAD (.docx/.md) -> sad_ir.json -> arch_model.json (+ arch_supplement.json); diff vs baseline
  design    arch_model -> case register (stable SWIT IDs; added / stale / obsolete)
  docs      draft strategy / guide content JSON (keeps reviewed content unless --force)
  host      gen_ceedling sub-commands: yml | standins | boundary | probe | skeleton
  run       target static check + (optionally ceedling) + collect -> results/round_<n>.json
  regress   select regression cases from the previous record (236/237 xlsx)
  build     render the deliverables due for --mode
  baseline  freeze the current arch_model as the baseline (done automatically after a release build)
  check     release gate

Usage examples
  swit.py status   --project swit/swit_project.json
  swit.py ingest   --project P
  swit.py design   --project P
  swit.py run      --project P --round 1 --ceedling
  swit.py build    --project P --mode full --round 1
  swit.py regress  --project P --previous "out/...Test Records_1.xlsx" --round R1 --svn 1200:1234
  swit.py run      --project P --round R1 --selection
  swit.py build    --project P --mode regression --rounds 1 R1
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ASSETS, Project, file_sha256, load_json, save_json, utf8_console  # noqa: E402

PY = [sys.executable, '-I']


def sh(script, *args):
    r = subprocess.run(PY + [str(HERE / script)] + [str(a) for a in args])
    return r.returncode


def baseline_path(prj):
    return prj.wsp('baseline', 'arch_model.json')


# --------------------------------------------------------------------------- commands

def cmd_init(a):
    p = Path(a.project)
    if p.exists():
        print(f'{p} exists - not overwritten')
        return 0
    shutil.copyfile(ASSETS / 'swit_project.example.json', p)
    print(f'created {p}: fill project / sad.path / templates.dir / sources / target, then `swit.py status`')
    return 0


def detect_mode(prj, regression=False):
    sad = prj.resolve(prj.get('sad.path'))
    info = {'sad': str(sad) if sad else None}
    if not sad or not sad.exists():
        return 'error', dict(info, why='sad.path not configured / not found')
    base = baseline_path(prj)
    if regression:
        mode = 'regression'
    elif not base.exists():
        return 'full', dict(info, why='no baseline: first SWE.5 run of this project')
    else:
        mode = 'execute'
    if base.exists():
        bm = load_json(base)
        sha = file_sha256(sad)
        if sha != bm['meta']['sha256']:
            cur = load_json(prj.wsp('sad', 'arch_model.json'), default={})
            if cur.get('meta', {}).get('sha256') != sha:
                info['why'] = 'SAD file changed since the baseline: run `ingest` to see whether anchors changed'
                info['needs_ingest'] = True
                return ('regression' if regression else 'sad-change?'), info
            sys.path.insert(0, str(HERE / 'sad'))
            import diff as sd
            d = sd.diff(bm, cur)
            if d['changed']:
                info['diff'] = d
                if regression:
                    info['warn'] = 'SAD anchors changed: regression assumes an unchanged architecture -> run sad-change'
                    return 'regression', info
                return 'sad-change', dict(info, why=sd.summary_line(d, prj.lang() if prj.lang() != 'bilingual' else 'en'))
            info['why'] = 'SAD file changed but no anchor changed (formatting only)'
    return mode, info


def cmd_status(a):
    prj = Project(a.project)
    mode, info = detect_mode(prj, a.regression)
    from check import DUE
    print(f"mode: {mode}")
    if info.get('why'):
        print(f"  {info['why']}")
    if info.get('warn'):
        print(f"  WARN {info['warn']}")
    if mode in DUE:
        print('  deliverables due: ' + ', '.join(DUE[mode]))
    nxt = {'full': ['ingest', 'design', 'docs', 'host yml/standins/probe', '(write tests)', 'run --round 1 --ceedling',
                    'build --mode full --round 1', 'check --mode full --round 1'],
           'sad-change': ['ingest', 'design', 'docs --force (review!)', '(update tests of stale/new cases)',
                          'run --round N --ceedling', 'build --mode sad-change --round N', 'check'],
           'execute': ['run --round N --ceedling', 'build --mode execute --round N', 'check'],
           'regression': ['regress --previous <236/237.xlsx> --round RN', 'run --round RN --selection --ceedling',
                          'build --mode regression --rounds <first> RN', 'check --mode regression --rounds <first> RN']}
    if mode in nxt:
        print('  next: ' + ' -> '.join(nxt[mode]))
    if mode == 'regression' and not a.previous:
        print('  regression needs the previous round record (--previous)')
    return 0


def cmd_ingest(a):
    prj = Project(a.project)
    sad = prj.resolve(prj.get('sad.path'))
    if not sad or not sad.exists():
        print('error: sad.path not found', file=sys.stderr)
        return 2
    if sad.suffix.lower() == '.doc':
        sys.path.insert(0, str(HERE / 'docs'))
        from convert import convert
        sad = convert(sad, prj.wsp('sad'))
    rc = sh('sad/extract.py', sad, '-o', prj.wsp('sad', 'sad_ir.json'))
    if rc:
        return rc
    args = ['--ir', prj.wsp('sad', 'sad_ir.json'), '--project', prj.path, '-o', prj.wsp('sad', 'arch_model.json'), '--summary']
    if prj.wsp('sad', 'arch_supplement.json').exists():
        args += ['--supplement', prj.wsp('sad', 'arch_supplement.json')]
    rc = sh('sad/model.py', *args)
    if baseline_path(prj).exists():
        sh('sad/diff.py', baseline_path(prj), prj.wsp('sad', 'arch_model.json'), '-o', prj.wsp('sad', 'diff.json'))
    return rc


def cmd_design(a):
    prj = Project(a.project)
    return sh('cases/derive.py', '--project', prj.path, '--summary')


def cmd_docs(a):
    prj = Project(a.project)
    rc = 0
    for w in ('strategy', 'guide'):
        rc |= sh('docs/draft_docs.py', '--project', prj.path, '--what', w, *(['--force'] if a.force else []))
    return 0 if rc in (0, 1) else rc


def cmd_host(a):
    prj = Project(a.project)
    return sh('host/gen_ceedling.py', '--project', prj.path, a.sub, *(['--force'] if a.force else []))


def cmd_run(a):
    prj = Project(a.project)
    typ = 'regression' if a.round.upper().startswith('R') else 'first'
    sh('target/check_resources.py', '--project', prj.path, '--round', a.round)
    args = ['--project', prj.path, '--round', a.round, '--type', typ]
    if a.selection:
        args += ['--selection', prj.wsp('results', f'selection_{a.round}.json')]
    if a.ceedling:
        args += ['--run']
    return sh('host/collect.py', *args)


def cmd_regress(a):
    prj = Project(a.project)
    args = ['--project', prj.path, '--previous', a.previous, '--round', a.round]
    if a.svn:
        args += ['--svn', a.svn]
    if a.git:
        args += ['--git', a.git]
    if a.changed_files:
        args += ['--changed-files', *a.changed_files]
    return sh('regress/select.py', *args)


def change_text(prj, mode, rounds):
    T = prj.text
    dp = prj.wsp('sad', 'diff.json')
    d = load_json(dp) if dp.exists() else None
    if mode == 'sad-change' and d:
        sys.path.insert(0, str(HERE / 'sad'))
        import diff as sd
        return sd.summary_line(d, 'zh' if prj.lang() == 'zh' else 'en')
    if mode == 'full':
        return T('首版：按软件架构设计生成', 'Initial version generated from the software architecture design')
    if mode == 'regression':
        return T(f'第 {rounds[-1]} 轮回归测试', f'Regression round {rounds[-1]}')
    return T(f'第 {rounds[-1]} 轮测试执行', f'Test round {rounds[-1]} executed')


def cmd_build(a):
    prj = Project(a.project)
    rounds = a.rounds or [a.round]
    mode = a.mode
    reg = load_json(prj.wsp('cases', 'cases.json'))
    pend = [c['id'] for c in reg['cases'] if c['status'] == 'Active' and c.get('text_status') != 'filled']
    if pend and not a.allow_drafts:
        print(f'refused: {len(pend)} case(s) still draft/stale (apply_text.py --list-pending); '
              f'--allow-drafts renders a layout preview only', file=sys.stderr)
        return 1
    chg = a.change or change_text(prj, mode, rounds)
    rc = 0
    if mode in ('full', 'sad-change'):
        for w in ('strategy', 'guide'):
            if not prj.wsp('docs', f'{w}_content.json').exists():
                sh('docs/draft_docs.py', '--project', prj.path, '--what', w)
            rc |= sh('docs/build_docx.py', '--project', prj.path, '--what', w, '--change', chg)
        rc |= sh('docs/build_xlsx.py', '--project', prj.path, '--what', 'cases', '--change', chg)
        rc |= sh('docs/build_xlsx.py', '--project', prj.path, '--what', 'trace', '--change', chg)
    if mode in ('full', 'sad-change', 'execute'):
        rc |= sh('docs/build_xlsx.py', '--project', prj.path, '--what', 'record', '--round', rounds[-1], '--change', chg)
    if mode == 'regression':
        rc |= sh('docs/build_xlsx.py', '--project', prj.path, '--what', 'regression', '--round', rounds[-1], '--change', chg)
    rc |= sh('docs/build_xlsx.py', '--project', prj.path, '--what', 'report', '--rounds', *rounds, '--change', chg)
    if a.allow_drafts:
        out = prj.resolve(prj.get('output.dir')) if prj.get('output.dir') else prj.wsp('out')
        for f in out.glob('*.*'):
            if '_DRAFT' not in f.stem and f.stat().st_mtime > dt.datetime.now().timestamp() - 600:
                f.replace(f.with_name(f.stem + '_DRAFT' + f.suffix))
        print('layout preview only: files renamed *_DRAFT, not deliverables')
    elif mode in ('full', 'sad-change') and rc == 0:
        cmd_baseline(a)
    return rc


def cmd_baseline(a):
    prj = Project(a.project)
    src = prj.wsp('sad', 'arch_model.json')
    dst = baseline_path(prj)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    save_json(prj.wsp('baseline', 'baseline.json'), {'date': dt.date.today().isoformat(),
                                                     'sad': load_json(src)['meta']['source'],
                                                     'sha256': load_json(src)['meta']['sha256']})
    print(f'baseline frozen: {dst}')
    return 0


def cmd_check(a):
    prj = Project(a.project)
    args = ['--project', prj.path, '--mode', a.mode]
    if a.rounds:
        args += ['--rounds', *a.rounds]
    elif a.round:
        args += ['--round', a.round]
    return sh('check.py', *args)


def main() -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('init', 'status', 'ingest', 'design', 'docs', 'host', 'run', 'regress', 'build', 'baseline', 'check'):
        p = sub.add_parser(name)
        p.add_argument('--project', required=True)
        if name == 'status':
            p.add_argument('--regression', action='store_true')
            p.add_argument('--previous')
        if name == 'docs':
            p.add_argument('--force', action='store_true')
        if name == 'host':
            p.add_argument('sub', choices=['yml', 'standins', 'boundary', 'probe', 'skeleton'])
            p.add_argument('--force', action='store_true')
        if name == 'run':
            p.add_argument('--round', required=True)
            p.add_argument('--selection', action='store_true')
            p.add_argument('--ceedling', action='store_true')
        if name == 'regress':
            p.add_argument('--previous', required=True)
            p.add_argument('--round', required=True)
            p.add_argument('--svn')
            p.add_argument('--git')
            p.add_argument('--changed-files', nargs='*')
        if name in ('build', 'check'):
            p.add_argument('--mode', required=True, choices=['full', 'sad-change', 'execute', 'regression'])
            p.add_argument('--round')
            p.add_argument('--rounds', nargs='*')
        if name == 'build':
            p.add_argument('--change', default='')
            p.add_argument('--allow-drafts', action='store_true')
    a = ap.parse_args()
    return globals()[f'cmd_{a.cmd}'](a)


if __name__ == '__main__':
    sys.exit(main())

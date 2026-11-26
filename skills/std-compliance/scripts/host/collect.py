"""Run Ceedling and map test results to host-test checklist items.

Mapping is by marker only (`/* STD: <id>[, <id>] */` governs the test functions that follow it, up to
the next marker) — never by guessing from test names. An item passes when ALL its tests pass; any
failure fails it; ignored / missing tests leave it 未检查.
"""
import subprocess

import core
from core import FAIL, NOTRUN, PASS

from host.gen_project import dirs


def run_and_collect(prj, items, build=True, test=None):
    hd, td, _ = dirs(prj)
    if build:
        if not (hd / "project.yml").exists():
            raise SystemExit("no project.yml: run `stdc.py host gen` first")
        r = subprocess.run(["ceedling", f"test:{test}" if test else "test:all"], cwd=hd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", shell=True)
        (prj.wsp("results")).mkdir(parents=True, exist_ok=True)
        (prj.wsp("results", "ceedling_stdout.log")).write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
        print(f"ceedling exit {r.returncode} (log: {prj.wsp('results', 'ceedling_stdout.log')})")
    marks, unmarked = core.test_marks(td)
    res = core.ceedling_results(hd)
    per = {}
    for key, ids in marks.items():
        for i in ids:
            per.setdefault(i, []).append((key, res.get(key)))
    known = {i["id"] for i in items}
    out = {}
    for it in items:
        tests = per.get(it["id"], [])
        if not tests:
            out[it["id"]] = {"verdict": NOTRUN, "evidence": "无标记测试", "tests": []}
            continue
        sts = [(k, (r or {}).get("status", "not_run"), (r or {}).get("message", "")) for k, r in tests]
        # a crashed test executable produced no verdict: it is a test-environment failure, never 不符合
        sts = [(k, "crashed" if (s_ == "fail" and "crashed" in m.lower()) else s_, m) for k, s_, m in sts]
        if any(s == "fail" for _, s, _ in sts):
            v = FAIL
        elif any(s == "crashed" for _, s, _ in sts):
            v = NOTRUN
        elif all(s == "pass" for _, s, _ in sts):
            v = PASS
        else:
            v = NOTRUN
        ev = "; ".join(f"{k}={s}{(' (' + m + ')') if m else ''}" for k, s, m in sts)
        out[it["id"]] = {"verdict": v, "evidence": ev, "tests": [k for k, _, _ in sts]}
    core.save_json(prj.wsp("results", "host.json"), out)
    stray = sorted({i for ids in marks.values() for i in ids} - known)
    print(f"host-test items {len(items)}: " + ", ".join(f"{v} {sum(1 for r in out.values() if r['verdict'] == v)}"
                                                       for v in (PASS, FAIL, NOTRUN)))
    if unmarked:
        print(f"[warn] {len(unmarked)} tests without STD marker: {', '.join(unmarked[:6])}")
    if stray:
        print(f"[warn] markers reference unknown / not applicable items: {', '.join(stray[:8])}")

"""Round results (ws/results/round_<name>.json) and the metrics every deliverable shares.

Round file schema
  {"round": "1" | "R1", "type": "first" | "regression", "date": "YYYY-MM-DD",
   "software_version": "...", "tester": "...", "selected": ["SWIT-00001", ...],
   "results": {"SWIT-00001": {"verdict": "pass|fail|na|blocked|skipped|not_run",
                              "actual": "...", "defects": ["BUG-12"], "evidence": "test_x.c::test_y",
                              "reason": "..."}},
   "coverage": {"objects": [{"name": "DRV", "version": "...", "functions_total": n, "functions_hit": n,
                             "calls_total": n, "calls_hit": n}],
                "total": {...same keys...}},
   "environment_difference": "..."}

Counting rules (one implementation for records, report and checks):
  - verdict "na" is only legal for execution == "swe6" (transferred to SWE.6); such cases are
    reported separately and excluded from execution-rate and pass-rate denominators
  - "not_run" / "skipped" / "blocked" are not executed; they are never counted as passed
  - a case passes only if verdict == "pass"
"""
from __future__ import annotations

from pathlib import Path

from common import load_json

VERDICTS = ('pass', 'fail', 'na', 'blocked', 'skipped', 'not_run')
EXECUTED = ('pass', 'fail')
CATS = ('interface', 'dynamic', 'resource', 'performance')


def load_round(path: str | Path) -> dict:
    r = load_json(path)
    r.setdefault('results', {})
    r.setdefault('selected', list(r['results'].keys()))
    r.setdefault('type', 'regression' if str(r.get('round', '')).upper().startswith('R') else 'first')
    return r


def verdict(rnd: dict, cid: str) -> str:
    v = (rnd['results'].get(cid) or {}).get('verdict', 'not_run')
    return v if v in VERDICTS else 'not_run'


def metrics(cases_by_id: dict, rnd: dict, ids=None) -> dict:
    ids = list(ids if ids is not None else rnd['selected'])
    m = {'selected': 0, 'executed': 0, 'passed': 0, 'failed': 0, 'not_executed': 0, 'transferred': 0,
         'not_executed_ids': [], 'failed_ids': [], 'transferred_ids': [], 'illegal_na': []}
    for cid in ids:
        c = cases_by_id.get(cid)
        if c is None:
            continue
        v = verdict(rnd, cid)
        if c.get('execution') == 'swe6':
            m['transferred'] += 1
            m['transferred_ids'].append(cid)
            continue
        m['selected'] += 1
        if v == 'na':
            m['illegal_na'].append(cid)
            m['not_executed'] += 1
            m['not_executed_ids'].append(cid)
        elif v in EXECUTED:
            m['executed'] += 1
            if v == 'pass':
                m['passed'] += 1
            else:
                m['failed'] += 1
                m['failed_ids'].append(cid)
        else:
            m['not_executed'] += 1
            m['not_executed_ids'].append(cid)
    m['execution_rate'] = (m['executed'] / m['selected']) if m['selected'] else None
    m['pass_rate'] = (m['passed'] / m['executed']) if m['executed'] else None
    return m


def by_category(cases_by_id, rnd):
    out = {}
    for cat in CATS:
        ids = [cid for cid in rnd['selected'] if cases_by_id.get(cid, {}).get('category') == cat]
        out[cat] = metrics(cases_by_id, rnd, ids)
    return out


def ratio(hit, total):
    return (hit / total) if total else None

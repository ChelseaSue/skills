"""Release gate for a compliance report. Exit code 1 when any FAIL check triggers.

FAIL
  - an item without id / standard / clause / method, or with an unknown method
  - a `target` item judged 符合 (real-time / physical conformance cannot be shown on the host)
  - an applicable item judged 不符合 without evidence
  - a review verdict that is not one of the allowed verdicts
  - host markers, reviews, notes, applicability_overrides or findings.related referencing items that do not exist
WARN
  - an item judged 不符合 by a rule or test without a note (root cause / fix) in std_project.json notes
  - applicable items still 未检查
  - items not yet verified against the standard text (source.verified false)
"""
import core
from core import FAIL, METHODS, PASS, TARGET, VERDICTS


def verify(prj, items, rows):
    fails, warns = [], []
    for it in items:
        for k in ("id", "standard", "clause", "method"):
            if not it.get(k):
                fails.append(f"{it.get('id', '?')}: 缺少字段 {k}")
        if it.get("method") not in METHODS:
            fails.append(f"{it.get('id')}: 未知方法 {it.get('method')}")
    for r in rows:
        iid = r["item"]["id"]
        if r["item"].get("method") == "target" and r["verdict"] == PASS:
            fails.append(f"{iid}: target 条款不得判“符合”")
        if r["verdict"] == FAIL and not r["evidence"]:
            fails.append(f"{iid}: “不符合”缺少证据")
        if r["verdict"] not in VERDICTS:
            fails.append(f"{iid}: 非法结论 {r['verdict']}")
        if r["applicable"] and r["verdict"] == core.NOTRUN:
            warns.append(iid)
    for iid, rv in prj.get("reviews", {}).items():
        if rv.get("verdict") not in VERDICTS:
            fails.append(f"reviews.{iid}: 非法结论 {rv.get('verdict')}")
        if rv.get("verdict") == PASS and next((i for i in items if i["id"] == iid and i.get("method") == "target"), None):
            fails.append(f"reviews.{iid}: target 条款不得经评审判“符合”")
    from host.gen_project import dirs
    _, td, _ = dirs(prj)
    if td.exists():
        marks, _ = core.test_marks(td)
        known = {i["id"] for i in items}
        for key, ids in marks.items():
            for i in ids:
                if i not in known:
                    fails.append(f"{key}: 标记引用不存在的检查项 {i}")
    known = {i["id"] for i in items}
    for sect in ("reviews", "notes", "applicability_overrides"):
        for iid in prj.get(sect, {}):
            if iid not in known:
                fails.append(f"{sect}.{iid}: 引用不存在的检查项")
    for f in prj.get("findings", []):
        for iid in f.get("related", []):
            if iid not in known:
                fails.append(f"findings.{f.get('id', '?')}: 关联不存在的检查项 {iid}")
    # review evidence already states cause and fix; rule/test evidence only states the symptom
    nonote = [r["item"]["id"] for r in rows if r["verdict"] == FAIL and r["source"] != "review"
              and r["item"]["id"] not in prj.get("notes", {})]
    unver = [i["id"] for i in items if not i.get("source", {}).get("verified")]
    for f in fails:
        print(f"FAIL  {f}")
    if warns:
        print(f"WARN  {len(warns)} 个适用检查项未检查：{', '.join(warns[:15])}{' …' if len(warns) > 15 else ''}")
    if nonote:
        print(f"WARN  {len(nonote)} 条“不符合”没有 notes（根因/整改）：{', '.join(nonote)}")
    if unver:
        print(f"WARN  {len(unver)} 个检查项未对照原文核对")
    print("verify: " + ("FAIL" if fails else "PASS") + f"（FAIL {len(fails)}，未检查 {len(warns)}，未核对 {len(unver)}）")
    return 1 if fails else 0

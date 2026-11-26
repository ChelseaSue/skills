"""Deliverables: 协议符合性矩阵.xlsx + 协议符合性检查报告.md (into <ws>/report/).

Counting rules (also in references/report-format.md):
  符合率 = 符合 / (符合 + 不符合 + 未检查)  — 不适用 and 转SWE.6/HIL are excluded from the denominator,
  and 未检查 stays IN it so an unfinished check cannot inflate the rate.
"""
import collections
import datetime

import core
from core import FAIL, NA, NOTRUN, PASS, TARGET

COLS = [("检查项ID", 16), ("标准", 14), ("版次", 7), ("条款", 10), ("标题", 34), ("要点（自述）", 60), ("方法", 10),
        ("适用", 6), ("结论", 12), ("证据", 70), ("结论来源", 10), ("原文核对", 10), ("页码", 6)]
FILL = {PASS: "C6EFCE", FAIL: "FFC7CE", NA: "EDEDED", TARGET: "DDEBF7", NOTRUN: "FFEB9C"}
METHOD_ZH = {"config": "配置核对", "design": "设计评审", "host-test": "宿主机测试", "target": "目标机/HIL"}


def rate(c):
    den = c.get(PASS, 0) + c.get(FAIL, 0) + c.get(NOTRUN, 0)
    return f"{100.0 * c.get(PASS, 0) / den:.1f}%" if den else "—"


def build(prj, rows, standards):
    out = prj.wsp("report")
    out.mkdir(parents=True, exist_ok=True)
    name = prj.get("project.name", "project")
    xlsx = out / f"{name}_协议符合性矩阵.xlsx"
    md = out / f"{name}_协议符合性检查报告.md"
    _xlsx(xlsx, rows, standards, prj)
    _md(md, prj, rows, standards)
    print(f"written {xlsx}\nwritten {md}")


def _row_values(r, standards):
    it = r["item"]
    std = standards.get(it.get("standard_key", ""), {})
    src = it.get("source", {})
    return [it["id"], it.get("standard", ""), std.get("edition", it.get("edition", "")), it.get("clause", ""),
            it.get("title", ""), it.get("requirement", ""), METHOD_ZH.get(it.get("method"), it.get("method", "")),
            "是" if r["applicable"] else "否", r["verdict"], r["evidence"], r["source"],
            "已核对" if src.get("verified") else "未核对", src.get("page", "")]


def _findings(prj):
    """findings: observations that are not a verdict on any clause (layering breaches, dead parameters, config drift)."""
    out = []
    for i, f in enumerate(prj.get("findings", []), 1):
        out.append({"id": f.get("id", f"F{i:02d}"), "topic": f.get("topic", ""), "detail": f.get("detail", ""),
                    "related": "、".join(f.get("related", []))})
    return out


def _xlsx(path, rows, standards, prj=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "符合性矩阵"
    ws.append([c for c, _ in COLS])
    for i, (_, w) in enumerate(COLS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
        ws.cell(1, i).font = Font(bold=True)
        ws.cell(1, i).fill = PatternFill("solid", fgColor="D9D9D9")
    for r in rows:
        ws.append(_row_values(r, standards))
        c = ws.cell(ws.max_row, 9)
        c.fill = PatternFill("solid", fgColor=FILL.get(r["verdict"], "FFFFFF"))
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    st = wb.create_sheet("统计")
    st.append(["标准", "检查项", PASS, FAIL, NOTRUN, NA, TARGET, "符合率"])
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        by[r["item"].get("standard", "?")][r["verdict"]] += 1
    tot = collections.Counter()
    for s, c in sorted(by.items()):
        st.append([s, sum(c.values())] + [c.get(k, 0) for k in (PASS, FAIL, NOTRUN, NA, TARGET)] + [rate(c)])
        tot.update(c)
    st.append(["合计", sum(tot.values())] + [tot.get(k, 0) for k in (PASS, FAIL, NOTRUN, NA, TARGET)] + [rate(tot)])
    for cell in st[1]:
        cell.font = Font(bold=True)
    st.column_dimensions["A"].width = 22

    fd = _findings(prj) if prj else []
    if fd:
        sh = wb.create_sheet("发现项")
        sh.append(["编号", "主题", "说明", "关联检查项"])
        for i, w in enumerate((8, 30, 100, 24), 1):
            sh.column_dimensions[get_column_letter(i)].width = w
            sh.cell(1, i).font = Font(bold=True)
        for f in fd:
            sh.append([f["id"], f["topic"], f["detail"], f["related"]])
        for row in sh.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    for title, v in (("不符合项", FAIL), ("转SWE.6-HIL", TARGET), ("未检查", NOTRUN)):
        sh = wb.create_sheet(title)
        sh.append([c for c, _ in COLS])
        for i, (_, w) in enumerate(COLS, 1):
            sh.column_dimensions[get_column_letter(i)].width = w
            sh.cell(1, i).font = Font(bold=True)
        for r in rows:
            if r["verdict"] == v:
                sh.append(_row_values(r, standards))
    try:
        wb.save(path)
    except PermissionError:                      # file open in Excel: keep going with a side copy
        import datetime as _dt
        alt = path.with_name(f"{path.stem}_{_dt.datetime.now():%H%M%S}{path.suffix}")
        wb.save(alt)
        print(f"[warn] {path.name} 被占用（可能在 Excel 中打开），已另存为 {alt.name}")


def _esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def _md(path, prj, rows, standards):
    node = prj.node
    tot = collections.Counter(r["verdict"] for r in rows)
    app = [r for r in rows if r["applicable"]]
    lines = [f"# {prj.get('project.name', '')} 协议符合性检查报告", "",
             f"| 项 | 内容 |", "|---|---|",
             f"| 软件版本 | {prj.get('project.version', '')} |",
             f"| 生成日期 | {datetime.date.today().isoformat()} |",
             f"| 标准包 | {', '.join(prj.get('packs', []))} |",
             f"| 节点 | 总线 {'/'.join(node.get('bus', []))}；LIN 角色 {node.get('lin_role', '—')}；UDS 角色 {node.get('uds_role', '—')}；功能 {', '.join(node.get('features', []))} |",
             "", "## 1 结论摘要", "",
             f"检查项 {len(rows)} 条，适用 {len(app)} 条。符合率 {rate(tot)}（口径：符合 ÷（符合+不符合+未检查）；不适用与转 SWE.6/HIL 不计入分母）。", "",
             "| 结论 | 数量 |", "|---|---:|"] + [f"| {k} | {tot.get(k, 0)} |" for k in core.VERDICTS] + ["",
             "## 2 标准与适用范围", "", "| 标准 | 版次 | 范围 | 适用条款数 | 符合率 |", "|---|---|---|---:|---:|"]
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        by[r["item"].get("standard_key", "?")][r["verdict"]] += 1
    for k, s in standards.items():
        c = by.get(k, collections.Counter())
        n_app = sum(v for kk, v in c.items() if kk != NA)
        lines.append(f"| {s['number']} | {s['edition']} | {_esc(s.get('scope_note', ''))} | {n_app} | {rate(c)} |")
    for title, v, hint in (("3 不符合项", FAIL, "每条须有可复现证据（规则输出或失败的测试）。"),
                           ("4 未检查项", NOTRUN, "原因见“证据”列；完成后重新生成报告。"),
                           ("5 转 SWE.6 / HIL / 一致性测试的条款", TARGET, "这些条款依赖真实总线或实时时序，宿主机不判结论，不计入符合率。")):
        sel = [r for r in rows if r["verdict"] == v]
        lines += ["", f"## {title}", "", hint, ""]
        if not sel:
            lines.append("无。")
            continue
        lines += ["| 检查项 | 标准条款 | 标题 | 证据 |", "|---|---|---|---|"]
        lines += [f"| {r['item']['id']} | {_esc(r['item'].get('standard', ''))} {r['item'].get('clause', '')} | "
                  f"{_esc(r['item'].get('title', ''))} | {_esc(r['evidence'])} |" for r in sel]
    fd = _findings(prj)
    lines += ["", "## 6 发现项", "", "不针对某一条款下结论、但影响协议实现质量或可维护性的观察（越层依赖、无效参数、配置副本不一致等）。", ""]
    if fd:
        lines += ["| 编号 | 主题 | 说明 | 关联检查项 |", "|---|---|---|---|"]
        lines += [f"| {f['id']} | {_esc(f['topic'])} | {_esc(f['detail'])} | {_esc(f['related'])} |" for f in fd]
    else:
        lines.append("无。")
    unver = [r for r in rows if not r["item"].get("source", {}).get("verified")]
    lines += ["", "## 7 条款核对状态", "",
              f"{len(rows) - len(unver)} 条已对照标准原文核对，{len(unver)} 条未核对。" + ("" if not unver else
              "未核对条款：" + "、".join(r["item"]["id"] for r in unver[:30]) + ("…" if len(unver) > 30 else "")),
              "", "## 8 说明", "",
              "- 检查项的“要点”为自述概括，不是标准原文；以标准原文为准。",
              "- 完整矩阵见同目录 xlsx（含不适用条款及理由）。"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

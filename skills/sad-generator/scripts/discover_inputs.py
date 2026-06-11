#!/usr/bin/env python3
"""Scan a project root for the documents a software ARCHITECTURE document (SAD) needs, and report
what's found vs missing.

Why: step 2 of the workflow ("gap prompt") must tell the user, concretely, which inputs exist in the
project and which are missing. For a SAD the primary input is the SRS (software requirements), plus
the AU-QR-R&D-032 architecture template, plus the CAN matrix (so sequence diagrams can cite real
signals). Most of what the *template* additionally demands — RTOS/scheduling choice, CPU-load budget,
memory map, NVM data dictionary, interrupt/task partitioning, watchdog strategy, component API
contracts, deployment view — are design DECISIONS that usually live in no file yet; those are not
detectable by a directory scan, so they're surfaced by references/input-checklist.md, not here.

This only locates and buckets files (it does NOT read contents). Output is human-readable plus a JSON
block (after the marker line) so the caller can parse it if useful.

Usage:
  python3 discover_inputs.py <project_root>
  python3 discover_inputs.py <project_root> --json     # JSON only
"""
import argparse
import json
import os
import sys

# category -> (dir-name keywords, filename keywords). A file matches a category if its directory
# OR its filename contains any keyword. Categories are checked in order; first match wins — so the
# SRS (a .md/.docx inside 软件需求/) is matched before the generic template, and the 032 architecture
# template is matched before product/system requirements.
CATEGORIES = [
    ("sad_template", (["软件架构"], ["软件架构", "architecture design", "au-qr-r&d-032", "au-qr-rd-032", "sad"])),
    ("srs",          (["软件需求"], ["软件需求规范", "srs", "software requirement", "软件需求"])),
    ("comm_matrix",  (["通信矩阵", "通讯矩阵"], ["通信矩阵", "通讯矩阵", "can_matrix", "canmatrix", "matrix", "dbc", "ldf"])),
    ("system_req",   (["系统需求"], ["系统需求", "system requirement"])),
    ("product_req",  (["产品需求"], ["产品需求", "product requirement"])),
    ("hsi",          (["hsi", "HSI"], ["hsi", "端口定义", "管脚", "pin", "接口定义"])),
    ("peripheral",   (["外设"], ["外设", "负载", "硬件需求规格", "peripheral", "load"])),
    ("hw_arch",      (["硬件架构"], ["框图", "架构", "block"])),
    ("schematic",    (["原理图"], ["原理图", "schematic"])),
    ("plan",         (["计划"], ["计划", "plan"])),
]

# what the SAD workflow expects from files on disk, and what absence means.
EXPECTED = {
    "srs":          ("软件需求规范 SRS（主输入）", "必需：SAD 的主输入，逐条 HOD_SRS_* 需求由此派生架构并追溯"),
    "sad_template": ("软件架构模板 AU-QR-R&D-032", "必需：最终 docx 的格式基底（.doc 会自动转 .docx）"),
    "comm_matrix":  ("通信矩阵 (CAN/LIN)", "强烈建议：时序图标注真实信号名/报文ID/收发方向（第 9 章）"),
    "system_req":   ("系统需求文档", "可选：追溯链上游参考、术语/参考文献核对"),
    "product_req":  ("产品需求文档", "可选：系统简介、软件特性核对"),
    "hsi":          ("HSI 端口/管脚定义", "可选：硬件约束/IO 约束、软件外部接口（第 3/4 章）"),
    "peripheral":   ("外设参数/硬件需求规格", "可选：IO 约束、负载与驱动约束"),
    "hw_arch":      ("硬件架构框图", "可选：部署视图/软件上下文图参考（vsdx 可转 PNG）"),
}


def classify(path):
    d = os.path.dirname(path).lower()
    name = os.path.basename(path).lower()
    for cat, (dir_kw, name_kw) in CATEGORIES:
        if any(k.lower() in name for k in name_kw) or any(k.lower() in d for k in dir_kw):
            return cat
    return None


DOC_EXTS = {".docx", ".doc", ".xlsx", ".xls", ".pdf", ".vsdx", ".md"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--json", action="store_true", help="print JSON only")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    found = {cat: [] for cat, _ in CATEGORIES}
    for dirpath, _, files in os.walk(root):
        if any(seg.startswith(".") for seg in dirpath.split(os.sep)):
            continue
        for f in files:
            if f.startswith("~$") or os.path.splitext(f)[1].lower() not in DOC_EXTS:
                continue
            full = os.path.join(dirpath, f)
            cat = classify(full)
            if cat:
                found[cat].append(os.path.relpath(full, root))

    result = {"root": root, "found": found,
              "missing": [c for c in EXPECTED if not found.get(c)]}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"项目根目录：{root}\n")
    print("=== 已找到的输入 ===")
    for cat, (label, note) in EXPECTED.items():
        files = found.get(cat, [])
        if files:
            print(f"  ✅ {label}（{note}）")
            for fp in files:
                print(f"       - {fp}")
    print("\n=== 缺失的文件级输入 ===")
    any_missing = False
    for cat, (label, note) in EXPECTED.items():
        if not found.get(cat):
            any_missing = True
            print(f"  ❌ {label} —— {note}")
    if not any_missing:
        print("  （预期文件级输入均已找到）")

    print("\n=== 注意：以下是 SAD 模板要求、但通常无文件可扫的“设计决策类”输入 ===")
    print("  （这些不会被目录扫描发现，需在缺口提示里向用户点出，详见 references/input-checklist.md）")
    for item in [
        "RTOS / 调度原则选择与依据（第 6 章备选论证、7.1 实时架构）",
        "CPU 负载预估与最坏情况计算（5.6 / 7.1）",
        "内存大小与内存映射（7.3）",
        "NVM 数据字典：地址/长度/默认值/掉电策略（6 章备选 + 7.4 NVM）",
        "中断/循环任务划分与时基（5.1/5.2/7.1）",
        "看门狗与故障处理策略（7.4 鲁棒性）",
        "各组件 API/服务契约（第 8 章软件组件）",
        "部署视图、内存/工具链约束（3.2 / 4 设计约束）",
    ]:
        print(f"  ⚠️ {item}")

    extras = {c: found[c] for c in found if c not in EXPECTED and found[c]}
    if extras:
        print("\n=== 其它发现（参考）===")
        for c, fl in extras.items():
            for fp in fl:
                print(f"  · {fp}")

    print("\n--- JSON ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

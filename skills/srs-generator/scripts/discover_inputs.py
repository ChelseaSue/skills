#!/usr/bin/env python3
"""Scan a project root for the documents an SRS needs, and report what's found vs missing.

Why: step 2 of the workflow ("gap prompt") must tell the user, concretely, which supplementary
inputs exist in the project and which are missing. This classifies files by directory and filename
keywords so the model can produce that prompt without re-deriving the project layout each time.

It does NOT read file contents — just locates and buckets them. Output is human-readable plus a JSON
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
# OR its filename contains any keyword. Categories are checked in order; first match wins.
CATEGORIES = [
    ("system_req",  (["系统需求"], ["系统需求", "system requirement", "system_req"])),
    ("srs_template",(["软件需求"], ["软件需求", "srs", "software requirement", "au-qr"])),
    ("product_req", (["产品需求"], ["产品需求", "product requirement"])),
    ("hsi",         (["hsi", "HSI"], ["hsi", "端口定义", "管脚", "pin", "接口定义"])),
    ("comm_matrix", (["通信矩阵", "通讯矩阵"], ["通信矩阵", "通讯矩阵", "can_matrix", "canmatrix", "matrix", "dbc", "ldf"])),
    ("peripheral",  (["外设"], ["外设", "负载", "硬件需求规格", "peripheral", "load"])),
    ("hw_arch",     (["硬件架构"], ["框图", "架构", "architecture", "block"])),
    ("schematic",   (["原理图"], ["原理图", "schematic"])),
    ("plan",        (["计划"], ["计划", "plan"])),
]

# what the SRS workflow expects, and whether absence blocks/just-TBDs
EXPECTED = {
    "system_req":  ("系统需求文档", "必需：SRS 的主输入"),
    "srs_template":("SRS 模板", "必需：最终 docx 的格式基底"),
    "product_req": ("产品需求文档", "可选：补 2.1/2.2 产品定义与功能列表"),
    "hsi":         ("HSI 端口/管脚定义", "可选：补 3.2 HSI 与 3.6 信号映射"),
    "comm_matrix": ("通信矩阵 (CAN/LIN)", "可选：补 3.5 通讯管理、3.6 逐信号映射、COM 模块 I/O"),
    "peripheral":  ("外设参数/硬件需求规格", "可选：补各 I/O 的范围/单位/来源目标"),
    "hw_arch":     ("硬件架构框图", "可选：嵌入系统/硬件框图（vsdx 自动转 PNG）"),
    "schematic":   ("原理图", "可选：参考"),
}

DOC_EXTS = {".docx", ".doc", ".xlsx", ".xls", ".pdf", ".vsdx", ".md"}


def classify(path):
    d = os.path.dirname(path).lower()
    name = os.path.basename(path).lower()
    for cat, (dir_kw, name_kw) in CATEGORIES:
        if any(k.lower() in d for k in dir_kw) or any(k.lower() in name for k in name_kw):
            return cat
    return None


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
    print("\n=== 缺失的输入 ===")
    any_missing = False
    for cat, (label, note) in EXPECTED.items():
        if not found.get(cat):
            any_missing = True
            print(f"  ❌ {label} —— {note}")
    if not any_missing:
        print("  （预期输入均已找到）")
    # other categories (plan etc.) just listed for awareness
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

#!/usr/bin/env python3
"""Scan a project root for the inputs CODE GENERATION needs, and report found vs missing.

Why: step 2 ("gap prompt") must tell the user concretely which inputs exist and which are missing.
For code generation the primary drivers are the SAD (software architecture) and SRS (software
requirements), plus a base SDK code root (BSP/MCAL/OS/RTOS/existing drivers) to build on, plus the
CAN matrix (so comms logic cites real signals) and the MISRA C:2012 PDF. Implementation-level details
(pin map, clocks, instance numbers, task priorities, buffer sizes, NVM layout...) usually live in no
single file and are surfaced by references/input-checklist.md, not here.

This only locates/buckets files (does NOT read contents). Output is human-readable + a JSON block
after the marker line.

Usage:
  python3 discover_inputs.py <project_root>
  python3 discover_inputs.py <project_root> --json
"""
import argparse
import json
import os
import sys

# category -> (dir keywords, filename keywords). First match wins (order matters).
# Keywords are intentionally bilingual + generic so discovery works on any project layout, not just
# the Chinese company folder convention. This is a best-effort locator; the caller confirms paths
# with the user regardless, and can always pass explicit file paths instead of relying on this.
CATEGORIES = [
    ("sad",          (["软件架构", "architecture", "sw_arch", "swarch", "arch_design", "sad"],
                      ["软件架构", "architecture design", "software architecture", "au-qr-r&d-032", "sad", "swad"])),
    ("srs",          (["软件需求", "software_req", "sw_req", "swrs", "srs"],
                      ["软件需求规范", "软件需求", "srs", "swrs", "software requirement", "sw requirement"])),
    ("comm_matrix",  (["通信矩阵", "通讯矩阵", "dbc", "ldf", "communication", "can_matrix", "network_matrix"],
                      ["通信矩阵", "通讯矩阵", "can_matrix", "canmatrix", "comm_matrix", "matrix", ".dbc", ".ldf", ".arxml"])),
    ("misra",        (["编码规范", "misra", "coding_standard", "coding_guideline", "guideline"],
                      ["misra", "coding standard", "coding guideline", "编码规范", "cert-c"])),
    ("system_req",   (["系统需求", "system_req", "sys_req", "sysrs"],
                      ["系统需求", "system requirement", "sys requirement", "sysrs"])),
    ("product_req",  (["产品需求", "product_req", "prd", "prod_req"],
                      ["产品需求", "product requirement", "prd"])),
    ("hsi_pinmux",   (["hsi", "引脚定义", "pinmux", "pinout", "pin_def", "io_list"],
                      ["hsi", "端口定义", "管脚", "pinmux", "pinout", "引脚", "pin map", "pin_def", "io list"])),
]

# A source code root is detected by presence of C sources + tell-tale SDK dirs, handled separately.
SDK_DIR_HINTS = {"mcal", "bsp", "os", "freertos", "source", "src", "hal", "cdd", "driver", "drivers"}

DOC_EXTS = {".docx", ".doc", ".xlsx", ".xls", ".pdf", ".vsdx", ".md", ".dbc", ".ldf"}

EXPECTED = {
    "sad":         ("软件架构设计 SAD（主驱动）", "必需：定层/定模块/定接口/定状态机时序，代码据此生成"),
    "srs":         ("软件需求规范 SRS", "必需：每条需求落到模块/函数并做 100% 追溯"),
    "sdk_root":    ("基础 SDK 代码根（BSP/MCAL/OS/RTOS/已有驱动）", "必需：生成代码要对接的底座，HAL 实现层在此落地"),
    "comm_matrix": ("通信矩阵 / DBC", "建议：CAN 收发对接真实报文/信号/周期/方向；缺则信号 TBD"),
    "misra":       ("MISRA C:2012 规范 PDF", "建议：规则权威；日常用 cppcheck --addon=misra 自动门禁"),
    "system_req":  ("系统需求文档", "可选：追溯链上游参考"),
    "product_req": ("产品需求文档", "可选：功能/特性核对"),
    "hsi_pinmux":  ("HSI 端口/管脚(PINMUX)定义", "可选但重要：管脚/外设实例等实现级信息来源"),
}


def classify(path):
    d = os.path.dirname(path).lower()
    name = os.path.basename(path).lower()
    for cat, (dir_kw, name_kw) in CATEGORIES:
        if any(k.lower() in name for k in name_kw) or any(k.lower() in d for k in dir_kw):
            return cat
    return None


def _has_c_below(d):
    for dp, _, files in os.walk(d):
        if any(seg.startswith(".") for seg in dp.split(os.sep)):
            continue
        if any(f.lower().endswith((".c", ".h")) for f in files):
            return True
    return False


def find_sdk_roots(root):
    """Heuristic: a dir is a likely SDK/source root if it contains C sources somewhere beneath AND
    either its own name or one of its immediate subdir names is an SDK-ish name (Source/src/MCAL/HAL/
    OS/BSP/driver...). Report the shallowest such dirs (don't descend once one is found)."""
    roots = []
    for dirpath, dirs, files in os.walk(root):
        if any(seg.startswith(".") for seg in dirpath.split(os.sep)):
            continue
        base = os.path.basename(dirpath).lower()
        low_dirs = {d.lower() for d in dirs}
        name_hit = (base in SDK_DIR_HINTS) or bool(low_dirs & SDK_DIR_HINTS)
        if name_hit and _has_c_below(dirpath):
            roots.append(os.path.relpath(dirpath, root))
            dirs[:] = []  # found a root here; don't descend further
    return roots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--json", action="store_true")
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
            cat = classify(os.path.join(dirpath, f))
            if cat:
                found[cat].append(os.path.relpath(os.path.join(dirpath, f), root))

    sdk_roots = find_sdk_roots(root)

    result = {
        "root": root,
        "found": found,
        "sdk_roots": sdk_roots,
        "expected": {k: list(v) for k, v in EXPECTED.items()},
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"# 代码生成输入盘点 @ {root}\n")
    order = ["sad", "srs", "sdk_root", "comm_matrix", "misra", "hsi_pinmux", "system_req", "product_req"]
    for cat in order:
        label, why = EXPECTED[cat]
        if cat == "sdk_root":
            hits = sdk_roots
        else:
            hits = found.get(cat, [])
        mark = "✅" if hits else "❌ 缺失"
        print(f"## {label}  [{mark}]")
        print(f"   作用：{why}")
        for h in hits[:10]:
            print(f"     - {h}")
        if len(hits) > 10:
            print(f"     - ...（共 {len(hits)} 个）")
        print()

    print("---")
    print("下一步：把缺失项点名给用户（见 references/input-checklist.md 的提示范例），")
    print("并提醒实现级信息（管脚/时钟/实例号/任务优先级/缓冲尺寸/NVM 布局/CAN 报文细节）多半不在文件里，需确认。")
    print("\n<<<JSON>>>")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

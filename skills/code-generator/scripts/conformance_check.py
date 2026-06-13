#!/usr/bin/env python3
"""Run the conformance checklist (references/conformance-checklist.md) and emit a pass/fail report.

Aggregates the automatable [A] checks:
  - Layering: invokes check_layering.py (0 violations expected)
  - MISRA:    invokes run_misra.py (0 Mandatory/Required, dynamic-memory grep == 0)
  - Directory: every .c/.h maps to a layer in layers.json (no orphan files)
  - Traceability: every SRS requirement id appears in some @implements; no orphan @implements ids
Manual [M] items are listed for the generator to confirm with evidence.

Usage:
  python3 conformance_check.py --root <code_root> --spec module_spec.json --layers layers.json --srs srs.md
  python3 conformance_check.py --root <code_root> --layers layers.json --srs srs.md --json
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
IMPLEMENTS_RE = re.compile(r"@implements\s+([^\n*]+)")
# Default requirement-id pattern is broad enough for common schemes across projects:
#   PREFIX_SRS_001 / HOD_SRS_12 / SWREQ_45 / SR-123 / REQ-001 / [FR-7] ...
# Override with --req-pattern '<regex with one capture group>' for project-specific id formats.
DEFAULT_REQ_PATTERN = r"\b((?:[A-Z][A-Z0-9]{1,9}[-_])?(?:SRS|SWRS|SWREQ|REQ|SR|FR|NFR)[-_][A-Za-z0-9._]+)\b"
DYNMEM_RE = re.compile(r"\b(malloc|calloc|realloc|free)\s*\(")


def run_json(script, *cli):
    cmd = [sys.executable, os.path.join(HERE, script), *cli, "--json"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(p.stdout), p.returncode
    except json.JSONDecodeError:
        return {"_raw": p.stdout + p.stderr}, p.returncode


def collect_implements(root):
    ids = set()
    for dp, _, files in os.walk(root):
        if any(s.startswith(".") for s in dp.split(os.sep)):
            continue
        for f in files:
            if f.lower().endswith((".c", ".h")):
                try:
                    txt = open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                for m in IMPLEMENTS_RE.finditer(txt):
                    for tok in re.split(r"[,\s]+", m.group(1).strip()):
                        tok = tok.strip().strip(".")
                        if tok and tok != "（待补充需求":
                            ids.add(tok)
    return ids


def srs_req_ids(srs_path, req_re):
    if not srs_path or not os.path.isfile(srs_path):
        return set()
    txt = open(srs_path, encoding="utf-8", errors="replace").read()
    return set(req_re.findall(txt))


def grep_dynmem(root):
    hits = []
    for dp, _, files in os.walk(root):
        if any(s.startswith(".") for s in dp.split(os.sep)):
            continue
        for f in files:
            if f.lower().endswith((".c", ".h")):
                p = os.path.join(dp, f)
                try:
                    for ln, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
                        if DYNMEM_RE.search(line) and "/*" not in line.split(DYNMEM_RE.search(line).group(0))[0][-3:]:
                            hits.append(f"{os.path.relpath(p, root)}:{ln}: {line.strip()}")
                except OSError:
                    pass
    return hits


# raw extern variable (not function): `extern <type> name ...;` with no '(' -> a shared global.
EXTERN_VAR_RE = re.compile(r'^\s*extern\s+(?!"C")[^;()]+\b[A-Za-z_]\w*\s*(\[[^\]]*\])?\s*;')


def grep_extern_globals(root):
    hits = []
    for dp, _, files in os.walk(root):
        if any(s.startswith(".") for s in dp.split(os.sep)):
            continue
        for f in files:
            if f.lower().endswith((".c", ".h")):
                p = os.path.join(dp, f)
                try:
                    for ln, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
                        if EXTERN_VAR_RE.match(line) and "(" not in line:
                            hits.append(f"{os.path.relpath(p, root)}:{ln}: {line.strip()}")
                except OSError:
                    pass
    return hits


def layer_of(relpath, path_map):
    norm = relpath.replace("\\", "/")
    for sub, layer in path_map.items():
        if sub.replace("\\", "/") in norm:
            return layer
    return None


def check_file_prefix(root, layers_cfg):
    """Each source file's basename should start with its layer's declared file_prefix (if any)."""
    file_prefix = layers_cfg.get("file_prefix", {})
    path_map = layers_cfg.get("path_map", {})
    if not file_prefix:
        return None, []  # no prefixes declared -> not applicable
    bad = []
    for dp, _, files in os.walk(root):
        if any(s.startswith(".") for s in dp.split(os.sep)):
            continue
        for f in files:
            if not f.lower().endswith((".c", ".h")):
                continue
            rel = os.path.relpath(os.path.join(dp, f), root)
            lyr = layer_of(rel, path_map)
            pfx = file_prefix.get(lyr)
            if pfx and not f.startswith(pfx):
                bad.append(f"{rel}（{lyr} 期望前缀 {pfx}）")
    return (len(bad) == 0), bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--layers", required=True)
    ap.add_argument("--spec")
    ap.add_argument("--srs")
    ap.add_argument("--req-pattern", default=DEFAULT_REQ_PATTERN,
                    help="regex (one capture group) for requirement IDs; override for non-default schemes")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    req_re = re.compile(args.req_pattern)
    try:
        layers_cfg = json.load(open(args.layers, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        layers_cfg = {}

    checks = []

    lay, _ = run_json("check_layering.py", "--root", root, "--layers", args.layers)
    vc = lay.get("violation_count", -1)
    unmapped = lay.get("unmapped_files", [])
    checks.append(("A-分层", "无向上/未声明跳层/平级依赖 include", vc == 0,
                   f"违规 {vc} 条" + (f"；{lay['violations'][:3]}" if vc else "")))
    checks.append(("D-目录", "所有源文件均归层（无层外游离）", len(unmapped) == 0,
                   f"未归层 {len(unmapped)} 个" + (f"：{unmapped[:5]}" if unmapped else "")))

    pfx_ok, pfx_bad = check_file_prefix(root, layers_cfg)
    if pfx_ok is None:
        checks.append(("D-目录", "文件名层前缀（layers.json 未声明 file_prefix，跳过）", None,
                       "未声明 file_prefix，按项目 NameRules/SAD 人工核命名"))
    else:
        checks.append(("D-目录", "文件名带层前缀且与所在层一致", pfx_ok,
                       f"不一致 {len(pfx_bad)} 个" + (f"：{pfx_bad[:5]}" if pfx_bad else "")))

    extern = grep_extern_globals(root)
    checks.append(("B-模块化", "无裸 extern 全局变量（跨模块共享走访问函数/总线）", len(extern) == 0,
                   f"命中 {len(extern)} 处" + (f"：{extern[:3]}" if extern else "")))

    mis, _ = run_json("run_misra.py", "--root", root)
    if mis.get("cppcheck"):
        mc = mis.get("count", -1)
        checks.append(("E-MISRA", "cppcheck misra 违规清零/已 deviation", mc == 0,
                       f"违规 {mc} 条" + (f"；by_rule={mis.get('by_rule')}" if mc else "")))
    else:
        checks.append(("E-MISRA", "cppcheck 未装：MISRA 走人工核查", None,
                       "cppcheck 不可用，自动门禁未运行（见报告说明）"))

    dyn = grep_dynmem(root)
    checks.append(("E-内存", "无动态内存 malloc/free/...", len(dyn) == 0,
                   f"命中 {len(dyn)} 处" + (f"：{dyn[:3]}" if dyn else "")))

    impl_ids = collect_implements(root)
    req_ids = srs_req_ids(args.srs, req_re)
    if req_ids:
        uncovered = sorted(req_ids - impl_ids)
        orphans = sorted(impl_ids - req_ids)
        checks.append(("F-追溯", "每条 SRS 需求都有 @implements 覆盖", len(uncovered) == 0,
                       f"未覆盖 {len(uncovered)}：{uncovered[:10]}"))
        checks.append(("F-追溯", "无指向不存在需求的孤儿 @implements", len(orphans) == 0,
                       f"孤儿 {len(orphans)}：{orphans[:10]}"))
    else:
        checks.append(("F-追溯", "需提供 --srs 才能核对追溯", None,
                       f"已收集 @implements {len(impl_ids)} 个，但无 SRS 求差"))

    manual = [
        "C-可测试: HAL 等硬件接口为 If/Impl 拆分或等效抽象，实现可替换/可打桩",
        "C-可测试: 每个公开函数有契约注释（线程安全/ISR/阻塞/返回码）",
        "B-模块化: 同层协作经总线/公开接口，无内部直调、无循环依赖",
        "A-分层: 硬件相关全部收敛在抽象层之后，上层无寄存器直操作",
        "E-MISRA: deviation 均有就地 /* MISRA deviation Rx.y: 理由 */",
        "G-编译: 有交叉工具链则工程编译通过；缺口均为 TBD 显式占位",
    ]

    passed = sum(1 for _, _, ok, _ in checks if ok is True)
    failed = sum(1 for _, _, ok, _ in checks if ok is False)
    na = sum(1 for _, _, ok, _ in checks if ok is None)

    result = {"root": root,
              "auto": [{"area": a, "item": it, "pass": ok, "evidence": ev} for a, it, ok, ev in checks],
              "manual": manual, "summary": {"pass": passed, "fail": failed, "na": na}}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"# 一致性检查清单核验 @ {root}\n")
        for a, it, ok, ev in checks:
            mark = "✅" if ok is True else ("❌" if ok is False else "⚠️")
            print(f"  {mark} [{a}] {it}")
            if ev:
                print(f"       └ {ev}")
        print(f"\n  小结：通过 {passed}　未通过 {failed}　待人工/不适用 {na}")
        print("\n  人工核查项（生成者对照证据逐条确认）：")
        for mi in manual:
            print(f"   [ ] {mi}")
        if failed:
            print("\n  ⚠️ 存在未通过的自动项——回到对应工作流步骤修复后重跑。")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

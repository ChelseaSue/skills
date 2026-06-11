#!/usr/bin/env python3
"""Run cppcheck --addon=misra over the code root and summarize MISRA C:2012 violations.

The MISRA addon ships with cppcheck. If cppcheck is missing, this prints install guidance and
falls back to a gcc syntax/conversion pass so you still catch some issues; the conformance report
should then note "MISRA via manual review, automated gate not run".

Gate criterion: Mandatory/Required violations must be 0 (or each tied to a justified deviation
comment). Advisory violations are summarized for the user to decide.

Usage:
  python3 run_misra.py --root <code_root>
  python3 run_misra.py --root <code_root> --inc Source/Hal/If --inc Source/Bus   # extra -I dirs
  python3 run_misra.py --root <code_root> --json
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

MISRA_LINE_RE = re.compile(r"\[misra-c2012-(\d+)\.(\d+)\]")


def have(tool):
    return shutil.which(tool) is not None


def auto_inc_dirs(root):
    """Collect dirs that contain .h files, to feed cppcheck as -I (best-effort)."""
    incs = set()
    for dirpath, _, files in os.walk(root):
        if any(seg.startswith(".") for seg in dirpath.split(os.sep)):
            continue
        if any(f.lower().endswith(".h") for f in files):
            incs.add(dirpath)
    return sorted(incs)


def run_cppcheck(root, extra_incs):
    incs = auto_inc_dirs(root)
    for e in extra_incs:
        p = e if os.path.isabs(e) else os.path.join(root, e)
        incs.append(p)
    cmd = ["cppcheck", "--enable=style", "--addon=misra",
           "--suppress=missingIncludeSystem", "--inline-suppr",
           "--quiet", "--template={file}:{line}: {id}: {message}"]
    for i in incs:
        cmd.append(f"-I{i}")
    cmd.append(root)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.stdout + proc.stderr


def parse(output):
    findings = []
    for line in output.splitlines():
        m = MISRA_LINE_RE.search(line)
        if m:
            rule = f"{m.group(1)}.{m.group(2)}"
            findings.append({"rule": rule, "line": line.strip()})
        elif "misra" in line.lower():
            findings.append({"rule": "?", "line": line.strip()})
    return findings


def gcc_fallback(root):
    out = []
    inc_flags = ["-I" + d for d in auto_inc_dirs(root)]
    for dirpath, _, files in os.walk(root):
        if any(seg.startswith(".") for seg in dirpath.split(os.sep)):
            continue
        for f in files:
            if f.lower().endswith(".c"):
                full = os.path.join(dirpath, f)
                cmd = ["gcc", "-std=c11", "-fsyntax-only", "-Wall", "-Wextra",
                       "-Wconversion", *inc_flags, full]
                p = subprocess.run(cmd, capture_output=True, text=True)
                if p.stderr.strip():
                    out.append(p.stderr.strip())
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--inc", action="append", default=[], help="extra include dir (repeatable)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    if not have("cppcheck"):
        msg = ("cppcheck 未安装。安装：sudo apt-get install -y cppcheck（自带 misra 插件）。\n"
               "本次退化为 gcc 语法/转换检查；conformance 报告请注明 MISRA 未过自动门禁。")
        gcc_out = gcc_fallback(root) if have("gcc") else "（gcc 也不可用，无法做任何自动检查）"
        result = {"tool": "gcc-fallback", "cppcheck": False, "note": msg,
                  "misra_findings": [], "gcc_output": gcc_out}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("# MISRA 门禁\n  ⚠️ " + msg + "\n")
            print(gcc_out or "  （gcc 无输出，纯语法层面无报错）")
        sys.exit(0)

    output = run_cppcheck(root, args.inc)
    findings = parse(output)
    by_rule = {}
    for f in findings:
        by_rule.setdefault(f["rule"], 0)
        by_rule[f["rule"]] += 1

    result = {"tool": "cppcheck", "cppcheck": True,
              "misra_findings": findings, "count": len(findings), "by_rule": by_rule}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"# MISRA 门禁（cppcheck --addon=misra）@ {root}")
        print(f"  违规计数：{len(findings)}")
        if by_rule:
            print("  按规则：")
            for r, c in sorted(by_rule.items()):
                print(f"     R{r}: {c}")
        print()
        for f in findings[:60]:
            print(f"  - {f['line']}")
        if len(findings) > 60:
            print(f"  ...（共 {len(findings)} 条，完整见 --json）")
        if not findings:
            print("  ✅ 无 MISRA 违规（或均被行内 deviation 抑制）。")

    # exit non-zero if any findings, so it can act as a gate; deviations are handled by suppression.
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verify the SAD covers 100% of the SRS's software requirements.

Why: the user's hard requirement is that the architecture document be fully traceable to the SRS —
every software requirement must be realized somewhere in the architecture (a component, a sequence
diagram, a design section). This script extracts every requirement ID from the SRS and checks each one
is referenced at least once in the SAD; it prints the uncovered set, which must be empty.

It also extracts the upstream system-requirement IDs (SR-xx-xxx) for a secondary, looser check — the
SAD should still let you trace down to system requirements, but the primary contract is SRS coverage.

By default it matches `<PREFIX>_SRS_<MODULE>_<NNN>` IDs with any prefix — so it works whether the SRS
uses `HOD_SRS_O2_001`, `OXY_SRS_O2_001`, or another project prefix, as long as it's consistent.
Override with --pattern only if your SRS uses a wholly different requirement-ID convention.

Usage:
  python3 trace_check.py --srs <srs.md> --sad <sad.md>
  python3 trace_check.py --srs <srs.md> --sad <sad.md> --pattern 'OXY_SRS_[A-Z0-9]+_[0-9]+'
  python3 trace_check.py --srs <srs.md> --sad <sad.md> --json
"""
import argparse
import json
import re
import sys

REQ_DEFAULT = r"[A-Z0-9]+_SRS_[A-Z0-9]+_[0-9]+"
SYSREQ = r"SR-[0-9]{2}-[0-9]{3}"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def ids(text, pattern):
    # order-preserving unique
    seen, out = set(), []
    for m in re.findall(pattern, text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--srs", required=True, help="SRS markdown (source of requirement IDs)")
    ap.add_argument("--sad", required=True, help="SAD markdown (must reference every SRS req)")
    ap.add_argument("--pattern", default=REQ_DEFAULT, help=f"requirement-ID regex (default: {REQ_DEFAULT})")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    srs_text, sad_text = read(args.srs), read(args.sad)
    srs_reqs = ids(srs_text, args.pattern)
    sad_refs = set(ids(sad_text, args.pattern))
    uncovered = [r for r in srs_reqs if r not in sad_refs]

    # secondary: system-requirement IDs present in SRS vs carried into SAD
    srs_sys = ids(srs_text, SYSREQ)
    sad_sys = set(ids(sad_text, SYSREQ))
    sys_missing = [s for s in srs_sys if s not in sad_sys]

    total = len(srs_reqs)
    covered = total - len(uncovered)
    rate = (covered / total * 100) if total else 100.0

    result = {
        "srs_requirements": total,
        "covered": covered,
        "uncovered": uncovered,
        "coverage_rate": round(rate, 1),
        "system_req_in_srs": len(srs_sys),
        "system_req_missing_from_sad": sys_missing,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if not uncovered else 1)

    print(f"SRS 软件需求总数：{total}")
    print(f"SAD 已引用覆盖：{covered}  → 覆盖率 {rate:.1f}%")
    if uncovered:
        print(f"\n❌ 未被 SAD 覆盖的 SRS 需求（{len(uncovered)} 条，必须补到某组件/时序/章节）：")
        for r in uncovered:
            print(f"   - {r}")
    else:
        print("\n✅ 全部 SRS 软件需求都已在 SAD 中被引用，追溯 100% 覆盖。")

    if sys_missing:
        print(f"\n⚠️ 提示：{len(sys_missing)} 个上游系统需求 SR-xx-xxx 出现在 SRS 但未在 SAD 中出现"
              f"（次要检查，非硬性）：{', '.join(sys_missing)}")

    sys.exit(0 if not uncovered else 1)


if __name__ == "__main__":
    main()

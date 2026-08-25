#!/usr/bin/env python3
"""Verify traceability between the SRS, the SAD, and (optionally) the code that implements them.

Why: the hard requirement is that the architecture be fully traceable to the SRS. But "traceable"
has three directions, and checking only one of them lets real holes ship:

  forward  (--srs --sad, always on)
      Every SRS requirement must be realized somewhere in the SAD. Catches: requirements the
      architecture forgot.

  reverse  (--reverse)
      Every component the SAD defines should realize at least one requirement. Catches: components
      that exist for no stated reason, and components whose "实现需求" cell is still 【TBD】 — i.e.
      the requirement side was never written. A component nobody asked for is as much a defect as a
      requirement nobody implemented; forward-only checking reports 100% coverage either way.

  drift    (--code-root)
      Every component in the SAD should exist in the code, and every module in the code should
      appear in the SAD. Catches: the brownfield case where a SAD is written from the SRS alone and
      never reconciled against a codebase that already exists, so the document is wrong the day it
      ships.

By default requirement IDs match `<PREFIX>_SRS_<MODULE>_<NNN>` with any prefix, so it works whether
the SRS uses `HOD_SRS_O2_001`, `OXY_SRS_O2_001`, or another project convention. Override with
--pattern only if the SRS uses a wholly different scheme.

Usage:
  python3 trace_check.py --srs <srs.md> --sad <sad.md>
  python3 trace_check.py --srs <srs.md> --sad <sad.md> --reverse
  python3 trace_check.py --srs <srs.md> --sad <sad.md> --reverse --code-root <src/>
  python3 trace_check.py --srs <srs.md> --sad <sad.md> --json
"""
import argparse
import json
import os
import re
import sys

REQ_DEFAULT = r"[A-Z0-9]+_SRS_[A-Z0-9]+_[0-9]+"
SYSREQ = r"SR-[0-9]{2}-[0-9]{3}"
SRC_EXT = (".c", ".h", ".cpp", ".hpp", ".cc", ".py", ".rs", ".java")

H_COMPONENT_ID = re.compile(r"组件\s*ID|component\s*id|模块\s*ID|module\s*id", re.I)
H_IMPLEMENTS = re.compile(r"实现需求|覆盖需求|implements|requirement", re.I)
TBD = re.compile(r"TBD|待补充|待定|预留", re.I)
NONE_TOKENS = {"—", "-", "–", "无", "none", "n/a", "na", ""}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def ids(text, pattern):
    seen, out = set(), []
    for m in re.findall(pattern, text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


# ---------------------------------------------------------------- markdown table parsing
def split_row(line):
    line = line.strip().strip("|")
    cells, buf, i = [], "", 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            buf += "|"
            i += 2
            continue
        if line[i] == "|":
            cells.append(buf.strip())
            buf = ""
            i += 1
            continue
        buf += line[i]
        i += 1
    cells.append(buf.strip())
    return cells


def iter_tables(text):
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) \
                and re.match(r"^\s*\|[\s\-:|]+\|\s*$", lines[i + 1]):
            header, rows, j = split_row(lines[i]), [], i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(split_row(lines[j]))
                j += 1
            yield header, rows
            i = j
        else:
            i += 1


def col_index(header, pattern):
    for k, cell in enumerate(header):
        if pattern.search(cell):
            return k
    return None


def parse_component_table(text, req_pattern):
    """[{id, name, implements:[ids], raw_impl}] from the component-definition table."""
    for header, rows in iter_tables(text):
        ci = col_index(header, H_COMPONENT_ID)
        ii = col_index(header, H_IMPLEMENTS)
        if ci is None or ii is None:
            continue
        out = []
        for r in rows:
            if max(ci, ii) >= len(r):
                continue
            cid = re.sub(r"[`*_]", "", r[ci]).strip()
            if not cid or cid.lower() in NONE_TOKENS:
                continue
            raw = r[ii]
            out.append({"id": cid,
                        "name": r[ci + 1] if ci + 1 < len(r) else "",
                        "implements": ids(raw, req_pattern),
                        "raw_impl": raw})
        if out:
            return out
    return []


# ---------------------------------------------------------------- code drift
def module_tokens(comp):
    """Identifiers that could name this component's directory in the codebase.

    Takes backtick-quoted names from the component-name cell — that is where a SAD names its
    implementing module (e.g. `APP_O2`) — plus the component ID with any `C-` style prefix removed.
    """
    toks = set(re.findall(r"`([^`]+)`", comp["name"]))
    cid = comp["id"]
    toks.add(cid)
    if "-" in cid:
        toks.add(cid.split("-", 1)[1])
    return {t.strip().lower() for t in toks if t.strip()}


def code_modules(root, exclude=()):
    """Directory name -> relative path, for every directory that actually contains source files."""
    mods = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        rel = os.path.relpath(dirpath, root)
        # match exclusions against whole path segments — a substring test would let "OS" swallow
        # "Service/OSIF", which is exactly the kind of silent over-exclusion that hides drift.
        segs = {s.lower() for s in rel.replace("\\", "/").split("/")}
        if rel == "." or any(x.lower() in segs for x in exclude):
            continue
        if any(f.lower().endswith(SRC_EXT) for f in filenames):
            mods.setdefault(os.path.basename(dirpath).lower(), rel)
    return mods


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--srs", required=True, help="SRS markdown (source of requirement IDs)")
    ap.add_argument("--sad", required=True, help="SAD markdown (must reference every SRS req)")
    ap.add_argument("--pattern", default=REQ_DEFAULT, help=f"requirement-ID regex (default: {REQ_DEFAULT})")
    ap.add_argument("--reverse", action="store_true",
                    help="also flag SAD components that realize no requirement (orphan components)")
    ap.add_argument("--code-root", help="also compare the SAD's component list against this code tree")
    ap.add_argument("--code-exclude", default="",
                    help="逗号分隔的路径片段：从漂移比对中排除厂商/生成代码目录"
                         "（如 StaticCode,generate,third_party）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    srs_text, sad_text = read(args.srs), read(args.sad)
    srs_reqs = ids(srs_text, args.pattern)
    sad_refs = set(ids(sad_text, args.pattern))
    uncovered = [r for r in srs_reqs if r not in sad_refs]

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
    failed = bool(uncovered)

    comps = []
    if args.reverse or args.code_root:
        comps = parse_component_table(sad_text, args.pattern)
        if not comps:
            result["component_table"] = "未找到组件定义表（需表头含「组件ID」与「实现需求」两列）"

    if args.reverse and comps:
        # Three ways a component can lack requirement IDs, and they are NOT the same defect:
        #   - cell is TBD/预留      -> an acknowledged hole; warn, do not fail
        #   - cell has prose        -> an enabling component with a stated rationale
        #                              ("serves every App component"); infrastructure legitimately
        #                              implements no requirement directly. Report as info.
        #   - cell is empty / "—"   -> nobody said why this component exists. That is the real orphan.
        orphans, tbd, rationale = [], [], []
        for c in comps:
            if c["implements"]:
                continue
            raw = (c["raw_impl"] or "").strip()
            if TBD.search(raw):
                tbd.append(c["id"])
            elif raw and raw.lower() not in NONE_TOKENS:
                rationale.append(c["id"])
            else:
                orphans.append(c["id"])
        result["components"] = len(comps)
        result["components_without_requirement"] = orphans
        result["components_with_tbd_requirement"] = tbd
        result["components_with_rationale_only"] = rationale
        failed = failed or bool(orphans)

    if args.code_root and comps:
        mods = code_modules(args.code_root,
                            [s.strip() for s in args.code_exclude.split(",") if s.strip()])
        matched_dirs, doc_only = set(), []
        for c in comps:
            hit = module_tokens(c) & set(mods)
            if hit:
                matched_dirs |= hit
            else:
                doc_only.append(c["id"])
        result["code_root"] = args.code_root
        result["components_not_found_in_code"] = doc_only
        result["code_modules_not_in_sad"] = sorted(mods[m] for m in set(mods) - matched_dirs)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1 if failed else 0)

    print(f"SRS 软件需求总数：{total}")
    print(f"SAD 已引用覆盖：{covered}  → 覆盖率 {rate:.1f}%")
    if uncovered:
        print(f"\n❌ 未被 SAD 覆盖的 SRS 需求（{len(uncovered)} 条，必须补到某组件/时序/章节）：")
        for r in uncovered:
            print(f"   - {r}")
    else:
        print("\n✅ 全部 SRS 软件需求都已在 SAD 中被引用（正向追溯 100%）。")

    if args.reverse and comps:
        print(f"\n组件总数：{result['components']}")
        if result["components_without_requirement"]:
            print(f"❌ {len(result['components_without_requirement'])} 个组件没有任何实现需求"
                  f"（反向追溯断裂，需补需求或说明其存在理由）：")
            for c in result["components_without_requirement"]:
                print(f"   - {c}")
        else:
            print("✅ 没有来历不明的组件——每个组件要么实现需求，要么写明了存在理由或 TBD。")
        if result.get("components_with_rationale_only"):
            print(f"ℹ️  {len(result['components_with_rationale_only'])} 个使能型组件不直接实现需求，"
                  f"但已写明服务对象：{'、'.join(result['components_with_rationale_only'])}")
        if result["components_with_tbd_requirement"]:
            print(f"⚠️  {len(result['components_with_tbd_requirement'])} 个组件的实现需求标为 TBD/预留"
                  f"（已知缺口，需求侧待补齐）：{'、'.join(result['components_with_tbd_requirement'])}")

    if args.code_root and comps:
        print(f"\n与代码比对：{args.code_root}")
        if result["components_not_found_in_code"]:
            print(f"⚠️  文档有、代码无（{len(result['components_not_found_in_code'])}）："
                  f"{'、'.join(result['components_not_found_in_code'])}")
        if result["code_modules_not_in_sad"]:
            print(f"⚠️  代码有、文档无（{len(result['code_modules_not_in_sad'])}）："
                  f"{'、'.join(result['code_modules_not_in_sad'][:30])}")
        if not result["components_not_found_in_code"] and not result["code_modules_not_in_sad"]:
            print("✅ 文档组件与代码模块一一对应，无架构漂移。")

    if sys_missing:
        print(f"\n⚠️  提示：{len(sys_missing)} 个上游系统需求 SR-xx-xxx 出现在 SRS 但未在 SAD 中出现"
              f"（次要检查，非硬性）：{', '.join(sys_missing)}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

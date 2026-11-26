#!/usr/bin/env python3
"""std-compliance command line.

  stdc.py init       --project P [--force]        write a std_project.json skeleton
  stdc.py extract    --project P                  decrypted standard PDFs -> <ws>/extract (pack authoring only)
  stdc.py applicable --project P                  applicability list -> <ws>/results/applicable.json
  stdc.py static     --project P                  config/design rules -> <ws>/results/static.json
  stdc.py host       --project P gen|probe|stubs  Ceedling project + skeletons / syntax probe / link stubs from last log
                     (stubs --stubs-out F: per-test stub file, starts empty, for tests that link extra real modules)
  stdc.py run        --project P [--no-build]     run Ceedling, map results to checklist items
  stdc.py report     --project P                  xlsx matrix + markdown report
  stdc.py verify     --project P                  release gate (exit 1 on FAIL)
  stdc.py status     --project P                  counts per verdict / method / standard

Common option: --fixtures <checklist.json> (repeatable) adds non-pack items (evals).
"""
import argparse
import collections
import json
import shutil
import subprocess
import sys
from pathlib import Path

import core
from core import NA, NOTRUN, Project

TEMPLATE = {
    "_comment": "std-compliance project config. Paths are relative to this file.",
    "project": {"name": "", "version": "", "author": ""},
    "workspace": "std_ws",
    "packs": ["lin-can-comm"],
    "node": {
        "bus": ["LIN"],
        "lin_role": "responder",
        "uds_role": "server",
        "ldf_name": "",
        "features": ["diag", "tp", "sleep", "node-config"],
        "supported_sids": "auto"
    },
    "inputs": {"standards_dir": "", "ldf": [], "dbc": [], "arxml": [], "sad": "", "source_root": ""},
    "expected": {"_comment": "project-level values rules compare against (e.g. NAD from requirements)"},
    "applicability_overrides": {},
    "reviews": {},
    "notes": {},
    "findings": [],
    "host": {"dir": "std_ws/host", "test_dir": "", "support_dir": "", "sources": [], "include_dirs": [],
             "mocks": [], "defines": [], "compiler": "gcc"}
}


def cmd_init(a):
    p = Path(a.project)
    if p.exists() and not a.force:
        raise SystemExit(f"{p} exists (use --force)")
    core.save_json(p, TEMPLATE)
    print(f"written {p}")


def cmd_extract(a, prj):
    import extract_clauses as X
    d = prj.p(prj.get("inputs.standards_dir"))
    if not d or not d.is_dir():
        raise SystemExit("inputs.standards_dir not set or missing")
    globs = [s["file_glob"] for s in core.pack_standards(prj).values()]
    pdfs = sorted({f for g in globs for f in d.glob(g)})
    out = prj.wsp("extract")
    out.mkdir(parents=True, exist_ok=True)
    (out / ".gitignore").write_text("# extracted standard text is licensed material: never commit\n*\n", encoding="utf-8")
    done = {p.name for p in out.iterdir() if (p / "summary.json").exists()}
    for f in pdfs:
        stem = X.re.sub(r"[^\w.-]+", "_", f.stem).strip("_")
        if stem in done and not a.force:
            print(f"skip {f.name} (already extracted)")
            continue
        X.extract(f, out)


def items_of(a, prj):
    return core.load_items(prj, a.fixtures or ())


def cmd_applicable(a, prj):
    items, stds = items_of(a, prj), core.pack_standards(prj)
    rows = []
    for it in items:
        ok, why = core.applicability(it, prj, stds)
        rows.append({"id": it["id"], "standard": it.get("standard"), "clause": it.get("clause"),
                     "method": it.get("method"), "applicable": ok, "reason": why})
    core.save_json(prj.wsp("results", "applicable.json"), rows)
    c = collections.Counter((r["applicable"], r["method"]) for r in rows)
    n_app = sum(1 for r in rows if r["applicable"])
    print(f"检查项 {len(rows)}，适用 {n_app}，不适用 {len(rows) - n_app}")
    for (ok, m), n in sorted(c.items(), key=lambda kv: (not kv[0][0], str(kv[0][1]))):
        print(f"  {'适用' if ok else '不适用'} / {m}: {n}")


def cmd_static(a, prj):
    ctx = core.Ctx(prj)
    if prj.node.get("supported_sids", "auto") == "auto" and prj.get("inputs.arxml"):
        from parsers import arxml as A
        sids = A.supported_sids(ctx.arxml)
        core.save_json(prj.wsp("inputs", "supported_sids.json"), [f"0x{s:02X}" for s in sids])
        print("supported SIDs (Dcm):", ", ".join(f"0x{s:02X}" for s in sids) or "none")
    items, stds = items_of(a, prj), core.pack_standards(prj)
    rules = core.load_rules(prj, a.rules_dir or ())
    by_id = {i["id"]: i for i in items}
    out = {}
    for rid, fn in rules.items():
        if rid not in by_id:
            print(f"[warn] rule {rid} has no checklist item")
            continue
        ok, _ = core.applicability(by_id[rid], prj, stds)
        if not ok:
            continue
        try:
            out[rid] = fn(ctx)
        except Exception as exc:
            out[rid] = core.result(NOTRUN, f"规则执行异常：{type(exc).__name__}: {exc}")
    missing = [i["id"] for i in items if i.get("method") == "config" and i["id"] not in rules
               and core.applicability(i, prj, stds)[0]]
    core.save_json(prj.wsp("results", "static.json"), out)
    c = collections.Counter(r["verdict"] for r in out.values())
    print(f"静态规则 {len(out)} 条：" + "，".join(f"{k} {v}" for k, v in c.items()))
    for rid, r in out.items():
        if r["verdict"] != core.PASS:
            print(f"  [{r['verdict']}] {rid}: {r['evidence']}")
    if missing:
        print(f"[info] {len(missing)} 个适用的 config 检查项尚无规则：{', '.join(missing[:12])}{' …' if len(missing) > 12 else ''}")


def cmd_host(a, prj):
    from host import gen_project as G
    items, stds = items_of(a, prj), core.pack_standards(prj)
    if a.action == "gen":
        G.generate(prj, [i for i in items if i.get("method") == "host-test" and core.applicability(i, prj, stds)[0]])
    elif a.action == "stubs":
        from host import gen_stubs
        sys.exit(gen_stubs.generate(prj, a.stubs_out))
    else:
        sys.exit(G.probe(prj))


def cmd_run(a, prj):
    """Runs Ceedling (optionally a single test via --test) and maps results to checklist items."""
    from host import collect as C
    items, stds = items_of(a, prj), core.pack_standards(prj)
    C.run_and_collect(prj, [i for i in items if i.get("method") == "host-test" and core.applicability(i, prj, stds)[0]],
                      build=not a.no_build, test=a.test)


def cmd_report(a, prj):
    from report import build as B
    items, stds = items_of(a, prj), core.pack_standards(prj)
    rows = core.merge_verdicts(prj, items, stds)
    B.build(prj, rows, stds)


def cmd_verify(a, prj):
    import verify as V
    items, stds = items_of(a, prj), core.pack_standards(prj)
    sys.exit(V.verify(prj, items, core.merge_verdicts(prj, items, stds)))


def cmd_status(a, prj):
    items, stds = items_of(a, prj), core.pack_standards(prj)
    rows = core.merge_verdicts(prj, items, stds)
    by_v = collections.Counter(r["verdict"] for r in rows)
    by_std = collections.defaultdict(collections.Counter)
    for r in rows:
        by_std[r["item"].get("standard", "?")][r["verdict"]] += 1
    print(f"检查项 {len(rows)}：" + "，".join(f"{k} {by_v.get(k, 0)}" for k in core.VERDICTS))
    for s, c in sorted(by_std.items()):
        print(f"  {s:24s} " + "  ".join(f"{k}{c.get(k, 0)}" for k in core.VERDICTS))
    unver = [r["item"]["id"] for r in rows if not r["item"].get("source", {}).get("verified")]
    if unver:
        print(f"[warn] {len(unver)} 个检查项尚未对照原文核对")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "extract", "applicable", "static", "host", "run", "report", "verify", "status"])
    ap.add_argument("action", nargs="?", choices=["gen", "probe", "stubs"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--fixtures", action="append", help="extra checklist json (evals)")
    ap.add_argument("--rules-dir", action="append", help="extra rule directory (evals)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--test", help="run a single Ceedling test file (name without .c)")
    ap.add_argument("--stubs-out", help="host stubs: write a per-test stub file (e.g. std_autostubs_uds.c) for a test "
                                        "that links real modules the shared std_autostubs.c stubs out")
    a = ap.parse_args()
    if a.cmd == "init":
        return cmd_init(a)
    prj = Project(a.project)
    if a.cmd == "host" and not a.action:
        ap.error("host needs gen|probe|stubs")
    globals()[f"cmd_{a.cmd}"](a, prj)


if __name__ == "__main__":
    main()

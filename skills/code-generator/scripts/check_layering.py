#!/usr/bin/env python3
"""Static layering check: does every #include respect the layer rules?

Rules (see references/layering-rules.md):
  - No UPWARD include: a file must not include a header in a HIGHER layer.
  - No SKIP-LAYER include (when strict_adjacent=true): an upper layer may include only the
    immediately-lower layer (+ same layer + cross-cutting + explicitly allowed edges).
  - Same-layer includes are allowed at the include level (semantic decoupling is checked by review).
  - Cross-cutting layers (Types/Bus/Cfg...) and allow_edges are always permitted.

layers.json schema:
{
  "layers": ["App", "Service", "Hal", "Cdd", "Mcal", "Os"],   // high -> low, ordered
  "cross_cutting": ["Bus", "Types", "Cfg"],                     // accessible from any layer
  "path_map": {                                                  // path-substring -> layer (first match wins)
      "Source/App": "App", "Source/Service": "Service",
      "Source/Hal": "Hal", "Source/Cdd": "Cdd",
      "Source/Mcal": "Mcal", "Source/Os": "Os",
      "Source/Bus": "Bus", "IF_Types": "Types"
  },
  "header_map": {"IF_Gpio.h": "Hal"},   // OPTIONAL explicit header-basename -> layer overrides
  "allow_edges": [["App","Os"]],          // OPTIONAL extra permitted (from_layer, to_layer) pairs
  "strict_adjacent": true                  // forbid skipping layers downward (default true)
}

Exit code: 0 if no violations, 1 otherwise.

Usage:
  python3 check_layering.py --root <code_root> --layers <layers.json>
  python3 check_layering.py --root <code_root> --layers <layers.json> --json
"""
import argparse
import json
import os
import re
import sys

INCLUDE_RE = re.compile(r'^\s*#\s*include\s*"([^"]+)"')


def load_cfg(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("cross_cutting", [])
    cfg.setdefault("header_map", {})
    cfg.setdefault("allow_edges", [])
    cfg.setdefault("strict_adjacent", True)
    return cfg


def layer_of_path(relpath, cfg):
    """Map a file path to a layer via path_map (first substring match wins)."""
    norm = relpath.replace("\\", "/")
    for sub, layer in cfg["path_map"].items():
        if sub.replace("\\", "/") in norm:
            return layer
    return None


def layer_of_header(basename, cfg):
    """Map an included header basename to a layer. header_map first, then path_map on basename."""
    if basename in cfg["header_map"]:
        return cfg["header_map"][basename]
    for sub, layer in cfg["path_map"].items():
        s = sub.replace("\\", "/")
        # match by basename substring so "IF_Types" or "Bus" path-stems work too
        if "/" not in s and s in basename:
            return layer
    return None


def build_header_index(root):
    """basename -> relpath, for resolving #include "foo.h" to a real file/layer."""
    idx = {}
    for dirpath, _, files in os.walk(root):
        if any(seg.startswith(".") for seg in dirpath.split(os.sep)):
            continue
        for f in files:
            if f.lower().endswith(".h"):
                idx.setdefault(f, os.path.relpath(os.path.join(dirpath, f), root))
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--layers", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    cfg = load_cfg(args.layers)
    order = {name: i for i, name in enumerate(cfg["layers"])}  # smaller index = higher layer
    cross = set(cfg["cross_cutting"])
    allow = {(a, b) for a, b in cfg["allow_edges"]}
    strict = bool(cfg["strict_adjacent"])
    hdr_index = build_header_index(root)

    violations = []
    files_scanned = 0
    unmapped_files = []

    for dirpath, _, files in os.walk(root):
        if any(seg.startswith(".") for seg in dirpath.split(os.sep)):
            continue
        for f in files:
            if not f.lower().endswith((".c", ".h")):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root)
            cur_layer = layer_of_path(rel, cfg)
            if cur_layer is None:
                unmapped_files.append(rel)
                continue
            if cur_layer not in order and cur_layer not in cross:
                unmapped_files.append(rel)
                continue
            files_scanned += 1
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
            except OSError:
                continue
            for ln, line in enumerate(lines, 1):
                m = INCLUDE_RE.match(line)
                if not m:
                    continue
                inc = m.group(1)
                base = os.path.basename(inc)
                # resolve target layer: prefer real file's path, else header_map/basename
                tgt_layer = None
                if base in hdr_index:
                    tgt_layer = layer_of_path(hdr_index[base], cfg)
                if tgt_layer is None:
                    tgt_layer = layer_of_header(base, cfg)
                if tgt_layer is None:
                    continue  # unknown / SDK / system header -> skip
                if tgt_layer in cross or cur_layer in cross:
                    continue  # cross-cutting always allowed
                if (cur_layer, tgt_layer) in allow:
                    continue
                if cur_layer not in order or tgt_layer not in order:
                    continue
                ci, ti = order[cur_layer], order[tgt_layer]
                if ti < ci:
                    violations.append({
                        "file": rel, "line": ln, "include": inc,
                        "from": cur_layer, "to": tgt_layer, "kind": "UPWARD",
                        "msg": f"向上依赖：{cur_layer} → {tgt_layer}（下层在上层之上，禁止）"})
                elif strict and (ti - ci) > 1:
                    violations.append({
                        "file": rel, "line": ln, "include": inc,
                        "from": cur_layer, "to": tgt_layer, "kind": "SKIP",
                        "msg": f"跳层：{cur_layer} 跳过中间层直够 {tgt_layer}（应经相邻下层接口）"})

    result = {
        "root": root, "files_scanned": files_scanned,
        "violations": violations, "violation_count": len(violations),
        "unmapped_files": unmapped_files,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"# 跨层依赖核查 @ {root}")
        print(f"  扫描文件：{files_scanned}　违规：{len(violations)}　未归层文件：{len(unmapped_files)}\n")
        for v in violations:
            print(f"  ❌ {v['file']}:{v['line']}  #include \"{v['include']}\"  [{v['kind']}]")
            print(f"       {v['msg']}")
        if unmapped_files:
            print(f"\n  ⚠️ 未能按 path_map 归层（请补全 layers.json 的 path_map）：")
            for u in unmapped_files[:20]:
                print(f"       - {u}")
            if len(unmapped_files) > 20:
                print(f"       - ...（共 {len(unmapped_files)} 个）")
        if not violations:
            print("  ✅ 无跨层/向上依赖违规。")

    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()

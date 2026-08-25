#!/usr/bin/env python3
"""Cross-validate the layering a SAD declares in three different places, and emit a machine-readable
layer model for the downstream code generator.

Why this exists
---------------
A SAD states dependencies three times over, in three different notations:

  1. the layered-architecture diagram (7.2.1) — edges between layers;
  2. the component table (7.2.3) — a "依赖 / depends-on" column per component;
  3. the per-component sections (chapter 8) — an "外部接口(依赖) / 依赖" line per component.

Nothing forces those three to agree, and nothing forces any of them to respect the layering the
document itself declares. In practice they drift: a diagram says App must not reach the HAL while the
component table has an App component depending on a HAL component, and a chapter-8 line has a service
component depending on an application component (a reverse dependency). All three ship in one
document and no reviewer catches it, because checking means reading 40 pages and holding a graph in
your head.

This script builds that graph for you. It parses all three sources, reconciles them, and reports:
  - dependencies that violate the declared layering (reverse / skip-level / illegal peer),
  - same-layer coupling (subject to the project's same_layer_policy),
  - disagreements between the three sources,
  - components declared in one place and missing from another.

It is deliberately project-agnostic: layer names, component IDs, and the legal edge set all come from
the document (or from --layers), never from anything hardcoded here. Tables are located by their
HEADER TEXT, not by position, so column order and extra columns do not matter.

Layer model
-----------
Either pass --layers <layers.json>, or let the script derive one from the SAD's "合法结构边 / legal
edges" table and component table. `--emit-layers <path>` writes the derived model out; that file is
the handoff artifact for `code-generator` (same schema as its layers.json: layers, peer_groups,
cross_cutting, architecture_edges).

Usage:
  python3 layer_check.py --sad <sad.md>
  python3 layer_check.py --sad <sad.md> --layers <layers.json>
  python3 layer_check.py --sad <sad.md> --emit-layers <layers.json>
  python3 layer_check.py --sad <sad.md> --json
"""
import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------- header vocabulary
# Tables are found by matching these against header cells. Bilingual so the script works on
# Chinese- and English-language SADs alike; extend rather than replace if a project words it
# differently.
H_COMPONENT_ID = re.compile(r"组件\s*ID|component\s*id|模块\s*ID|module\s*id", re.I)
H_LAYER = re.compile(r"^\s*(所属)?(层|子系统|layer|subsystem)", re.I)
H_DEPENDS = re.compile(r"依赖|depend", re.I)
H_EDGE_FROM = re.compile(r"源层|上层|from|source", re.I)
H_EDGE_TO = re.compile(r"目标层|下层|to|target", re.I)

# A dependency statement inside a component write-up. Colon is optional because thin-layer entries
# are usually prose ("依赖 C-MCAL、C-LOAD。"); the run stops at 。 or end of line either way.
CH8_DEP = re.compile(
    r"(?:外部接口\s*\(?依赖\)?|依赖|depends?\s*on)(?:\*\*)?\s*[:：]?\s*([^。\n]+)",
    re.I)
# a heading that introduces a component section, e.g. "### 8.2.7 设备能力门面 C-DEV"
CH8_HEADING = re.compile(r"^#{2,4}\s*(\d+(?:\.\d+)+)\s+(.*)$", re.M)

CROSS_LAYER_WORDS = re.compile(r"横切|cross[-\s]?cut", re.I)
NONE_TOKENS = {"—", "-", "–", "无", "none", "n/a", "na", ""}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- markdown table parsing
def split_row(line):
    """Split a markdown table row into cells, honouring escaped pipes (\\|) inside cells."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, buf, i = [], "", 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            buf += "|"
            i += 2
            continue
        if c == "|":
            cells.append(buf.strip())
            buf = ""
            i += 1
            continue
        buf += c
        i += 1
    cells.append(buf.strip())
    return cells


def iter_tables(text):
    """Yield (header_cells, [row_cells, ...]) for every markdown table in the document."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) \
                and re.match(r"^\s*\|[\s\-:|]+\|\s*$", lines[i + 1]):
            header = split_row(lines[i])
            rows, j = [], i + 2
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


def clean_token(s):
    """Strip markdown emphasis/code marks and trailing parenthetical notes from a cell token."""
    s = re.sub(r"[`*_]", "", s).strip()
    s = re.sub(r"[（(].*?[)）]", "", s).strip()
    return s


def split_list(cell):
    """Split a dependency cell into tokens. Handles 、 , ， ; ； / and whitespace runs.

    Parenthetical notes are stripped BEFORE splitting — real documents write
    `C-BUS（下发控制、取用上报数据）、C-OSIF（10ms 周期）`, and splitting first would shred the
    note into bogus tokens.
    """
    cell = re.sub(r"<br\s*/?>", ",", cell, flags=re.I)
    cell = re.sub(r"[（(][^（()）]*[)）]", " ", cell)   # drop one level of parenthetical notes
    parts = re.split(r"[、,，;；/]+|\s{2,}", cell)
    out = []
    for p in parts:
        p = clean_token(p)
        if p and p.lower() not in NONE_TOKENS:
            out.append(p)
    return out


# ---------------------------------------------------------------- extraction
def parse_components(text):
    """From the component-definition table: {component_id: {"layer":…, "deps":[…], "name":…}}."""
    for header, rows in iter_tables(text):
        ci = col_index(header, H_COMPONENT_ID)
        li = col_index(header, H_LAYER)
        di = col_index(header, H_DEPENDS)
        if ci is None or li is None or di is None:
            continue
        comps = {}
        for r in rows:
            if max(ci, li, di) >= len(r):
                continue
            cid = clean_token(r[ci])
            if not cid or cid.lower() in NONE_TOKENS:
                continue
            comps[cid] = {
                "layer": clean_token(r[li]),
                "deps": split_list(r[di]),
                "name": clean_token(r[ci + 1]) if ci + 1 < len(r) else "",
            }
        if comps:
            return comps
    return {}


def parse_legal_edges(text):
    """From the legal-structural-edge table: [(from_layer, to_layer), ...]."""
    for header, rows in iter_tables(text):
        fi = col_index(header, H_EDGE_FROM)
        ti = col_index(header, H_EDGE_TO)
        if fi is None or ti is None or fi == ti:
            continue
        # guard: a component table also has a 层 column; require BOTH from and to and no 组件ID
        if col_index(header, H_COMPONENT_ID) is not None:
            continue
        edges = []
        for r in rows:
            if max(fi, ti) >= len(r):
                continue
            a, b = clean_token(r[fi]), clean_token(r[ti])
            if a and b and a.lower() not in NONE_TOKENS and b.lower() not in NONE_TOKENS:
                edges.append((a, b))
        if edges:
            return edges
    return []


def parse_plantuml_edges(text):
    """Layer-to-layer edges declared inside plantuml blocks (`A ..> B`, `A --> B`)."""
    edges = []
    for block in re.findall(r"```plantuml(.*?)```", text, re.S):
        alias = dict(re.findall(r'package\s+"[^"]*"\s+as\s+(\w+)', block) and [] or [])
        for m in re.finditer(r"^\s*(\w+)\s*(?:\.\.>|-->|->)\s*(\w+)\s*$", block, re.M):
            edges.append((alias.get(m.group(1), m.group(1)), alias.get(m.group(2), m.group(2))))
    return edges


def _deps_in(body):
    deps = []
    for m in CH8_DEP.finditer(body):
        deps.extend(split_list(m.group(1)))
    return deps


def parse_chapter8_deps(text, known_components):
    """From per-component sections: {component_id: [dep_token, ...]}.

    Two authoring styles are both accepted, because both are common and neither is wrong:
      (a) one heading per component — "### 8.2.7 设备能力门面 C-DEV" followed by bullets;
      (b) one bullet per component  — "- **C-IN**（IF_IN）：… 依赖 C-MCAL、C-LOAD。"
          which is how thin layers (HAL/CDD/BSW/MCAL) usually get written up.

    Returns (deps_map, documented) — `documented` is every component that HAS a write-up, whether or
    not that write-up states dependencies. Keeping the two apart matters: "no section at all" is a
    documentation hole, while "a section that declares no dependencies" is normal for leaf layers.
    """
    out, documented = {}, set()

    def add(cid, deps):
        documented.add(cid)
        if deps:
            out.setdefault(cid, []).extend(deps)

    # (a) heading-per-component
    headings = [(m.start(), m.group(1), m.group(2)) for m in CH8_HEADING.finditer(text)]
    for idx, (pos, _num, title) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(text)
        body = text[pos:end]
        hits = [c for c in known_components if c and c in title]
        if hits:
            add(max(hits, key=len), _deps_in(body))
            continue
        # (b) bullet-per-component, scoped to this section's body
        items = [(m.start(), m.group(1)) for m in
                 re.finditer(r"^\s*[-*]\s*\*\*\s*([^*]+?)\s*\*\*", body, re.M)]
        for k, (bpos, label) in enumerate(items):
            bend = items[k + 1][0] if k + 1 < len(items) else len(body)
            bhits = [c for c in known_components if c and c in label]
            if bhits:
                add(max(bhits, key=len), _deps_in(body[bpos:bend]))
    return out, documented


# ---------------------------------------------------------------- layer model
def build_model(text, comps, cli_layers):
    if cli_layers:
        with open(cli_layers, encoding="utf-8") as f:
            m = json.load(f)
        m.setdefault("peer_groups", [])
        m.setdefault("cross_cutting", [])
        m.setdefault("same_layer_policy", "bus")
        m.setdefault("same_layer_allow", [])
        m["architecture_edges"] = [tuple(e) for e in m.get("architecture_edges", [])]
        return m, []

    notes = []
    edges = parse_legal_edges(text)
    if not edges:
        edges = parse_plantuml_edges(text)
        if edges:
            notes.append("未找到「合法结构边」表，已退回从 plantuml 分层图推导边——"
                         "建议在 7.2.1 增设合法结构边表，图与表才有单一事实源。")
    # layer vocabulary: component table's layer column, plus anything named in the edges
    layers, cross = [], []
    for c in comps.values():
        L = c["layer"]
        if not L:
            continue
        if CROSS_LAYER_WORDS.search(L):
            if L not in cross:
                cross.append(L)
        elif L not in layers:
            layers.append(L)
    for a, b in edges:
        for L in (a, b):
            if L not in layers and L not in cross:
                layers.append(L)
    return {
        "layers": layers,
        "peer_groups": [],
        "cross_cutting": cross,
        "architecture_edges": edges,
        "same_layer_policy": "bus",
        "same_layer_allow": [],
    }, notes


def layer_of(cid, comps):
    return comps.get(cid, {}).get("layer", "")


def is_cross(layer, model):
    if not layer:
        return False
    if layer in model["cross_cutting"]:
        return True
    return bool(CROSS_LAYER_WORDS.search(layer))


def classify(src_layer, dst_layer, model, dst_component=None):
    """Return None if legal, else a short violation kind.

    `dst_component` lets a project sanction specific in-layer gateways (an OS-adapter, a logger, a
    bus adapter) via `same_layer_allow` — depending on those from inside their own layer is the
    intended design, not coupling to be reported.
    """
    if not src_layer or not dst_layer:
        return None
    if is_cross(dst_layer, model):
        return None
    if is_cross(src_layer, model):
        return "横切层反向依赖纵向层"
    if src_layer == dst_layer:
        if dst_component and dst_component in set(model.get("same_layer_allow", [])):
            return None
        policy = model.get("same_layer_policy", "bus")
        return None if policy == "allow" else "同层耦合"
    if (src_layer, dst_layer) in set(model["architecture_edges"]):
        return None
    order = model["layers"]
    if src_layer in order and dst_layer in order:
        if order.index(dst_layer) < order.index(src_layer):
            return "反向依赖"
        return "越层/未声明的结构边"
    return "未知层"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sad", required=True, help="SAD markdown")
    ap.add_argument("--layers", help="layer model JSON; derived from the SAD when omitted")
    ap.add_argument("--emit-layers", help="write the layer model here (handoff to code-generator)")
    ap.add_argument("--same-layer-allow", default="",
                    help="逗号分隔的组件ID：允许被同层其它组件依赖的层内网关/门面"
                         "（也可写进 layers.json 的 same_layer_allow）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    # Console encodings vary (GBK on many Chinese Windows shells); never let a status glyph crash a check.
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    text = read(args.sad)
    comps = parse_components(text)
    if not comps:
        print("❌ 未找到组件定义表。需要一张表头同时含「组件ID」「层」「依赖」三列（中英皆可）。")
        sys.exit(2)

    model, notes = build_model(text, comps, args.layers)
    if args.same_layer_allow:
        model["same_layer_allow"] = sorted(set(model.get("same_layer_allow", [])) |
                                           {s.strip() for s in args.same_layer_allow.split(",") if s.strip()})
    ch8, documented = parse_chapter8_deps(text, set(comps))

    violations, unknown, mismatch = [], [], []

    # (1) component-table dependencies vs the declared layering
    for cid, c in comps.items():
        for d in c["deps"]:
            if d not in comps:
                unknown.append((cid, d))
                continue
            kind = classify(c["layer"], layer_of(d, comps), model, d)
            if kind:
                violations.append({"source": "7.2.3 组件表", "component": cid, "from_layer": c["layer"],
                                   "depends_on": d, "to_layer": layer_of(d, comps), "kind": kind})

    # (2) chapter-8 dependency lines vs the declared layering
    for cid, deps in ch8.items():
        for d in deps:
            if d not in comps:
                continue  # prose often names non-components ("NVM", "总线活动"); not an error here
            kind = classify(layer_of(cid, comps), layer_of(d, comps), model, d)
            if kind:
                violations.append({"source": "第 8 章", "component": cid, "from_layer": layer_of(cid, comps),
                                   "depends_on": d, "to_layer": layer_of(d, comps), "kind": kind})

    # (3) do the two prose sources agree with each other?
    for cid in sorted(set(comps) & set(ch8)):
        table_set = {d for d in comps[cid]["deps"] if d in comps}
        ch8_set = {d for d in ch8[cid] if d in comps}
        only_table, only_ch8 = sorted(table_set - ch8_set), sorted(ch8_set - table_set)
        if only_table or only_ch8:
            mismatch.append({"component": cid, "only_in_table": only_table, "only_in_chapter8": only_ch8})

    # (4) components with no chapter-8 section at all
    no_section = sorted(c for c in comps if c not in documented)

    # (5) do the two sources use the SAME NAMES for layers? A layer that appears only in the edge
    # table or only in the component table is almost always one layer written two ways (SVC vs
    # Service), which silently defeats every edge lookup above.
    edge_layers = {L for e in model["architecture_edges"] for L in e}
    comp_layers = {c["layer"] for c in comps.values() if c["layer"] and not is_cross(c["layer"], model)}
    layer_naming = {
        "only_in_edge_table": sorted(edge_layers - comp_layers),
        "only_in_component_table": sorted(comp_layers - edge_layers),
    }

    result = {
        "components": len(comps),
        "layers": model["layers"],
        "cross_cutting": model["cross_cutting"],
        "architecture_edges": [list(e) for e in model["architecture_edges"]],
        "violations": violations,
        "unknown_dependency_targets": [{"component": a, "token": b} for a, b in unknown],
        "table_vs_chapter8_mismatch": mismatch,
        "components_without_chapter8_section": no_section,
        "layer_naming_mismatch": layer_naming,
        "notes": notes,
    }
    naming_broken = bool(layer_naming["only_in_edge_table"] or layer_naming["only_in_component_table"])

    if args.emit_layers:
        out = {k: result[k] for k in ("layers", "cross_cutting", "architecture_edges")}
        out["peer_groups"] = model["peer_groups"]
        out["same_layer_policy"] = model.get("same_layer_policy", "bus")
        out["same_layer_allow"] = model.get("same_layer_allow", [])
        out["_source"] = os.path.basename(args.sad)
        with open(args.emit_layers, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1 if violations or mismatch or naming_broken else 0)

    print(f"组件数：{len(comps)}    层：{' > '.join(model['layers']) or '（未识别）'}")
    if model["cross_cutting"]:
        print(f"横切层：{'、'.join(model['cross_cutting'])}")
    print(f"合法结构边：{len(model['architecture_edges'])} 条")
    for n in notes:
        print(f"\n⚠️  {n}")

    if naming_broken:
        print("\n❌ 层名在两处写法不一致——结构边查表会因此全部落空，必须先统一：")
        if layer_naming["only_in_edge_table"]:
            print(f"   仅出现在结构边表：{'、'.join(layer_naming['only_in_edge_table'])}")
        if layer_naming["only_in_component_table"]:
            print(f"   仅出现在组件表：{'、'.join(layer_naming['only_in_component_table'])}")

    if violations:
        print(f"\n❌ 违反已声明分层的依赖（{len(violations)} 处）：")
        for v in violations:
            print(f"   [{v['kind']}] {v['component']}({v['from_layer']}) → "
                  f"{v['depends_on']}({v['to_layer']})    来源：{v['source']}")
    else:
        print("\n✅ 组件表与第 8 章的依赖全部落在已声明的合法结构边上。")

    if mismatch:
        print(f"\n❌ 组件表与第 8 章依赖不一致（{len(mismatch)} 个组件）：")
        for m in mismatch:
            bits = []
            if m["only_in_table"]:
                bits.append(f"仅表中有 {'、'.join(m['only_in_table'])}")
            if m["only_in_chapter8"]:
                bits.append(f"仅第 8 章有 {'、'.join(m['only_in_chapter8'])}")
            print(f"   {m['component']}：{'；'.join(bits)}")

    if unknown:
        print(f"\n⚠️  依赖列里 {len(unknown)} 个 token 不是已定义的组件ID（可能是笔误或漏建组件）：")
        for a, b in unknown[:20]:
            print(f"   {a} → {b}")

    if no_section:
        print(f"\n⚠️  {len(no_section)} 个组件在第 8 章没有对应小节：{'、'.join(no_section)}")

    if args.emit_layers:
        print(f"\n已写出层模型：{args.emit_layers}（可直接交给 code-generator 作 layers.json 起点）")

    sys.exit(1 if violations or mismatch or naming_broken else 0)


if __name__ == "__main__":
    main()

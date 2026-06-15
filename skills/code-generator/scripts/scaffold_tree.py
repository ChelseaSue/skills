#!/usr/bin/env python3
"""Generate a layered directory tree + per-module C skeletons from a module_spec + layers config.

Produces, for each module: <Module>.h (public API + contracts + @implements traceability + include
guard), <Module>_Cfg.h (compile-time config placeholders), <Module>.c (only lower/same/cross-cutting
includes + function stubs with /* TBD */ bodies). MISRA-friendly by construction.

Placement:
  - module.dir given            -> use it verbatim (relative to --out)
  - else                        -> <layer base dir>/<Module>   (base = first path_map key for the layer)
  - module.flat == true         -> files go directly in the base dir (no per-module subdir)
  - module.hal_split == true    -> header+cfg in <base>/If, .c in <base>/Impl

See assets/module_spec.schema.json and assets/module_spec.example.json.

Usage:
  python3 scaffold_tree.py --spec module_spec.json --layers layers.json --out <code_root>
  python3 scaffold_tree.py --spec module_spec.json --layers layers.json --out <code_root> --dry-run
"""
import argparse
import json
import os
import sys
from datetime import date


def base_dir_for_layer(layer, layers_cfg):
    for sub, lyr in layers_cfg.get("path_map", {}).items():
        if lyr == layer and "/" in sub.replace("\\", "/"):
            return sub.replace("\\", "/")
    return layer  # fallback: a dir named after the layer


def guard(name):
    return "".join(c if c.isalnum() else "_" for c in name).upper().strip("_") + "_H_"


_DEFAULT_REUSE = {"App": "project-specific"}


def reuse_of(m):
    """模块的复用分类：显式 reuse 字段优先，否则按层默认（App→project-specific，其它→reusable）。"""
    return m.get("reuse") or _DEFAULT_REUSE.get(m["layer"], "reusable")


def contract_text(m):
    mod = m["name"]
    g = guard(mod + "_contract")
    lines = ["/*!", f"** @file    {mod}_contract.h",
             f"** @brief   {mod} 自包含横切契约：本模块用到的信号/事件 ID、Cfg 默认、返回码扩展集中于此，",
             "**          整个模块文件夹可整体移植。只依赖稳定横切（IF_Types 返回码、Bus 注册 API），",
             "**          不直接引用其它项目专属的全局 ID。",
             "*/", f"#ifndef {g}", f"#define {g}", "", '#include "IF_Types.h"', "",
             "/* TBD: 本模块自有的信号/事件 ID 枚举、Cfg 默认值、返回码扩展。移植时只动这里与 Impl/Cfg。 */", "",
             f"#endif /* {g} */"]
    return "\n".join(lines) + "\n"


def port_md_text(m):
    mod = m["name"]
    impls = ", ".join(m.get("implements", [])) or "（待补充需求 ID）"
    return f"""# {mod} 移植清单（参考说明，自动生成）

## 1. 模块身份
- 层：{m['layer']}　复用类型：{reuse_of(m)}　对应 SRS 需求 ID（旧项目）：{impls}

## 2. 依赖
- 自带：{mod}_contract.h、{mod}.h/.c、本模块单测
- 需新项目提供：稳定 IF_Types 返回码、Bus 注册 API（若用）

## 3. 需重新适配的接驳点（移植时逐条改）
- [ ] Impl/ → 绑定新项目 MCAL/SDK（仅 HAL 模块）
- [ ] {mod}_Cfg.h → 新项目板级/通道/参数
- [ ] 信号/事件 ID → 在新项目登记 {mod}_contract.h 里的 ID
- [ ] 文件名/符号前缀 → 若新项目 file_prefix 不同则改

## 4. 追溯重映射
- 旧 SRS ID（{impls}）→ 新项目 SRS ID：TBD（移植时回填）

## 5. 主机单测
- 如何脱离硬件跑本模块单测（打桩点说明）：TBD
"""


def header_text(m, today):
    mod = m["name"]
    g = guard(mod)
    impls = ", ".join(m.get("implements", [])) or "（待补充需求 ID）"
    deps = m.get("deps", [])
    lines = []
    lines.append("/*!")
    lines.append(f"** @file    {mod}.h")
    lines.append(f"** @brief   {m.get('brief','<职责>')}。所属层：{m['layer']}。")
    lines.append(f"** @implements {impls}")
    lines.append("** @version V0.1")
    lines.append(f"** @date    {today}")
    lines.append("*/")
    lines.append(f"#ifndef {g}")
    lines.append(f"#define {g}")
    lines.append("")
    lines.append('#include "IF_Types.h"')
    lines.append(f'#include "{mod}_Cfg.h"')
    for d in deps:
        lines.append(f'#include "{d}"')
    lines.append("")
    lines.append("#ifdef __cplusplus")
    lines.append('extern "C" {')
    lines.append("#endif")
    lines.append("")
    api = m.get("api") or [
        {"proto": f"void {mod}_Init(void)", "brief": "初始化模块", "contract": "@thread_safe @isr_unsafe"},
        {"proto": f"void {mod}_Tick(void)", "brief": "周期任务", "contract": "@thread_safe @isr_unsafe"},
    ]
    for fn in api:
        c = fn.get("contract", "")
        fi = ", ".join(fn.get("implements", []))
        doc = f"/** @brief {fn.get('brief','')}. {c}"
        if fi:
            doc += f"\n *  @implements {fi}"
        doc += " */"
        lines.append(doc)
        proto = fn["proto"].rstrip(";")
        lines.append(proto + ";")
        lines.append("")
    lines.append("#ifdef __cplusplus")
    lines.append("}")
    lines.append("#endif")
    lines.append("")
    lines.append(f"#endif /* {g} */")
    return "\n".join(lines) + "\n"


def cfg_text(m, today):
    mod = m["name"]
    g = guard(mod + "_Cfg")
    lines = ["/*!", f"** @file    {mod}_Cfg.h",
             f"** @brief   {mod} 编译期配置（值来自 SRS/SAD/HSI；缺则 TBD）。",
             "*/", f"#ifndef {g}", f"#define {g}", "", '#include "IF_Types.h"', ""]
    cfg = m.get("cfg") or [{"name": f"{mod.upper()}_TICK_PERIOD_MS", "value": "10u", "comment": "TBD: 确认调度周期"}]
    for c in cfg:
        lines.append(f"#define {c['name']:<28} ({c['value']})   /* {c.get('comment','')} */")
    lines += ["", f"#endif /* {g} */"]
    return "\n".join(lines) + "\n"


def c_text(m, today):
    mod = m["name"]
    deps = m.get("deps", [])
    lines = ["/*!", f"** @file    {mod}.c", f"** @brief   {m.get('brief','<职责>')} 实现。所属层：{m['layer']}。",
             "*/", f'#include "{mod}.h"']
    for d in deps:
        lines.append(f'#include "{d}"')
    lines += ["", "/* 文件内私有状态：static、无动态内存。 */", "", ]
    api = m.get("api") or [
        {"proto": f"void {mod}_Init(void)"}, {"proto": f"void {mod}_Tick(void)"}]
    for fn in api:
        proto = fn["proto"].rstrip(";")
        ret = proto.split()[0]
        lines.append(proto)
        lines.append("{")
        if ret not in ("void",):
            lines.append(f"    {ret} status = (IF_Status_t)IF_OK;" if ret == "IF_Status_t" else f"    {ret} ret = 0;")
            lines.append("    /* TBD: 实现逻辑——对齐 SAD 状态机/时序；入参校验；单一退出。 */")
            lines.append("    return status;" if ret == "IF_Status_t" else "    return ret;")
        else:
            lines.append("    /* TBD: 对齐 SAD；同层走总线/公开接口，硬件经相邻下层或 architecture_edges 接口。 */")
        lines.append("}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--layers", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    with open(args.layers, encoding="utf-8") as f:
        layers_cfg = json.load(f)
    out = os.path.abspath(args.out)
    today = date.today().isoformat()

    # optional per-layer filename prefix, e.g. {"Hal":"IF_","App":"App_","Service":"Svc_"}.
    # applied to the module's file stem (and thus folder + include guard + default symbols) unless the
    # name already carries it. Keeps "filenames add a layer prefix" automatic & consistent.
    file_prefix = layers_cfg.get("file_prefix", {})

    planned = []
    for m in spec.get("modules", []):
        m = dict(m)  # don't mutate caller's spec
        pfx = file_prefix.get(m["layer"], "")
        if pfx and not m["name"].startswith(pfx):
            m["name"] = pfx + m["name"]
        mod = m["name"]
        if m.get("dir"):
            base = m["dir"].replace("\\", "/")
            hdr_dir = c_dir = base if m.get("flat") else os.path.join(base, mod)
        else:
            base = base_dir_for_layer(m["layer"], layers_cfg)
            hdr_dir = c_dir = base if m.get("flat") else os.path.join(base, mod)
        if m.get("hal_split"):
            hdr_dir = os.path.join(base, "If")
            c_dir = os.path.join(base, "Impl")
        files = {
            os.path.join(out, hdr_dir, f"{mod}.h"): header_text(m, today),
            os.path.join(out, hdr_dir, f"{mod}_Cfg.h"): cfg_text(m, today),
            os.path.join(out, c_dir, f"{mod}.c"): c_text(m, today),
        }
        if reuse_of(m) == "reusable":
            files[os.path.join(out, hdr_dir, f"{mod}_contract.h")] = contract_text(m)
            files[os.path.join(out, hdr_dir, f"{mod}_port.md")] = port_md_text(m)
        planned.append((mod, files))

    for mod, files in planned:
        for path, content in files.items():
            rel = os.path.relpath(path, out)
            if args.dry_run:
                print(f"[dry-run] {rel}  ({len(content)} bytes)")
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            print(f"written  {rel}")

    n = sum(len(f) for _, f in planned)
    print(f"\n{'(dry-run) ' if args.dry_run else ''}模块 {len(planned)} 个，文件 {n} 个 → {out}")
    if not args.dry_run:
        print("下一步：补全头文件契约细节，跑 check_layering.py + run_misra.py，再逐模块填实现。")


if __name__ == "__main__":
    main()

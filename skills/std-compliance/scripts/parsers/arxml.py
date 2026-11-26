#!/usr/bin/env python3
"""AUTOSAR ECUC (EcucValues) extractor → flat container list, plus query helpers.

Every ECUC-CONTAINER-VALUE becomes one record:
  {"module": "Dcm", "path": "Dcm/DcmConfigSet/DcmDsd/...", "name": <SHORT-NAME>, "def": <container def name>,
   "params": {<param def name>: value | [values]}, "refs": {<ref def name>: [target paths]}}

Parameter and container names are the LAST segment of DEFINITION-REF, so vendor-specific definition
roots (/AUTOSAR/EcucDefs/..., /EAS/...) do not matter. Values keep their textual form; use num().

Usage: python3 arxml.py <file.arxml|dir> [--module Dcm] [--def DcmDsdService] [--json]
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _ln(tag):
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _ln(c.tag) == name:
            return c
    return None


def _children(el, name):
    return [c for c in el if _ln(c.tag) == name]


def _text(el, name):
    c = _child(el, name)
    return c.text.strip() if c is not None and c.text else None


def _last(ref):
    return ref.rstrip("/").rsplit("/", 1)[-1] if ref else None


def _walk_container(el, module, parent, out):
    name = _text(el, "SHORT-NAME")
    path = f"{parent}/{name}"
    rec = {"module": module, "path": path, "name": name, "def": _last(_text(el, "DEFINITION-REF")),
           "params": {}, "refs": {}}
    pv = _child(el, "PARAMETER-VALUES")
    if pv is not None:
        for p in pv:
            k = _last(_text(p, "DEFINITION-REF"))
            v = _text(p, "VALUE")
            if k is None:
                continue
            if k in rec["params"]:
                old = rec["params"][k]
                rec["params"][k] = (old if isinstance(old, list) else [old]) + [v]
            else:
                rec["params"][k] = v
    rv = _child(el, "REFERENCE-VALUES")
    if rv is not None:
        for r in rv:
            k = _last(_text(r, "DEFINITION-REF"))
            t = _text(r, "VALUE-REF")
            if k:
                rec["refs"].setdefault(k, []).append(t)
    out.append(rec)
    sub = _child(el, "SUB-CONTAINERS")
    if sub is not None:
        for c in _children(sub, "ECUC-CONTAINER-VALUE"):
            _walk_container(c, module, path, out)


def parse_file(path):
    out = []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        print(f"[warn] {path}: {exc}", file=sys.stderr)
        return out
    for mod in root.iter():
        if _ln(mod.tag) != "ECUC-MODULE-CONFIGURATION-VALUES":
            continue
        module = _last(_text(mod, "DEFINITION-REF")) or _text(mod, "SHORT-NAME")
        cont = _child(mod, "CONTAINERS")
        if cont is None:
            continue
        for c in _children(cont, "ECUC-CONTAINER-VALUE"):
            _walk_container(c, module, module, out)
    return out


def load(paths):
    recs = []
    for p in paths:
        p = Path(p)
        files = sorted(p.rglob("*.arxml")) if p.is_dir() else [p]
        for f in files:
            recs.extend(parse_file(f))
    return recs


def num(v, default=None):
    if v is None:
        return default
    if isinstance(v, list):
        v = v[0]
    s = str(v).strip()
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        return int(s, 0)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return default if default is not None else s


def find(recs, module=None, defname=None, param=None):
    """Records filtered by module / container def; with param → [(record, value)]."""
    res = [r for r in recs if (module is None or r["module"] == module) and (defname is None or r["def"] == defname)]
    if param is None:
        return res
    return [(r, r["params"][param]) for r in res if param in r["params"]]


def param_values(recs, param, module=None):
    """All values of a parameter (by definition name) across containers."""
    vals = []
    for r in recs:
        if module is not None and r["module"] != module:
            continue
        for k, v in r["params"].items():          # tolerate unit suffixes such as "Timeout(ms)"
            if k == param or k.split("(")[0].strip() == param:
                vals.extend(v if isinstance(v, list) else [v])
    return vals


def supported_sids(recs):
    """UDS service IDs configured in the Dcm service table(s) (DcmDsdSidTabServiceId)."""
    sids = set()
    for v in param_values(recs, "DcmDsdSidTabServiceId", module="Dcm"):
        n = num(v)
        if isinstance(n, int):
            sids.add(n)
    return sorted(sids)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(zip(sys.argv[1::1], sys.argv[2::1]))
    recs = load(args[:1])
    mod, d = opts.get("--module"), opts.get("--def")
    sel = find(recs, mod, d)
    if "--json" in sys.argv:
        print(json.dumps(sel, ensure_ascii=False, indent=1))
    else:
        mods = sorted({r["module"] for r in recs})
        print(f"containers={len(recs)} modules={mods}")
        print("supported SIDs:", [f"0x{s:02X}" for s in supported_sids(recs)])
        for r in sel[:40]:
            print(f"  {r['def']:32s} {r['path']}  {json.dumps(r['params'], ensure_ascii=False)[:160]}")

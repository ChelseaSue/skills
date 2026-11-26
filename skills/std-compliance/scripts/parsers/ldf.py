#!/usr/bin/env python3
"""Tolerant LIN Description File (LDF) parser → plain dict.

Covers the sections a protocol-compliance check needs: header (protocol/language version, speed),
Nodes (commander time base/jitter, responders), Signals, Frames (id, publisher, length, signals),
Sporadic/Event-triggered frames, Diagnostic frames, Node_attributes (NAD, product id, P2_min, ST_min,
N_As/N_Cr timeouts, response_error, configurable frames) and Schedule_tables.

The LDF grammar uses nested braces and `;`-terminated statements; we tokenise by braces rather than
by line so formatting differences between tools do not matter. Unknown sections are kept raw.

Usage: python3 ldf.py <file.ldf> [--json]
"""
import json
import re
import sys


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _blocks(text):
    """Yield (name, body) for top-level `Name { ... }` blocks, brace-balanced."""
    i, n = 0, len(text)
    while i < n:
        m = re.compile(r"([A-Za-z_][\w]*)\s*\{").search(text, i)
        if not m:
            return
        depth, j = 1, m.end()
        while j < n and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        yield m.group(1), text[m.end():j - 1]
        i = j


def _num(s):
    s = s.strip()
    try:
        return int(s, 0)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def _ms(s):
    m = re.match(r"\s*([\d.]+)\s*ms", s)
    return float(m.group(1)) if m else None


def parse(text):
    text = _strip_comments(text)
    ldf = {"header": {}, "nodes": {}, "signals": {}, "frames": {}, "diagnostic_frames": {},
           "event_triggered_frames": {}, "sporadic_frames": {}, "node_attributes": {}, "schedule_tables": {}}
    for key, rx in [("protocol_version", r'LIN_protocol_version\s*=\s*"([^"]+)"'),
                    ("language_version", r'LIN_language_version\s*=\s*"([^"]+)"'),
                    ("speed_kbps", r"LIN_speed\s*=\s*([\d.]+)\s*kbps"), ("channel", r'Channel_name\s*=\s*"([^"]+)"')]:
        m = re.search(rx, text)
        if m:
            ldf["header"][key] = _num(m.group(1)) if key == "speed_kbps" else m.group(1)

    for name, body in _blocks(text):
        if name == "Nodes":
            m = re.search(r"Master\s*:\s*(\w+)\s*,\s*([\d.]+)\s*ms\s*,\s*([\d.]+)\s*ms", body)
            if m:
                ldf["nodes"]["commander"] = {"name": m.group(1), "time_base_ms": float(m.group(2)), "jitter_ms": float(m.group(3))}
            m = re.search(r"Slaves\s*:\s*([^;]+);", body)
            if m:
                ldf["nodes"]["responders"] = [s.strip() for s in m.group(1).split(",") if s.strip()]
        elif name == "Signals":
            for m in re.finditer(r"(\w+)\s*:\s*(\d+)\s*,\s*([^,]+|\{[^}]*\})\s*,\s*(\w+)\s*((?:,\s*\w+\s*)*);", body):
                ldf["signals"][m.group(1)] = {"size": int(m.group(2)), "init": m.group(3).strip(),
                                              "publisher": m.group(4),
                                              "subscribers": [s.strip() for s in m.group(5).split(",") if s.strip()]}
        elif name in ("Frames", "Diagnostic_frames"):
            tgt = ldf["frames"] if name == "Frames" else ldf["diagnostic_frames"]
            for m in re.finditer(r"(\w+)\s*:\s*(0x[0-9A-Fa-f]+|\d+)\s*(?:,\s*(\w+)\s*,\s*(\d+))?\s*\{([^}]*)\}", body):
                sigs = [{"name": s.group(1), "offset": int(s.group(2))}
                        for s in re.finditer(r"(\w+)\s*,\s*(\d+)\s*;", m.group(5))]
                tgt[m.group(1)] = {"id": int(m.group(2), 0), "publisher": m.group(3),
                                   "length": int(m.group(4)) if m.group(4) else 8, "signals": sigs}
        elif name == "Event_triggered_frames":
            for m in re.finditer(r"(\w+)\s*:\s*(?:(\w+)\s*,\s*)?(0x[0-9A-Fa-f]+|\d+)\s*((?:,\s*\w+\s*)*);", body):
                ldf["event_triggered_frames"][m.group(1)] = {"collision_table": m.group(2), "id": int(m.group(3), 0),
                                                             "frames": [f.strip() for f in m.group(4).split(",") if f.strip()]}
        elif name == "Sporadic_frames":
            for m in re.finditer(r"(\w+)\s*:\s*([^;]+);", body):
                ldf["sporadic_frames"][m.group(1)] = [f.strip() for f in m.group(2).split(",")]
        elif name == "Node_attributes":
            for node, nbody in _blocks(body):
                attrs = {}
                for m in re.finditer(r"(\w+)\s*=\s*([^;{]+);", nbody):
                    k, v = m.group(1), m.group(2).strip()
                    if k in ("configured_NAD", "initial_NAD"):
                        attrs[k] = _num(v)
                    elif k == "product_id":
                        attrs[k] = [_num(x) for x in v.split(",")]
                    elif k in ("P2_min", "ST_min", "N_As_timeout", "N_Cr_timeout"):
                        attrs[k] = _ms(v)
                    else:
                        attrs[k] = v.strip('"')
                cf = re.search(r"configurable_frames\s*\{([^}]*)\}", nbody)
                if cf:
                    attrs["configurable_frames"] = [x.split("=")[0].strip() for x in cf.group(1).split(";") if x.strip()]
                ldf["node_attributes"][node] = attrs
        elif name == "Schedule_tables":
            for tname, tbody in _blocks(body):
                ldf["schedule_tables"][tname] = [{"entry": m.group(1).strip(), "delay_ms": float(m.group(2))}
                                                 for m in re.finditer(r"([^;{}]+?)\s+delay\s+([\d.]+)\s*ms\s*;", tbody)]
    return ldf


def pid(frame_id):
    """Protected identifier: id (6 bit) + P0 = ID0^ID1^ID2^ID4, P1 = !(ID1^ID3^ID4^ID5)."""
    b = [(frame_id >> i) & 1 for i in range(6)]
    p0 = b[0] ^ b[1] ^ b[2] ^ b[4]
    p1 = 1 - (b[1] ^ b[3] ^ b[4] ^ b[5])
    return (frame_id & 0x3F) | (p0 << 6) | (p1 << 7)


def load(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return parse(f.read())


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    d = load(sys.argv[1])
    if "--json" in sys.argv:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    else:
        print("header:", d["header"])
        print("nodes:", d["nodes"])
        for n, f in {**d["frames"], **d["diagnostic_frames"]}.items():
            print(f"  frame {n:16s} id=0x{f['id']:02X} pid=0x{pid(f['id']):02X} len={f['length']} pub={f['publisher']} sigs={len(f['signals'])}")
        print("node_attributes:", json.dumps(d["node_attributes"], ensure_ascii=False))
        print("schedule_tables:", {k: len(v) for k, v in d["schedule_tables"].items()})

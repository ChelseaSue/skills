#!/usr/bin/env python3
"""Parse a CAN matrix .xlsx into a per-message / per-signal lookup, so the SAD's sequence diagrams can
cite REAL signals (name + message ID + send/receive direction) instead of vague prose.

Why this matters: the user's hard requirement is that each functional sequence diagram marks the
actual CAN signals it uses. The SRS already transcribed these into prose tables, but parsing the
matrix directly is more reliable and—crucially—recovers the per-node send/receive direction (the
`*_Node` columns hold 'S'/'R'), which tells you which way each arrow points in a sequence diagram.

Layout assumed (standard NIO-style matrix, one header row, columns by Chinese header keyword, robust
to column reordering): a message row carries 报文名称/标识符/周期/长度 and the node S·R columns; the
signal rows beneath it (blank message cells) carry 信号名称/描述/起始字节/起始位/长度/精度/偏移/范围/单位.
Each node column header (anything not in the known column set, e.g. OXY_Node / AC_Node) is treated as a
network node whose cell value 'S'/'R' gives that node's role for the message.

Usage:
  python3 parse_can_matrix.py <matrix.xlsx>            # human-readable markdown + JSON
  python3 parse_can_matrix.py <matrix.xlsx> --json     # JSON only
  python3 parse_can_matrix.py <matrix.xlsx> --signal OXY_Status_Concentration   # look up one signal
"""
import argparse
import json
import re
import sys

import openpyxl


# header keyword -> canonical field. Matched by substring against the (newline-stripped) header text.
COLMAP = [
    ("报文名称", "msg_name"), ("Msg_Name", "msg_name"),
    ("报文类型", "msg_type"),
    ("报文标识符", "msg_id"), ("Msg_ID", "msg_id"),
    ("报文发送类型", "msg_send_type"),
    ("报文周期", "msg_cycle"),
    ("报文长度", "msg_dlc"),
    ("信号名称", "sig_name"), ("Signal_Na", "sig_name"),
    ("信号描述", "sig_desc"),
    ("排列格式", "byte_order"),
    ("起始字节", "start_byte"),
    ("起始位", "start_bit"),
    ("信号长度", "bit_length"), ("Bit_Lengt", "bit_length"),
    ("精度", "factor"),
    ("偏移量", "offset"),
    ("物理最小值", "phys_min"),
    ("物理最大值", "phys_max"),
    ("单位", "unit"),
    ("数据类型", "data_type"),
    ("初始值", "initial"),
    ("备注", "comments"),
]
KNOWN_FIELDS = {f for _, f in COLMAP}


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip() if s is not None else ""


def header_to_field(h):
    h = norm(h)
    for kw, field in COLMAP:
        if kw.lower() in h.lower():
            return field
    return None


def load(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    header = [norm(c) for c in rows[0]]
    # map column index -> canonical field. A "node" column is a network ECU column whose cells hold
    # 'S'/'R' (e.g. OXY_Node / AC_Node). Detect those specifically (header ends in Node / 节点) rather
    # than treating every unmapped column as a node — otherwise matrix-metadata columns such as
    # 报文延时时间/信号值描述/总线最小值 would be mistaken for nodes.
    col_field = {}
    node_cols = {}
    for idx, h in enumerate(header):
        if not h:
            continue
        f = header_to_field(h)
        if f:
            col_field[idx] = f
        elif re.search(r"node$", h, re.I) or "节点" in h:
            node_cols[idx] = re.sub(r"[_\s]*Node$", "", h, flags=re.I) or h
    return rows, (col_field, node_cols)


def parse(path):
    rows, (col_field, node_cols) = load(path)
    all_nodes = list(node_cols.values())
    messages = []
    cur = None
    for r in rows[1:]:
        rec = {col_field[i]: norm(r[i]) for i in col_field if i < len(r)}
        nodes = {node_cols[i]: norm(r[i]) for i in node_cols if i < len(r) and norm(r[i])}
        msg_id = rec.get("msg_id", "")
        msg_name = rec.get("msg_name", "")
        # a row that names a message starts a new message block
        if msg_id or msg_name:
            cur = {
                "msg_name": msg_name,
                "msg_id": msg_id,
                "msg_cycle": rec.get("msg_cycle", ""),
                "msg_dlc": rec.get("msg_dlc", ""),
                "msg_send_type": rec.get("msg_send_type", ""),
                "nodes": nodes,            # node -> 'S'/'R' for this message (senders explicit)
                "all_nodes": all_nodes,    # every node column on the bus (to infer implicit receivers)
                "signals": [],
            }
            messages.append(cur)
        if rec.get("sig_name"):
            cur = cur or {"msg_name": "", "msg_id": "", "msg_cycle": "", "msg_dlc": "",
                          "msg_send_type": "", "nodes": {}, "signals": []}
            if cur not in messages:
                messages.append(cur)
            cur["signals"].append({
                "name": rec.get("sig_name", ""),
                "desc": rec.get("sig_desc", ""),
                "start_byte": rec.get("start_byte", ""),
                "start_bit": rec.get("start_bit", ""),
                "bit_length": rec.get("bit_length", ""),
                "factor": rec.get("factor", ""),
                "offset": rec.get("offset", ""),
                "phys_min": rec.get("phys_min", ""),
                "phys_max": rec.get("phys_max", ""),
                "unit": rec.get("unit", ""),
            })
    return messages


def fmt_dir(nodes, all_nodes=None):
    """Render a compact direction hint 'AC → OXY' (sender → receiver). Matrices commonly mark only the
    sender with 'S'; receivers are left blank. With the full node list we infer receivers = all nodes
    that aren't senders, which on a 2-node bus (OXY ↔ AC) recovers the real direction."""
    if not nodes:
        return ""
    senders = [n for n, v in nodes.items() if v.upper().startswith("S")]
    receivers = [n for n, v in nodes.items() if v.upper().startswith("R")]
    if not receivers and all_nodes:
        receivers = [n for n in all_nodes if n not in senders]
    sp = "/".join(senders) or "?"
    rp = "/".join(receivers) or "?"
    return f"{sp} → {rp}"


def print_markdown(messages):
    print("# CAN 信号查找表（供 SAD 时序图标注真实信号）\n")
    for m in messages:
        direction = fmt_dir(m["nodes"], m.get("all_nodes"))
        node_str = ", ".join(f"{n}={v}" for n, v in m["nodes"].items())
        print(f"## 报文 {m['msg_name']} ({m['msg_id']})")
        print(f"- 周期 {m['msg_cycle']}ms · DLC {m['msg_dlc']} · 发送类型 {m['msg_send_type']}")
        if direction:
            print(f"- 方向：**{direction}**（{node_str}）")
        if m["signals"]:
            print("\n| 信号 | 描述 | 起始字节.位 | 长度 | 精度 | 偏移 | 物理范围 | 单位 |")
            print("|---|---|---|---|---|---|---|---|")
            for s in m["signals"]:
                rng = f"{s['phys_min']}~{s['phys_max']}" if (s['phys_min'] or s['phys_max']) else ""
                print(f"| {s['name']} | {s['desc']} | {s['start_byte']}.{s['start_bit']} | "
                      f"{s['bit_length']} | {s['factor']} | {s['offset']} | {rng} | {s['unit']} |")
        print()
    print("> 时序图箭头标注建议：`<报文ID> <信号名>`，方向按上面的 S→R。例如 "
          "`整车 -> COM : 0x201 OXY_Seat1_Ctrl_Nasal_Gear`、"
          "`COM -> 整车 : 0x203 OXY_Status_Concentration`。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--json", action="store_true", help="print JSON only")
    ap.add_argument("--signal", help="look up a single signal by (sub)name and print its message/direction")
    args = ap.parse_args()

    try:
        messages = parse(args.xlsx)
    except Exception as e:
        print(f"ERROR parsing {args.xlsx}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.signal:
        q = args.signal.lower()
        hits = []
        for m in messages:
            for s in m["signals"]:
                if q in s["name"].lower():
                    hits.append((m, s))
        if not hits:
            print(f"（未找到含 '{args.signal}' 的信号）")
            return
        for m, s in hits:
            print(f"{s['name']}  ∈  {m['msg_name']} ({m['msg_id']})  方向 {fmt_dir(m['nodes'], m.get('all_nodes'))}  "
                  f"起始 {s['start_byte']}.{s['start_bit']} 长 {s['bit_length']} 单位 {s['unit'] or '-'}")
        return

    if args.json:
        print(json.dumps(messages, ensure_ascii=False, indent=2))
        return

    print_markdown(messages)
    print("\n--- JSON ---")
    print(json.dumps(messages, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

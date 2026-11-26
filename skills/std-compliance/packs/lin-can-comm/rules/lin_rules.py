"""config rules for ISO 17987-2/-3 and ISO 14229-7 (LIN side). Inputs: LDF (ctx.ldf) + ARXML LinIf/LinTp."""
from core import FAIL, NOTRUN, PASS, result
from parsers import arxml as A

DIAG_IDS = (0x3C, 0x3D)


def _hex(v):
    return f"0x{v:02X}" if isinstance(v, int) else str(v)


def _linif_frames(ctx):
    out = []
    for r in A.find(ctx.arxml, "LinIf", "LinIfFrame"):
        fid = A.num(r["params"].get("LinIfFrameId"))
        out.append({"name": r["name"], "id": fid, "cks": r["params"].get("LinIfChecksumType"),
                    "type": r["params"].get("LinIfFrameType"), "dlc": A.num(r["params"].get("FrameDlc"))})
    return out


def _need_ldf(ctx):
    return None if ctx.ldf else result(NOTRUN, "未配置 LDF（inputs.ldf）")


def sig_single_publisher(ctx):
    if (r := _need_ldf(ctx)):
        return r
    bad = []
    for fname, f in ctx.ldf["frames"].items():
        for s in f["signals"]:
            sig = ctx.ldf["signals"].get(s["name"])
            if sig and f.get("publisher") and sig["publisher"] != f["publisher"]:
                bad.append(f"{s['name']}（信号发布者 {sig['publisher']}，帧 {fname} 发布者 {f['publisher']}）")
    n = len(ctx.ldf["signals"])
    return result(FAIL if bad else PASS, f"LDF 信号 {n} 个均只有一个发布者" if not bad else "发布者不一致：" + "；".join(bad[:8]))


def sig_init_values(ctx):
    if (r := _need_ldf(ctx)):
        return r
    miss = [k for k, v in ctx.ldf["signals"].items() if not str(v.get("init", "")).strip()]
    return result(FAIL if miss else PASS, f"LDF 信号 {len(ctx.ldf['signals'])} 个" + ("均有初始值" if not miss else f"，缺初始值：{', '.join(miss[:10])}"))


def frame_ids(ctx):
    if (r := _need_ldf(ctx)):
        return r
    bad = [f"{n}={_hex(f['id'])}" for n, f in ctx.ldf["frames"].items() if not 0 <= f["id"] <= 59]
    diag = {f["id"] for f in ctx.ldf["diagnostic_frames"].values()}
    extra = [f"诊断帧 ID {_hex(i)}" for i in diag if i not in DIAG_IDS]
    msg = f"信号帧 ID：{', '.join(_hex(f['id']) for f in ctx.ldf['frames'].values())}；诊断帧：{', '.join(_hex(i) for i in sorted(diag))}"
    probs = bad + extra
    return result(FAIL if probs else PASS, msg + ("" if not probs else "；违规：" + "，".join(probs)))


def diag_classic(ctx):
    fr = [f for f in _linif_frames(ctx) if f["id"] in DIAG_IDS]
    if not fr:
        return result(NOTRUN, "ARXML 中未找到 LinIf 诊断帧（0x3C/0x3D）")
    bad = [f"{_hex(f['id'])}={f['cks']}" for f in fr if str(f["cks"]).upper() != "CLASSIC"]
    return result(FAIL if bad else PASS, "LinIf 诊断帧校验和：" + ", ".join(f"{_hex(f['id'])}={f['cks']}" for f in fr))


def signal_enhanced(ctx):
    fr = [f for f in _linif_frames(ctx) if f["id"] not in DIAG_IDS]
    if not fr:
        return result(NOTRUN, "ARXML 中未找到 LinIf 信号帧")
    ver = str(ctx.ldf.get("header", {}).get("protocol_version", "")) if ctx.ldf else ""
    want = "CLASSIC" if ver.startswith("1.") else "ENHANCED"
    bad = [f"{_hex(f['id'])}={f['cks']}" for f in fr if str(f["cks"]).upper() != want]
    ldf_ids = {f["id"] for f in ctx.ldf.get("frames", {}).values()} if ctx.ldf else set()
    miss = sorted(ldf_ids - {f["id"] for f in fr})
    ev = f"LDF 协议版本 {ver or '?'} → 期望 {want}；LinIf 信号帧：" + ", ".join(f"{_hex(f['id'])}={f['cks']}" for f in fr)
    if miss:
        ev += f"；LDF 中有、LinIf 未配置的帧：{', '.join(_hex(i) for i in miss)}"
    return result(FAIL if bad else PASS, ev)


def diag_len8(ctx):
    if (r := _need_ldf(ctx)):
        return r
    ldf_bad = [f"{n}={f['length']}" for n, f in ctx.ldf["diagnostic_frames"].items() if f["length"] != 8]
    cfg_bad = [f"{_hex(f['id'])}={f['dlc']}" for f in _linif_frames(ctx) if f["id"] in DIAG_IDS and f["dlc"] != 8]
    bad = ldf_bad + cfg_bad
    return result(FAIL if bad else PASS, "诊断帧长度 LDF 与 LinIf 均为 8" if not bad else "长度不为 8：" + ", ".join(bad))


def schedule_slots(ctx):
    if (r := _need_ldf(ctx)):
        return r
    spd = ctx.ldf["header"].get("speed_kbps")
    jit = ctx.ldf["nodes"].get("commander", {}).get("jitter_ms", 0.0)
    if not spd:
        return result(NOTRUN, "LDF 缺少 LIN_speed")
    allf = {**ctx.ldf["frames"], **ctx.ldf["diagnostic_frames"]}
    bad, rows = [], []
    for t, entries in ctx.ldf["schedule_tables"].items():
        for e in entries:
            f = allf.get(e["entry"].split()[0])
            if not f:
                continue
            tmax = 1.4 * (34 + 10 * (f["length"] + 1)) / spd  # ms; nominal header+response with 40 % margin
            need = tmax + jit
            rows.append(f"{t}/{e['entry']}: {e['delay_ms']}≥{need:.2f}")
            if e["delay_ms"] < need:
                bad.append(f"{t}/{e['entry']} delay {e['delay_ms']} ms < {need:.2f} ms")
    return result(FAIL if bad else PASS, f"按 {spd} kbps、抖动 {jit} ms 计算帧最大时长；" + ("; ".join(bad) if bad else "全部帧槽足够：" + "；".join(rows[:6])))


def response_error(ctx):
    name, attrs = ctx.ldf_node
    if attrs is None:
        return result(NOTRUN, f"LDF 中找不到本节点 {name!r} 的 Node_attributes（node.ldf_name）")
    sig = attrs.get("response_error")
    if not sig:
        return result(FAIL, f"LDF Node_attributes.{name} 未声明 response_error 信号")
    s = ctx.ldf["signals"].get(sig)
    host = [n for n, f in ctx.ldf["frames"].items() if f.get("publisher") == name and any(x["name"] == sig for x in f["signals"])]
    probs = []
    if not s:
        probs.append("信号未在 Signals 中定义")
    elif s["publisher"] != name or s["size"] != 1:
        probs.append(f"信号发布者 {s['publisher']}、长度 {s['size']} 位")
    if not host:
        probs.append("未映射到本节点发布的无条件帧")
    return result(FAIL if probs else PASS, f"response_error = {sig}" + ("" if not probs else "；" + "；".join(probs)) + (f"；承载帧 {', '.join(host)}" if host else ""))


def product_id(ctx):
    name, attrs = ctx.ldf_node
    if attrs is None:
        return result(NOTRUN, f"LDF 中找不到本节点 {name!r} 的 Node_attributes")
    pid = attrs.get("product_id")
    if not pid or len(pid) < 2:
        return result(FAIL, f"LDF {name} 未声明 product_id")
    sup, fun = pid[0], pid[1]
    bad = []
    if sup == 0x7FFF:
        bad.append("供应商 ID 为通配值 0x7FFF")
    if fun == 0xFFFF:
        bad.append("功能 ID 为通配值 0xFFFF")
    ev = f"product_id：供应商 ID {_hex(sup)}，功能 ID {_hex(fun)}，变体 {pid[2] if len(pid) > 2 else '-'}"
    if sup == 0:
        ev += "（供应商 ID 为 0x0000，请确认是否为分配给本供应商的值）"
    return result(FAIL if bad else PASS, ev + ("；" + "，".join(bad) if bad else ""))


def _nads(ctx):
    name, attrs = ctx.ldf_node
    ldf = {k: attrs.get(k) for k in ("initial_NAD", "configured_NAD")} if attrs else {}
    tp = sorted({v for v in ctx.param("LinTpRxNSduNad", "LinTp") + ctx.param("LinTpTxNSduNad", "LinTp")
                 if isinstance(v, int) and v not in (0x7E, 0x7F)})
    exp = A.num(ctx.prj.get("expected.nad_physical"))
    return name, ldf, tp, exp


def nad_consistent(ctx):
    name, ldf, tp, exp = _nads(ctx)
    if not ldf and not tp:
        return result(NOTRUN, "LDF 与 ARXML 中都没有 NAD 信息")
    vals = {f"LDF {name}.{k}": v for k, v in ldf.items() if v is not None}
    vals.update({f"LinTp 物理 NAD#{i + 1}": v for i, v in enumerate(tp)})
    if isinstance(exp, int):
        vals["需求期望"] = exp
    ok = len(set(vals.values())) == 1
    return result(PASS if ok else FAIL, "；".join(f"{k}={_hex(v)}" for k, v in vals.items()) + ("" if ok else " —— 不一致"))


def bus_idle_timeout(ctx):
    v = ctx.param("LinIfBusIdleTimeoutPeriod", "LinIf")
    if not v:
        return result(NOTRUN, "ARXML 中没有 LinIfBusIdleTimeoutPeriod（或未在 LinIf 中配置静默超时）")
    bad = [x for x in v if not (isinstance(x, (int, float)) and 4000 <= x <= 10000)]
    return result(FAIL if bad else PASS, f"LinIfBusIdleTimeoutPeriod = {', '.join(str(x) for x in v)} ms（要求 4000~10000 ms）")


def tp_timeouts(ctx):
    nas = sorted(set(ctx.param("LinTpNas", "LinTp")))
    ncr = sorted(set(ctx.param("LinTpNcr", "LinTp")))
    if not nas and not ncr:
        return result(NOTRUN, "ARXML 中没有 LinTpNas/LinTpNcr")
    name, attrs = ctx.ldf_node
    d_as = (attrs or {}).get("N_As_timeout")
    d_cr = (attrs or {}).get("N_Cr_timeout")
    lim_as = min(x for x in (1000, d_as) if x is not None)
    lim_cr = min(x for x in (1000, d_cr) if x is not None)
    bad = [f"N_As={x}>{lim_as}" for x in nas if x > lim_as] + [f"N_Cr={x}>{lim_cr}" for x in ncr if x > lim_cr]
    ev = f"实现 N_As={nas} ms、N_Cr={ncr} ms；LDF 声明 N_As={d_as}、N_Cr={d_cr} ms；上限 1000 ms"
    warn = [f"N_Cr 实现值 {x} 小于声明值 {d_cr}" for x in ncr if d_cr and x < d_cr] + \
           [f"N_As 实现值 {x} 小于声明值 {d_as}" for x in nas if d_as and x < d_as]
    if warn:
        ev += "；提示：" + "，".join(warn) + "（主节点按声明值调度时本节点可能提前超时，建议统一）"
    return result(FAIL if bad else PASS, ev + ("；超限：" + "，".join(bad) if bad else ""))


def st_min(ctx):
    name, attrs = ctx.ldf_node
    if attrs is None or attrs.get("ST_min") is None:
        return result(NOTRUN, f"LDF {name!r} 未声明 ST_min")
    v = attrs["ST_min"]
    return result(PASS, f"LDF {name}.ST_min = {v} ms" + ("；声明 0 ms 表示本节点须能背靠背接收连续帧，需结合 LinTp 接收处理评审" if v == 0 else ""))


def p2_values(ctx):
    p2 = ctx.param("DcmDspSessionP2ServerMax", "Dcm")
    p2s = ctx.param("DcmDspSessionP2StarServerMax", "Dcm")
    if not p2:
        return result(NOTRUN, "ARXML Dcm 中没有 DcmDspSessionP2ServerMax")
    name, attrs = ctx.ldf_node
    p2min = (attrs or {}).get("P2_min")
    bad = [f"P2={x}" for x in p2 if not 50 <= x <= 500] + [f"P2*={x}" for x in p2s if x > 2000]
    if p2min is not None:
        bad += [f"P2={x} < LDF P2_min {p2min}" for x in p2 if x < p2min]
    ltp = ctx.param("LinTpP2Timing", "LinTp"), ctx.param("LinTpP2Max", "LinTp")
    ev = f"Dcm P2={sorted(set(p2))} ms、P2*={sorted(set(p2s))} ms；LDF P2_min={p2min} ms；LinTp P2Timing={ltp[0]}、P2Max={ltp[1]}"
    if any(x > 2000 for x in ltp[1]):
        ev += "（LinTpP2Max 超过 2000 ms，需确认其语义：若为本节点响应挂起上限则不符合）"
    return result(FAIL if bad else PASS, ev + ("；违规：" + "，".join(bad) if bad else ""))


def nad_7e_ignored(ctx):
    fun = [(r["name"], r["params"].get("RxTaType")) for r in A.find(ctx.arxml, "LinTp", "LinTpRxNSdu")
           if A.num(r["params"].get("LinTpRxNSduNad")) == 0x7E]
    if not A.find(ctx.arxml, "LinTp"):
        return result(NOTRUN, "ARXML 中没有 LinTp 配置")
    if fun:
        return result(FAIL, "LinTp 配置了 NAD 0x7E 的接收 N-SDU：" + ", ".join(f"{n}({t})" for n, t in fun) +
                      "。若 OEM 需求要求支持 0x7E 功能寻址，请在 applicability_overrides 中记录偏差与理由")
    return result(PASS, "LinTp 未配置 NAD 0x7E 接收")


def tp_buffer(ctx):
    buf = ctx.param("DcmDslBufferSize", "Dcm")
    if not buf:
        return result(NOTRUN, "ARXML Dcm 中没有 DcmDslBufferSize")
    need = A.num(ctx.prj.get("expected.tp_buffer_min"))
    mx = ctx.param("DcmDslProtocolMaximumResponseSize", "Dcm")
    ev = f"Dcm 缓冲区 {buf} 字节；最大响应长度配置 {mx}"
    bad = []
    if isinstance(need, int):
        ev += f"；需求最小值 {need}"
        bad += [f"缓冲区 {b} < {need}" for b in buf if b < need]
    if mx and buf and max(mx) > min(buf):
        ev += "；最大响应长度大于缓冲区，长响应会被截断或拒绝，需确认"
    return result(FAIL if bad else PASS, ev + ("；" + "，".join(bad) if bad else ""))


RULES = {
    "LIN3-SIG-01": sig_single_publisher,
    "LIN3-SIG-02": sig_init_values,
    "LIN3-FRM-01": frame_ids,
    "LIN3-CKS-01": diag_classic,
    "LIN3-CKS-02": signal_enhanced,
    "LIN3-DIAG-01": diag_len8,
    "LIN3-SCH-02": schedule_slots,
    "LIN3-STA-01": response_error,
    "LIN3-ID-01": product_id,
    "LIN3-NC-11": nad_consistent,
    "LIN2-NM-03": bus_idle_timeout,
    "LIN2-TP-09": tp_timeouts,
    "LIN2-TP-12": st_min,
    "LIN2-DG-01": p2_values,
    "UDS7-NAD-01": nad_consistent,
    "UDS7-NAD-02": nad_7e_ignored,
    "UDS7-LEN-01": tp_buffer,
    "UDS7-DL-01": diag_classic,
}

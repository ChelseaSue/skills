"""config rules for ISO 14229-1/-2/-3/-7 (bus independent, ARXML Dcm) and ISO 15765-2 (ARXML CanTp)."""
from core import FAIL, NOTRUN, PASS, result
from parsers import arxml as A

UDSONLIN_FORBIDDEN = {0x83, 0x29, 0x84, 0x87, 0x23, 0x24, 0x2A, 0x2C, 0x3D}


def s3_server(ctx):
    v = ctx.param("S3Server", "Dcm") or ctx.param("DcmTimStrS3Server", "Dcm") or ctx.param("DcmDspSessionS3Server", "Dcm")
    if not v:
        return result(NOTRUN, "ARXML Dcm 中没有 S3 参数（S3Server / DcmTimStrS3Server）")
    bad = [x for x in v if x != 5000]
    return result(FAIL if bad else PASS, f"S3Server = {sorted(set(v))} ms（要求 5000 ms）")


def task_vs_p2(ctx):
    t = ctx.param("DcmTaskTime", "Dcm")
    p2 = ctx.param("DcmDspSessionP2ServerMax", "Dcm")
    if not t or not p2:
        return result(NOTRUN, "ARXML 缺少 DcmTaskTime 或 DcmDspSessionP2ServerMax")
    ok = max(t) < min(p2)
    return result(PASS if ok else FAIL, f"Dcm 主函数周期 {max(t)} ms，最小 P2Server_max {min(p2)} ms")


def seed_key_parity(ctx):
    lv = [A.num(v) for v in A.param_values(ctx.arxml, "DcmDspSecurityLevel", "Dcm")]
    lv = [x for x in lv if isinstance(x, int)]
    if not lv:
        return result(NOTRUN, "ARXML Dcm 中没有 DcmDspSecurityLevel")
    pairs = [f"等级 {x}: requestSeed 0x{2 * x - 1:02X} / sendKey 0x{2 * x:02X}" for x in sorted(set(lv))]
    return result(PASS, "按 AUTOSAR 安全等级映射，子功能 = 2×等级−1（种子）/ 2×等级（密钥），满足奇偶规则：" + "；".join(pairs))


def udsonlin_services(ctx):
    from parsers.arxml import supported_sids
    sids = supported_sids(ctx.arxml)
    if not sids:
        return result(NOTRUN, "ARXML Dcm 中没有服务表")
    bad = [f"0x{s:02X}" for s in sids if s in UDSONLIN_FORBIDDEN]
    return result(FAIL if bad else PASS, "Dcm 服务表：" + ", ".join(f"0x{s:02X}" for s in sids) + (f"；UDSonLIN 不支持的服务：{', '.join(bad)}" if bad else ""))


def cantp_timeouts(ctx):
    names = ("CanTpNas", "CanTpNar", "CanTpNbs", "CanTpNcr")
    vals = {n: ctx.param(n, "CanTp") for n in names}
    if not any(vals.values()):
        return result(NOTRUN, "ARXML 中没有 CanTp 超时参数")
    bad = []
    for n, vs in vals.items():
        for v in vs:
            ms = v * 1000 if isinstance(v, float) and v < 10 else v       # AUTOSAR stores seconds as float
            if not 1000 <= ms <= 1500:
                bad.append(f"{n}={v}")
    return result(FAIL if bad else PASS, "；".join(f"{n}={v}" for n, v in vals.items()) + ("；超出 [1000,1500] ms：" + "，".join(bad) if bad else ""))


def cantp_wft(ctx):
    v = ctx.param("CanTpRxWftMax", "CanTp")
    if not v:
        return result(NOTRUN, "ARXML 中没有 CanTpRxWftMax")
    return result(PASS, f"CanTpRxWftMax = {v}" + ("（为 0 时实现不得发送 FC WAIT，需结合宿主机测试确认）" if 0 in v else ""))


def uds3_timing(ctx):
    p2 = ctx.param("DcmDspSessionP2ServerMax", "Dcm")
    p2s = ctx.param("DcmDspSessionP2StarServerMax", "Dcm")
    if not p2:
        return result(NOTRUN, "ARXML Dcm 中没有 P2 参数")
    bad = [f"P2={x}" for x in p2 if x > 50] + [f"P2*={x}" for x in p2s if x > 5000]
    return result(FAIL if bad else PASS, f"P2={sorted(set(p2))} ms、P2*={sorted(set(p2s))} ms（UDSonCAN 常用 ≤50 / ≤5000 ms，以 OEM 规定为准）"
                  + ("；" + "，".join(bad) if bad else ""))


RULES = {
    "UDS2-SES-02": s3_server,
    "UDS2-PERF-01": task_vs_p2,
    "UDS1-SA-01": seed_key_parity,
    "UDS7-SVC-01": udsonlin_services,
    "CANTP-TIM-01": cantp_timeouts,
    "CANTP-WFT-01": cantp_wft,
    "UDS3-TIM-01": uds3_timing,
}

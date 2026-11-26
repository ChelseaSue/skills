"""Fixture rules exercising the rule API (see references/framework.md)."""
from core import FAIL, NOTRUN, PASS, result


def diag_frames(ctx):
    if not ctx.ldf:
        return result(NOTRUN, "未配置 LDF")
    ids = {f["id"] for f in ctx.ldf.get("diagnostic_frames", {}).values()}
    miss = [f"0x{i:02X}" for i in (0x3C, 0x3D) if i not in ids]
    return result(FAIL if miss else PASS, f"LDF 诊断帧 ID：{sorted(f'0x{i:02X}' for i in ids)}" + (f"；缺少 {miss}" if miss else ""))


def nad_consistent(ctx):
    name, attrs = ctx.ldf_node
    if not attrs:
        return result(NOTRUN, f"LDF 中找不到节点 {name!r} 的 Node_attributes（node.ldf_name）")
    tp = {v for v in ctx.param("LinTpRxNSduNad", "LinTp") if isinstance(v, int) and v != 0x7E}
    if not tp:
        return result(NOTRUN, "ARXML 中没有 LinTp 物理寻址 NAD")
    ldf_nad = attrs.get("configured_NAD")
    ok = tp == {ldf_nad}
    return result(PASS if ok else FAIL, f"LDF {name}.configured_NAD=0x{ldf_nad:02X}；LinTp 物理 NAD={', '.join(f'0x{v:02X}' for v in sorted(tp))}")


RULES = {"FX-CFG-DIAGFRAMES": diag_frames, "FX-CFG-NAD": nad_consistent}

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 layers.json + module_spec.json 生成「卡片风格」分层架构图（SVG，可选 PNG）。

绘图要求（详见 references/diagram-guide.md）：
- 纵向逐层堆叠（layers 中“非横切”的层，按高→低），每层：左侧彩色竖标签(中文层名) + 顶部
  紫色层标题条(英文层名 + 前缀) + 层内模块卡片(渐变圆角块；可按 module 的 group 字段分组虚线框)。
- 横切层(layers.json 的 cross_cutting)**画成右侧竖条**，竖向**跨它的使用者层**，用虚线箭头连过去，
  不占纵向层序。使用者层 = 声明 deps 依赖了该横切层模块的那些层（自动推断；也可在 layers.json 用
  cross_spans 显式给定）。
- 配色：layers.json 可给 colors{层:{fill,accent}}；否则用内置调色板。
- 数据全部来自配置，**不硬编码任何项目**。

用法:
  python3 render_layer_diagram.py --layers layers.json --spec module_spec.json --out arch_diagram
      [--title "XXX 软件分层架构"] [--font "SimHei"] [--no-png]
输出: <out>.svg（始终）、<out>.png（装了 cairosvg 时）。
"""
import argparse
import json
import os

PALETTE = [  # (fill, accent) 供未指定颜色的层循环使用
    ("#9FC5E8", "#1976D2"), ("#F6B26B", "#EF6C00"), ("#93C47D", "#2E7D32"),
    ("#A8D08D", "#1B5E20"), ("#D7D86E", "#827717"), ("#FFD966", "#E65100"),
    ("#B6D7A8", "#33691E"), ("#9CC3E0", "#2E5E8C"),
]
CROSS_FILL = "#C9A8DC"
CROSS_ACCENT = "#6A1B9A"


def lighten(hexc, f=0.45):
    c = hexc.lstrip('#'); r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    r = int(r + (255 - r) * f); g = int(g + (255 - g) * f); b = int(b + (255 - b) * f)
    return f"#{r:02x}{g:02x}{b:02x}"


class SVG:
    def __init__(self, font):
        self.font = font; self.body = []; self.defs = []; self._g = {}
        self.defs.append('<linearGradient id="tbar" x1="0" y1="0" x2="0" y2="1">'
                         '<stop offset="0" stop-color="#CB9BDA"/><stop offset="1" stop-color="#9B59B6"/></linearGradient>')
        self.defs.append('<marker id="arr" markerWidth="9" markerHeight="9" refX="6.5" refY="3" orient="auto">'
                         '<path d="M0,0 L6.5,3 L0,6 z" fill="%s"/></marker>' % CROSS_ACCENT)
        self.defs.append('<marker id="arrR" markerWidth="9" markerHeight="9" refX="0.5" refY="3" orient="auto">'
                         '<path d="M6.5,0 L0,3 L6.5,6 z" fill="%s"/></marker>' % CROSS_ACCENT)

    def grad(self, base):
        if base not in self._g:
            gid = f"g{len(self._g)}"
            self.defs.append(f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
                             f'<stop offset="0" stop-color="{lighten(base,0.55)}"/>'
                             f'<stop offset="1" stop-color="{base}"/></linearGradient>')
            self._g[base] = f"url(#{gid})"
        return self._g[base]

    def rect(self, x, y, w, h, rx, fill, stroke="#888", sw=1, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ''
        self.body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
                         f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, size=13, fill="#333", anchor="middle", weight="normal"):
        s = (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        self.body.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{self.font}" font-size="{size}" '
                         f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" '
                         f'dominant-baseline="middle">{s}</text>')

    def line(self, x1, y1, x2, y2, color, dash=None, marker_both=False):
        d = f' stroke-dasharray="{dash}"' if dash else ''
        m = ' marker-end="url(#arr)" marker-start="url(#arrR)"' if marker_both else ' marker-end="url(#arr)"'
        self.body.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                         f'stroke="{color}" stroke-width="1.4"{d}{m}/>')

    def out(self, w, h):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<defs>' + "".join(self.defs) + '</defs>'
                f'<rect width="{w}" height="{h}" fill="#ffffff"/>' + "".join(self.body) + '</svg>')


def module_layer_index(spec):
    """模块名(去前缀/扩展名后的 stem) -> 所属层。用于把 deps 解析到层。"""
    idx = {}
    for m in spec.get("modules", []):
        idx[m["name"]] = m["layer"]
    return idx


def dep_to_layer(dep, mod2layer, header_map):
    base = os.path.basename(dep)
    stem = base[:-2] if base.lower().endswith(".h") else base
    if base in header_map:
        return header_map[base]
    if stem in header_map:
        return header_map[stem]
    if stem in mod2layer:
        return mod2layer[stem]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layers", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True, help="输出基名（不含扩展名）")
    ap.add_argument("--title", default="软件分层架构")
    ap.add_argument("--font", default="SimHei, Noto Sans CJK SC, sans-serif")
    ap.add_argument("--no-png", action="store_true")
    args = ap.parse_args()

    layers_cfg = json.load(open(args.layers, encoding="utf-8"))
    spec = json.load(open(args.spec, encoding="utf-8"))
    order = layers_cfg["layers"]
    cross = layers_cfg.get("cross_cutting", [])
    fpfx = layers_cfg.get("file_prefix", {})
    colors = layers_cfg.get("colors", {})
    labels = layers_cfg.get("labels", {})          # 层 key -> 显示名(如中文)；竖标签用它，缺省用 key
    cross_spans = layers_cfg.get("cross_spans", {})
    header_map = layers_cfg.get("header_map", {})
    mod2layer = module_layer_index(spec)

    vertical = [l for l in order if l not in cross]      # 纵向层
    cross_layers = []                                     # 横切层（来自 cross_cutting，去重保序）
    for c in cross:
        if c not in cross_layers:
            cross_layers.append(c)

    # 每层模块（按 group 聚合，保持出现顺序）
    by_layer = {l: [] for l in order}
    for m in spec.get("modules", []):
        by_layer.setdefault(m["layer"], []).append(m)

    # 推断每个横切层的使用者层范围
    users = {c: set() for c in cross_layers}
    for L in vertical:
        for m in by_layer.get(L, []):
            for dep in m.get("deps", []):
                dl = dep_to_layer(dep, mod2layer, header_map)
                if dl in users:
                    users[dl].add(L)
    span = {}
    for c in cross_layers:
        if c in cross_spans and cross_spans[c]:
            us = [l for l in vertical if l in set(cross_spans[c])]
        elif users[c]:
            us = [l for l in vertical if l in users[c]]
        else:
            us = list(vertical)  # 推断不出 -> 跨全部
        span[c] = us

    def col(layer, i):
        if layer in colors:
            return colors[layer].get("fill"), colors[layer].get("accent")
        f, a = PALETTE[i % len(PALETTE)]
        return f, a

    # ---- 布局尺寸 ----
    FONT = args.font
    PANEL_X = 56
    CROSS_W = 132
    CROSS_GAP = 12
    n_cross = max(len(cross_layers), 0)
    cross_total = (CROSS_W + CROSS_GAP) * n_cross if n_cross else 0
    W = 760 + cross_total + 60
    MAIN_RIGHT = W - 14 - cross_total
    PANEL_W = MAIN_RIGHT - PANEL_X
    PAD = 14; TITLE_H = 30; GRP_TITLE_H = 22; BLK_GAP = 10
    s = SVG(FONT)
    x = PANEL_X + PAD
    bounds = {}
    y = 52

    def blocks(bx, by, bw, items, cols, base, h=44):
        n = len(items); rows = (n + cols - 1) // cols
        cw = (bw - BLK_GAP * (cols - 1)) / cols
        for i, it in enumerate(items):
            r, c = divmod(i, cols)
            xx = bx + c * (cw + BLK_GAP); yy = by + r * (h + BLK_GAP)
            s.rect(xx, yy, cw, h, 7, s.grad(base), stroke="#9a9a9a", sw=1)
            for li, ln in enumerate(str(it).split("\n")):
                s.text(xx + cw / 2, yy + h / 2 + (li - (len(str(it).split("\n")) - 1) / 2) * 13, ln, size=11.5, fill="#1a1a1a")
        return rows * h + (rows - 1) * BLK_GAP

    def draw_layer(L, idx):
        nonlocal y
        fill, accent = col(L, idx)
        y0 = y
        # 标题条
        s.rect(PANEL_X + PAD, y0 + PAD, PANEL_W - 2 * PAD, TITLE_H, 7, "url(#tbar)", stroke="#7E3F96", sw=1)
        pfx = fpfx.get(L)
        ttl = f"{L}    （前缀 {pfx}）" if pfx else L
        s.text(PANEL_X + PANEL_W / 2, y0 + PAD + TITLE_H / 2, ttl, size=14, fill="#ffffff", weight="bold")
        cy = y0 + PAD + TITLE_H + 10
        mods = by_layer.get(L, [])
        names = [m["name"] for m in mods] or ["（待补充模块）"]
        # 按 group 分组？
        groups = {}
        for m in mods:
            groups.setdefault(m.get("group"), []).append(m["name"])
        if len(groups) > 1 or (len(groups) == 1 and None not in groups):
            body_h = 0
            for gname, gitems in groups.items():
                cols = min(len(gitems), 6) or 1
                gtitle = gname or "其它"
                bh = blocks(x + 10, cy + body_h + GRP_TITLE_H, PANEL_W - 2 * PAD - 20, gitems, cols, fill, 40)
                gh = GRP_TITLE_H + bh + 12
                s.rect(x, cy + body_h, PANEL_W - 2 * PAD, gh, 9, "none", stroke=accent, sw=1.3, dash="5,4")
                s.text(x + (PANEL_W - 2 * PAD) / 2, cy + body_h + GRP_TITLE_H / 2 + 3, gtitle, size=12, fill=accent, weight="bold")
                body_h += gh + 10
            body_h -= 10
        else:
            cols = min(len(names), 7) or 1
            body_h = blocks(x, cy, PANEL_W - 2 * PAD, names, cols, fill, 44)
        total = PAD + TITLE_H + 10 + body_h + PAD
        s.rect(PANEL_X, y0, PANEL_W, total, 12, "none", stroke=accent, sw=2)
        # 左侧竖标签（显示名优先用 labels）
        s.rect(8, y0, 40, total, 8, s.grad(accent), stroke="#7a7a7a", sw=1)
        chars = list(labels.get(L, L)); ch_gap = min(22, (total - 16) / max(len(chars), 1))
        st = y0 + total / 2 - ch_gap * (len(chars) - 1) / 2
        for i, ch in enumerate(chars):
            s.text(28, st + i * ch_gap, ch, size=14, fill="#ffffff", weight="bold")
        bounds[L] = (y0, y0 + total)
        y = y0 + total + 16

    for i, L in enumerate(vertical):
        draw_layer(L, i)

    # ---- 横切层竖条 ----
    for ci, c in enumerate(cross_layers):
        us = span[c]
        if not us:
            continue
        top = min(bounds[u][0] for u in us)
        bot = max(bounds[u][1] for u in us)
        cx = MAIN_RIGHT + CROSS_GAP + ci * (CROSS_W + CROSS_GAP)
        s.rect(cx, top, CROSS_W, bot - top, 12, s.grad("#F1E3F7"), stroke=CROSS_ACCENT, sw=2, dash="6,4")
        s.text(cx + CROSS_W / 2, top + 16, f"横切层 {labels.get(c, c)}", size=13, fill=CROSS_ACCENT, weight="bold")
        s.text(cx + CROSS_W / 2, top + 31, "(跨多层 · 任意层可用)", size=9, fill=CROSS_ACCENT)
        cmods = [m["name"] for m in by_layer.get(c, [])] or [c]
        by_ = top + 46
        for nm in cmods:
            s.rect(cx + 11, by_, CROSS_W - 22, 50, 8, s.grad(CROSS_FILL), stroke="#8a6aa0", sw=1)
            s.text(cx + CROSS_W / 2, by_ + 25, nm, size=11.5, fill="#1a1a1a", weight="bold")
            by_ += 60
        # 使用者层 -> 竖条 的虚线箭头
        for u in us:
            t, b = bounds[u]; my = (t + b) / 2
            s.line(MAIN_RIGHT, my, cx, my, CROSS_ACCENT, dash="5,3", marker_both=True)

    # 标题
    s.text(W / 2, 24, args.title, size=18, fill="#333", weight="bold")
    s.text(W / 2, 42, "（纵向=分层，右侧竖条=横切层；数据源自 layers.json + module_spec.json）", size=10.5, fill="#777")

    H = y + 8
    svg_text = s.out(W, int(H))
    open(args.out + ".svg", "w", encoding="utf-8").write(svg_text)
    print("written", args.out + ".svg", f"({W}x{int(H)})")
    if not args.no_png:
        try:
            import cairosvg
            cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), write_to=args.out + ".png",
                             output_width=W, output_height=int(H))
            print("written", args.out + ".png")
        except Exception as e:
            print(f"[提示] 未生成 PNG（{e}）。装 cairosvg 即可：pip install cairosvg；或用浏览器/工具打开 .svg")


if __name__ == "__main__":
    main()

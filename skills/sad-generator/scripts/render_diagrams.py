#!/usr/bin/env python3
"""Render the diagrams referenced by a Markdown SRS into PNGs, and emit a "rendered" Markdown
where each diagram fence is replaced by an image link — so the docx builder only deals with images.

Handles:
  * ```mermaid  fenced blocks   -> mmdc
  * ```plantuml fenced blocks   -> plantuml  (also accepts blocks starting with @startuml)
  * a .vsdx file (Visio)        -> soffice --convert-to pdf then pdftoppm (page 1 by default)

Usage:
  python3 render_diagrams.py <srs.md> --outdir <imgdir> [--rendered-md <out.md>]
  python3 render_diagrams.py --vsdx <file.vsdx> --outdir <imgdir> [--page N]

Requires: mmdc, plantuml, soffice/libreoffice, pdftoppm (poppler) for vsdx. Each is only needed if
the corresponding input is present; missing tools are reported but don't abort the others.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def have(tool):
    return shutil.which(tool) is not None


def render_mermaid(code, out_png):
    if not have("mmdc"):
        print("WARN: mmdc 不可用，跳过一个 mermaid 图", file=sys.stderr)
        return False
    src = out_png.replace(".png", ".mmd")
    with open(src, "w") as f:
        f.write(code)
    # white background, scale up for crisper embed
    r = sh(["mmdc", "-i", src, "-o", out_png, "-b", "white", "-s", "2"])
    if r.returncode != 0:
        print(f"WARN mermaid 渲染失败: {r.stderr[:300]}", file=sys.stderr)
        return False
    return os.path.exists(out_png)


def render_plantuml(code, out_png):
    if not have("plantuml"):
        print("WARN: plantuml 不可用，跳过一个 plantuml 图", file=sys.stderr)
        return False
    if "@startuml" not in code:
        code = "@startuml\n" + code + "\n@enduml\n"
    src = out_png.replace(".png", ".puml")
    with open(src, "w") as f:
        f.write(code)
    r = sh(["plantuml", "-tpng", src])  # writes <src without ext>.png next to src
    produced = src.replace(".puml", ".png")
    if r.returncode != 0 or not os.path.exists(produced):
        print(f"WARN plantuml 渲染失败: {r.stderr[:300]}", file=sys.stderr)
        return False
    if produced != out_png:
        shutil.move(produced, out_png)
    return True


def render_vsdx(vsdx, out_png, page=1):
    if not (have("soffice") or have("libreoffice")):
        print("WARN: soffice 不可用，无法转 vsdx", file=sys.stderr)
        return False
    soffice = "soffice" if have("soffice") else "libreoffice"
    outdir = os.path.dirname(out_png) or "."
    r = sh([soffice, "--headless", "--convert-to", "pdf", "--outdir", outdir, vsdx])
    pdf = os.path.join(outdir, os.path.splitext(os.path.basename(vsdx))[0] + ".pdf")
    if r.returncode != 0 or not os.path.exists(pdf):
        print(f"WARN vsdx->pdf 失败: {r.stderr[:300]}", file=sys.stderr)
        return False
    if not have("pdftoppm"):
        print(f"NOTE: 已生成 PDF {pdf}；缺 pdftoppm 无法转 PNG，可手动转或直接引用 PDF", file=sys.stderr)
        return False
    prefix = out_png.replace(".png", "")
    sh(["pdftoppm", "-png", "-r", "150", "-f", str(page), "-l", str(page), pdf, prefix])
    # pdftoppm names like prefix-1.png / prefix-01.png
    for cand in (f"{prefix}-{page}.png", f"{prefix}-0{page}.png", f"{prefix}-{page:02d}.png"):
        if os.path.exists(cand):
            shutil.move(cand, out_png)
            return True
    return False


FENCE_RE = re.compile(r"```(mermaid|plantuml)\s*\n(.*?)```", re.DOTALL)


def process_markdown(md_path, outdir, rendered_md):
    os.makedirs(outdir, exist_ok=True)
    with open(md_path, encoding="utf-8") as f:
        text = f.read()

    counter = {"n": 0}

    def repl(m):
        kind, code = m.group(1), m.group(2)
        counter["n"] += 1
        h = hashlib.md5(code.encode()).hexdigest()[:8]
        png = os.path.join(outdir, f"diagram_{counter['n']:02d}_{h}.png")
        ok = render_mermaid(code, png) if kind == "mermaid" else render_plantuml(code, png)
        if ok:
            rel = os.path.relpath(png, os.path.dirname(os.path.abspath(rendered_md)) or ".")
            return f"![diagram_{counter['n']:02d}]({rel})\n"
        return m.group(0)  # leave the fence in place on failure

    new_text = FENCE_RE.sub(repl, text)
    with open(rendered_md, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"渲染 {counter['n']} 个图 → {outdir}")
    print(f"已生成可供 build_srs_docx 使用的 Markdown：{rendered_md}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md", nargs="?", help="SRS markdown file")
    ap.add_argument("--outdir", required=True, help="directory for rendered PNGs")
    ap.add_argument("--rendered-md", help="output markdown path (default: <md>.rendered.md)")
    ap.add_argument("--vsdx", help="convert a single vsdx to PNG and exit")
    ap.add_argument("--page", type=int, default=1, help="vsdx page to export")
    args = ap.parse_args()

    if args.vsdx:
        os.makedirs(args.outdir, exist_ok=True)
        out = os.path.join(args.outdir, os.path.splitext(os.path.basename(args.vsdx))[0] + ".png")
        ok = render_vsdx(args.vsdx, out, args.page)
        print(out if ok else "vsdx 转换未完成（见上方 WARN）")
        sys.exit(0 if ok else 1)

    if not args.md:
        ap.error("需要 <md> 或 --vsdx")
    rendered = args.rendered_md or (os.path.splitext(args.md)[0] + ".rendered.md")
    process_markdown(args.md, args.outdir, rendered)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Extract a clause index and normative-statement candidates from a (decrypted) standard PDF.

Output is WORKING MATERIAL for authoring a standard pack — it contains the standard's own wording, so it
is written to the project workspace only (never into the skill) and the workspace gets its own
`.gitignore`. Checklist items written from it must be paraphrased (see references/pack-authoring.md).

Why the custom text reconstruction: ISO PDFs from the web store are commonly rendered glyph-by-glyph
with custom fonts that carry no /Widths, so pypdf and pdftotext insert a space between every letter
("T h e p u r p o s e"). We take each glyph's x position through pypdf's visitor, learn each glyph's
normal advance statistically from the first pages, and insert a space only where the gap clearly
exceeds that advance. Residual artefacts (a split capital, a lost space after a font switch) remain
but do not hide clause numbers or the meaning of a sentence.

Outputs (in <out>/<stem>/):
  pages/p####.txt     reconstructed text per page (1-based page numbers = PDF page index + 1)
  clauses.json        [{"clause": "5.2.4.3", "title": "...", "page": 23}, ...] in document order
  norms.jsonl         one JSON per normative sentence: {"clause", "page", "kind": shall|shall-not|should|may, "text"}
  summary.json        counts per top-level clause and per kind

Usage:
  python3 extract_clauses.py <pdf> [<pdf> ...] --out <workspace>/extract
"""
import argparse
import collections
import json
import re
import statistics
import sys
from pathlib import Path

PUNCT = set(",.;:")
HEAD_RE = re.compile(r"^((?:\d+|[A-H])(?:\s?\.\s?\d+)*)\s*(?=[A-Z])(.{2,120})$")
NORM_RE = [("shall-not", re.compile(r"\bshall\s+not\b", re.I)), ("shall", re.compile(r"\bshall\b", re.I)),
           ("should", re.compile(r"\bshould\b", re.I))]


def page_glyphs(page):
    out = []

    def visit(text, cm, tm, fd, fs):
        if not text or not text.strip():
            return
        try:
            size = abs(float(fs) * float(cm[0])) or 1.0
            x = float(tm[4]) * float(cm[0]) + float(cm[4])
            y = float(tm[5]) * float(cm[3]) + float(cm[5])
        except (TypeError, ValueError):
            return
        font = str(fd.get("/BaseFont")) if fd else ""
        for ch in text.strip():
            out.append((y, x, ch, size, font))

    try:
        page.extract_text(visitor_text=visit)
    except Exception as exc:  # a broken content stream must not stop the whole document
        print(f"  [warn] page skipped: {exc}", file=sys.stderr)
    return out


def rows(glyphs):
    buckets = collections.defaultdict(list)
    for y, x, ch, s, f in glyphs:
        buckets[round(y)].append((x, ch, s, f))
    merged = []
    for k in sorted(buckets, reverse=True):
        if merged and abs(merged[-1][0] - k) <= 1:
            merged[-1][1].extend(buckets[k])
        else:
            merged.append([k, list(buckets[k])])
    return [sorted(r) for _, r in merged]


def learn_advances(sample_pages):
    adv = collections.defaultdict(list)
    for glyphs in sample_pages:
        for r in rows(glyphs):
            for a, b in zip(r, r[1:]):
                dx = b[0] - a[0]
                if dx > 0:
                    adv[(a[1], a[3], round(a[2], 1))].append(dx / a[2])
    table = {}
    for k, v in adv.items():
        if len(v) >= 8:
            table[k] = sorted(v)[int(len(v) * 0.3)]
        elif len(v) >= 2:
            table[k] = statistics.median(v)
    return table


def page_lines(glyphs, adv):
    lines = []
    for r in rows(glyphs):
        s = ""
        for i, (x, ch, sz, f) in enumerate(r):
            if i:
                px, pch, psz, pf = r[i - 1]
                w = 0.25 if pch in PUNCT else adv.get((pch, pf, round(psz, 1)), 0.5)
                th = 0.2 if pch.isupper() and (len(s) < 2 or not s[-2].isalpha()) else 0.09
                if (x - px) / psz - w > th:
                    s += " "
            s += ch
        lines.append(s.strip())
    return [l for l in lines if l]


def norm_clause(num):
    return re.sub(r"\s+", "", num)


def is_heading(line):
    if "...." in line or len(line) > 130:
        return None
    m = HEAD_RE.match(line)
    if not m:
        return None
    num, title = norm_clause(m.group(1)), m.group(2).strip()
    if not re.match(r"^(\d+(\.\d+)*|[A-H](\.\d+)+)$", num):
        return None
    if re.search(r"\b(shall|should)\b", title) or title.endswith((".", ",", ";")):
        return None
    if re.match(r"^\d+$", num) and int(num) > 20:      # page numbers / table values, not top clauses
        return None
    return num, title


def sentences(text):
    text = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.;:])\s+(?=[A-Z—\-a-z])", text) if s.strip()]


def extract(pdf, out_root, sample=40):
    import pypdf
    reader = pypdf.PdfReader(str(pdf))
    n = len(reader.pages)
    print(f"{pdf.name}: {n} pages")
    glyphs = [page_glyphs(p) for p in reader.pages]
    adv = learn_advances(glyphs[:min(sample, n)])
    out = out_root / re.sub(r"[^\w.-]+", "_", pdf.stem).strip("_")
    (out / "pages").mkdir(parents=True, exist_ok=True)

    clauses, norms = [], []
    current = {"clause": "front", "title": "", "page": 1}
    buf = []

    def flush():
        if not buf:
            return
        for s in sentences(" ".join(buf)):
            for kind, rx in NORM_RE:
                if rx.search(s):
                    norms.append({"clause": current["clause"], "page": current["page_now"], "kind": kind, "text": s})
                    break
        buf.clear()

    started = False
    for i, g in enumerate(glyphs):
        lines = page_lines(g, adv)
        (out / "pages" / f"p{i + 1:04d}.txt").write_text("\n".join(lines), encoding="utf-8")
        current["page_now"] = i + 1
        for line in lines:
            if line.startswith(("©", "ISO ", "BS ISO")) and len(line) < 60:
                continue
            h = is_heading(line)
            if h and (started or h[0] == "1"):
                started = True
                flush()
                current = {"clause": h[0], "title": h[1], "page": i + 1, "page_now": i + 1}
                clauses.append({"clause": h[0], "title": h[1], "page": i + 1})
                continue
            if started:
                buf.append(line)
        flush()  # sentences rarely span pages in tables; keep page attribution exact

    # drop TOC duplicates: keep the LAST occurrence of a clause number before the body restarts at "1"
    seen, body = {}, []
    for c in clauses:
        seen[c["clause"]] = c
    body = sorted(seen.values(), key=lambda c: (c["page"], clauses.index(c)))

    (out / "clauses.json").write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "norms.jsonl", "w", encoding="utf-8") as f:
        for n_ in norms:
            f.write(json.dumps(n_, ensure_ascii=False) + "\n")
    per_top = collections.Counter(n_["clause"].split(".")[0] for n_ in norms)
    kinds = collections.Counter(n_["kind"] for n_ in norms)
    summary = {"pdf": pdf.name, "pages": n, "clauses": len(body), "norms": len(norms),
               "by_kind": dict(kinds), "by_top_clause": dict(sorted(per_top.items(), key=lambda kv: kv[0]))}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  clauses={len(body)} norms={len(norms)} {dict(kinds)}")
    return summary


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    gi = a.out / ".gitignore"
    if not gi.exists():
        gi.write_text("# extracted standard text is licensed material: never commit\n*\n", encoding="utf-8")
    res = [extract(p, a.out) for p in a.pdfs]
    (a.out / "index.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

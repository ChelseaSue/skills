#!/usr/bin/env python3
"""Suppress Word's style-level auto-numbering on heading paragraphs of a .docx.

Why: the company templates (AU-QR-R&D-027/032) define the Heading 1/2/3 styles WITH a built-in
multilevel auto-number (numId). Our generated documents already write the section numbers into the
heading TEXT ("1.1 目标", "4.1 功能 制氧控制" …). So Word renders its own number on top — and because
the document title is itself a Heading 1, the auto-numbers are offset by one — yielding doubled /
mismatched numbers (e.g. a heading whose text says "4.1" shows Word's auto "3.1" beside it).

Since the authored text numbers are authoritative, the clean fix is to tell each heading paragraph
"no numbering" (an explicit numId=0 override), which cancels the inherited style list and leaves only
the numbers we wrote. This touches only paragraphs styled `Heading <n>` (the body headings we add),
not the template's own cover/TOC paragraphs.

Usage:
  python3 fix_heading_numbering.py <file.docx> [<file2.docx> ...]
"""
import re
import sys

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

HEADING_RE = re.compile(r"^Heading \d+$")


def suppress_numbering(paragraph):
    """Add an explicit no-numbering reference (numId=0) to a paragraph, overriding its style's list.
    numPr must sit right after pStyle in pPr, so insert it there rather than appending blindly."""
    pPr = paragraph._p.get_or_add_pPr()
    for existing in pPr.findall(qn("w:numPr")):
        pPr.remove(existing)
    numPr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl"); ilvl.set(qn("w:val"), "0")
    numId = OxmlElement("w:numId"); numId.set(qn("w:val"), "0")
    numPr.append(ilvl)
    numPr.append(numId)
    pStyle = pPr.find(qn("w:pStyle"))
    if pStyle is not None:
        pStyle.addnext(numPr)
    else:
        pPr.insert(0, numPr)


def fix(path):
    d = docx.Document(path)
    n = 0
    for p in d.paragraphs:
        name = p.style.name if p.style else ""
        if name and HEADING_RE.match(name):
            suppress_numbering(p)
            n += 1
    d.save(path)
    print(f"  {path}: 处理 {n} 个标题段，已取消样式自动编号")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for path in sys.argv[1:]:
        fix(path)


if __name__ == "__main__":
    main()

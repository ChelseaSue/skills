"""Resolve function-name aliases defined in glue/RTE headers.

Many layered embedded code bases route calls through mapping headers:
    #define HRTE_enuGetVlt   HADC_enuGetVltCur
The SAD dependency tables list the alias (HRTE_enuGetVlt) while the provider documents the real
name (HADC_enuGetVltCur). Without resolving the alias, an in-scope call looks like a call to the
outside world and the consumer relation is lost.
"""
from __future__ import annotations

import re
from pathlib import Path

DEFINE_RE = re.compile(r'^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*(?:/\*.*?\*/|//.*)?[ \t]*$', re.M)


def scan(dirs, known=None) -> dict:
    """alias -> final target, from object-like #defines that map one identifier to another.

    If `known` (set of real function names) is given, only chains ending in a known name are kept.
    """
    raw = {}
    seen_files = set()
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for h in d.rglob('*.h'):
            if h in seen_files:
                continue
            seen_files.add(h)
            try:
                txt = h.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            for a, b in DEFINE_RE.findall(txt):
                if a != b and not a.isupper() or (a.isupper() and not b.isupper()):
                    raw.setdefault(a, b)
    out = {}
    for a in raw:
        t, hops = a, 0
        while t in raw and hops < 8:
            t = raw[t]
            hops += 1
        if t != a and (known is None or t in known):
            out[a] = t
    return out

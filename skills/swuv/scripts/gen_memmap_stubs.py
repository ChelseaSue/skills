#!/usr/bin/env python3
"""Generate cppcheck-only replacements for AutoSAR/MCAL *_MemMap.h headers.

The real MemMap headers are included many times per translation unit and use
`#define <MOD>_START_SEC_*` / `#include "<Mod>_MemMap.h"` pairs that end in
`#error "no valid memory mapping symbol"` when no section symbol is defined.
gcc handles that protocol; cppcheck's preprocessor does not and aborts the
whole file on the #error, so the MISRA addon silently analyses nothing.

This tool copies each MemMap header's *version macros* (the including driver
header checks them) into an otherwise empty header of the same name.  Point
`static.extra_include_dirs` in ut_spec.json at the output directory;
run_static.py searches it before the real include dirs.  The Ceedling build
keeps using the real headers.

    python scripts/gen_memmap_stubs.py --root . --search <MCAL dir> \
        -o unit_test/<module>/static_support
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

VERSION_RE = re.compile(r'#define\s+\w+_(VENDOR_ID|AR_RELEASE_\w+_VERSION|SW_\w+_VERSION)\b')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, default=Path('.'))
    ap.add_argument('--search', action='append', required=True,
                    help='directory (relative to --root) to scan recursively; repeatable')
    ap.add_argument('-o', '--out', type=Path, required=True,
                    help='output directory (relative to --root) for the replacement headers')
    args = ap.parse_args()

    out = args.root / args.out
    out.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    for d in args.search:
        for f in sorted((args.root / d).rglob('*MemMap.h')):
            if f.name in seen:
                continue
            seen.add(f.name)
            text = f.read_text(encoding='utf-8', errors='replace')
            defs = [l for l in text.splitlines() if VERSION_RE.match(l)]
            body = ('/* cppcheck-only replacement of %s: keeps the version macros the\n'
                    '   including driver header checks and drops the #pragma section\n'
                    '   bookkeeping (cppcheck reports a false "#error no valid memory\n'
                    '   mapping symbol" on the real header). Not used by the Ceedling build. */\n'
                    % f.name) + '\n'.join(defs) + '\n'
            (out / f.name).write_text(body, encoding='utf-8', newline='\n')
    print(f'{len(seen)} MemMap replacement headers written to {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

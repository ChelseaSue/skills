#!/usr/bin/env python3
"""Convert legacy Office templates: .doc -> .docx, .xls -> .xlsx (formatting preserved).

Order of attempts:
  1. Office / WPS COM via PowerShell (Windows): Word.Application / Excel.Application,
     then WPS (KWPS.Application / KET.Application)
  2. LibreOffice:  soffice --headless --convert-to docx|xlsx
  3. Give up with a clear message (user re-saves the file as .docx/.xlsx once).

Converted files are cached: convert(src, cache_dir) returns the cached copy when it is newer
than the source.

Usage: convert.py <file.doc|file.xls> [-o out_dir]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORD_PROGIDS = ['Word.Application', 'KWPS.Application', 'WPS.Application']
EXCEL_PROGIDS = ['Excel.Application', 'KET.Application', 'ET.Application']

PS_WORD = r'''
$ErrorActionPreference = 'Stop'
$src = '{src}'; $dst = '{dst}'
foreach ($pid_ in @({progids})) {{
  try {{
    $app = New-Object -ComObject $pid_
    try {{ $app.Visible = $false }} catch {{}}
    try {{ $app.DisplayAlerts = 0 }} catch {{}}
    $doc = $app.Documents.Open($src, $false, $true)
    try {{ $doc.SaveAs2($dst, 16) }} catch {{ $doc.SaveAs($dst, 16) }}
    $doc.Close($false); $app.Quit()
    Write-Output "OK $pid_"; exit 0
  }} catch {{ try {{ $app.Quit() }} catch {{}} }}
}}
Write-Output 'FAIL'; exit 1
'''

PS_EXCEL = r'''
$ErrorActionPreference = 'Stop'
$src = '{src}'; $dst = '{dst}'
foreach ($pid_ in @({progids})) {{
  try {{
    $app = New-Object -ComObject $pid_
    try {{ $app.Visible = $false }} catch {{}}
    try {{ $app.DisplayAlerts = $false }} catch {{}}
    $wb = $app.Workbooks.Open($src, 0, $true)
    $wb.SaveAs($dst, 51)
    $wb.Close($false); $app.Quit()
    Write-Output "OK $pid_"; exit 0
  }} catch {{ try {{ $app.Quit() }} catch {{}} }}
}}
Write-Output 'FAIL'; exit 1
'''


def _ps_quote(p: Path) -> str:
    return str(p).replace("'", "''")


def _via_com(src: Path, dst: Path) -> bool:
    if sys.platform != 'win32' or not shutil.which('powershell'):
        return False
    word = src.suffix.lower() == '.doc'
    tpl = PS_WORD if word else PS_EXCEL
    progids = ','.join(f"'{p}'" for p in (WORD_PROGIDS if word else EXCEL_PROGIDS))
    script = tpl.format(src=_ps_quote(src), dst=_ps_quote(dst), progids=progids)
    with tempfile.NamedTemporaryFile('w', suffix='.ps1', delete=False, encoding='utf-8-sig') as f:
        f.write(script)
        ps1 = f.name
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps1],
                           capture_output=True, text=True, timeout=300)
        return r.returncode == 0 and dst.exists()
    except Exception:
        return False
    finally:
        Path(ps1).unlink(missing_ok=True)


def _via_soffice(src: Path, dst: Path) -> bool:
    exe = shutil.which('soffice') or shutil.which('libreoffice')
    for cand in (r'C:\Program Files\LibreOffice\program\soffice.exe',
                 r'C:\Program Files (x86)\LibreOffice\program\soffice.exe'):
        if not exe and Path(cand).exists():
            exe = cand
    if not exe:
        return False
    fmt = 'docx' if src.suffix.lower() == '.doc' else 'xlsx'
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([exe, '--headless', '--convert-to', fmt, '--outdir', td, str(src)],
                           capture_output=True, text=True, timeout=300)
        out = Path(td) / (src.stem + '.' + fmt)
        if r.returncode == 0 and out.exists():
            shutil.move(str(out), dst)
            return True
    return False


def convert(src: str | Path, out_dir: str | Path | None = None) -> Path:
    src = Path(src).resolve()
    ext = src.suffix.lower()
    if ext in ('.docx', '.xlsx', '.xlsm'):
        return src
    if ext not in ('.doc', '.xls'):
        raise ValueError(f'cannot convert {src.name}')
    out_dir = Path(out_dir).resolve() if out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (src.stem + ('.docx' if ext == '.doc' else '.xlsx'))
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    if dst.exists():
        dst.unlink()
    if _via_com(src, dst) or _via_soffice(src, dst):
        return dst
    raise RuntimeError(
        f'无法自动转换 {src.name}：本机没有可用的 Office/WPS COM 或 LibreOffice。'
        f'请用 Word/Excel/WPS 打开它另存为 {dst.suffix}，放到 {out_dir} 后重试。')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src', type=Path)
    ap.add_argument('-o', '--out-dir', type=Path)
    a = ap.parse_args()
    print(convert(a.src, a.out_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())

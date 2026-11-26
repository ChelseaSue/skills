"""Shared helpers for the swit scripts (stdlib only).

Everything project-specific lives in swit_project.json; this module only knows how to
load it, find templates by document number and read/write JSON consistently.
"""
from __future__ import annotations

import copy
import glob
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / 'assets'

CASE_ID_RE = re.compile(r'^SWIT-\d{5}$')


def utf8_console() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


def load_json(path: str | Path, default=None):
    p = Path(path)
    if not p.exists():
        if default is not None:
            return copy.deepcopy(default)
        raise FileNotFoundError(p)
    with p.open('r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path: str | Path, data) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, p)
    return p


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k.startswith('_comment'):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def norm(s) -> str:
    """Normalise text for matching: NFKC, collapse whitespace, strip."""
    if s is None:
        return ''
    s = unicodedata.normalize('NFKC', str(s))
    return re.sub(r'\s+', ' ', s).strip()


def content_hash(obj) -> str:
    txt = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(txt.encode('utf-8')).hexdigest()[:16]


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- project config

class Project:
    """swit_project.json + resolved workspace paths.

    Relative paths inside the config resolve against the config file's directory.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.root = self.path.parent
        defaults = load_json(ASSETS / 'swit_project.defaults.json')
        self.cfg = deep_merge(defaults, load_json(self.path))
        ws = self.cfg.get('workspace') or 'swit_ws'
        self.ws = self.resolve(ws)

    # ---- paths
    def resolve(self, p: str | Path | None) -> Path | None:
        if p in (None, ''):
            return None
        p = Path(os.path.expandvars(os.path.expanduser(str(p))))
        return p if p.is_absolute() else (self.root / p).resolve()

    def wsp(self, *parts: str) -> Path:
        return self.ws.joinpath(*parts)

    def get(self, dotted: str, default=None):
        cur = self.cfg
        for k in dotted.split('.'):
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    # ---- templates
    def template(self, key: str) -> Path:
        """Locate a template by its document-number glob (e.g. 'AU-QR-R&D-052*').

        Highest version wins when several revisions sit in the folder.
        """
        tdir = self.resolve(self.get('templates.dir'))
        pattern = self.get(f'templates.patterns.{key}')
        if not tdir or not pattern:
            raise KeyError(f'templates.dir / templates.patterns.{key} not configured')
        hits = [Path(h) for h in glob.glob(str(tdir / pattern)) if not Path(h).name.startswith('~$')]
        if not hits:
            raise FileNotFoundError(f'no template matching {pattern} in {tdir}')
        return sorted(hits, key=_version_key)[-1]

    # ---- language
    def lang(self) -> str:
        return self.get('content_language', 'en')

    def text(self, zh: str, en: str) -> str:
        lang = self.lang()
        if lang == 'zh':
            return zh
        if lang == 'bilingual':
            return f'{zh} {en}'
        return en


def _version_key(p: Path):
    m = re.search(r'V(\d+)(?:\.(\d+))?(?:\.(\d+))?', p.name, re.I)
    if not m:
        return (0, 0, 0, p.stat().st_mtime)
    return tuple(int(x or 0) for x in m.groups()) + (p.stat().st_mtime,)


def pick(row: dict, *keys: str, default: str = '') -> str:
    for k in keys:
        if k in row and row[k] not in (None, ''):
            return row[k]
    return default


def die(msg: str, code: int = 2):
    print(f'error: {msg}', file=sys.stderr)
    sys.exit(code)

"""Parse PlantUML / Mermaid diagram source into sequence messages or state transitions.

parse(lang, text) -> {"type": "sequence"|"state"|"unknown",
                      "participants": [{"alias","name"}], "messages": [{"from","to","label","n"}],
                      "states": [...], "transitions": [{"from","to","label","n"}]}
"""
from __future__ import annotations

import re

_PU_PART = re.compile(r'^\s*(participant|actor|boundary|control|entity|database|collections|queue|component)\s+'
                      r'(?:"([^"]+)"|(\S+))(?:\s+as\s+(\w+))?', re.I)
_PU_MSG = re.compile(r'^\s*("?[\w一-鿿 .\[\]]+?"?)\s*([-.]+>>?|<<?[-.]+|->x|-\\\\|-//?)\s*'
                     r'("?[\w一-鿿 .\[\]]+?"?)\s*(?::\s*(.*))?$')
_PU_STATE_T = re.compile(r'^\s*(\[\*\]|[\w一-鿿.]+)\s*-+(?:left|right|up|down)?-*>\s*(\[\*\]|[\w一-鿿.]+)\s*(?::\s*(.*))?$')
_PU_STATE_DECL = re.compile(r'^\s*state\s+(?:"([^"]+)"\s+as\s+(\w+)|(\w+))', re.I)

_MM_PART = re.compile(r'^\s*(participant|actor)\s+(\S+)(?:\s+as\s+(.+))?$', re.I)
_MM_MSG = re.compile(r'^\s*([^\s:>-]+)\s*(-{1,2}>>?|-{1,2}x|-{1,2}\))\s*([^\s:]+)\s*:\s*(.*)$')
_MM_STATE_T = re.compile(r'^\s*(\[\*\]|[\w一-鿿.]+)\s*-->\s*(\[\*\]|[\w一-鿿.]+)\s*(?::\s*(.*))?$')

_SKIP = re.compile(r'^\s*(@startuml|@enduml|title|skinparam|autonumber|note|end note|hide|show|activate|deactivate|'
                   r'alt|else|end|opt|loop|par|group|ref|box|legend|endlegend|==|\.\.\.|\|\|\||return|'
                   r'rect|critical|break|%%|\')', re.I)


def _clean(s: str) -> str:
    return (s or '').strip().strip('"').strip()


def parse(lang: str, text: str) -> dict:
    lang = (lang or '').lower()
    lines = text.splitlines()
    body = '\n'.join(lines)
    if lang == 'mermaid':
        if re.search(r'^\s*stateDiagram', body, re.M):
            return _mermaid_state(lines)
        if re.search(r'^\s*sequenceDiagram', body, re.M):
            return _mermaid_seq(lines)
        return {'type': 'unknown'}
    # plantuml: decide by content
    if re.search(r'^\s*state\s', body, re.M | re.I) or re.search(r'\[\*\]\s*-+>', body):
        return _pu_state(lines)
    return _pu_seq(lines)


def _pu_seq(lines):
    parts, alias, msgs = [], {}, []
    for ln in lines:
        m = _PU_PART.match(ln)
        if m:
            name = _clean(m.group(2) or m.group(3))
            al = m.group(4) or name
            alias[al] = name
            parts.append({'alias': al, 'name': name})
            continue
        if _SKIP.match(ln):
            continue
        m = _PU_MSG.match(ln)
        if m:
            a, arrow, b, label = _clean(m.group(1)), m.group(2), _clean(m.group(3)), _clean(m.group(4))
            if arrow.startswith('<'):
                a, b = b, a
            msgs.append({'from': alias.get(a, a), 'to': alias.get(b, b), 'label': label, 'n': len(msgs) + 1,
                         'reply': '--' in arrow or '..' in arrow})
    return {'type': 'sequence', 'participants': parts, 'messages': msgs}


def _pu_state(lines):
    states, alias, trans = [], {}, []
    for ln in lines:
        m = _PU_STATE_DECL.match(ln)
        if m:
            name = m.group(1) or m.group(3)
            al = m.group(2) or m.group(3)
            alias[al] = name
            if name not in states:
                states.append(name)
            continue
        m = _PU_STATE_T.match(ln)
        if m:
            a, b = alias.get(m.group(1), m.group(1)), alias.get(m.group(2), m.group(2))
            for s in (a, b):
                if s != '[*]' and s not in states:
                    states.append(s)
            trans.append({'from': a, 'to': b, 'label': _clean(m.group(3)), 'n': len(trans) + 1})
    return {'type': 'state', 'states': states, 'transitions': trans}


def _mermaid_seq(lines):
    parts, alias, msgs = [], {}, []
    for ln in lines:
        m = _MM_PART.match(ln)
        if m:
            al = m.group(2)
            name = _clean(m.group(3) or al)
            alias[al] = name
            parts.append({'alias': al, 'name': name})
            continue
        m = _MM_MSG.match(ln)
        if m:
            a, arrow, b, label = m.group(1), m.group(2), m.group(3), _clean(m.group(4))
            msgs.append({'from': alias.get(a, a), 'to': alias.get(b, b), 'label': label, 'n': len(msgs) + 1,
                         'reply': arrow.startswith('--')})
    return {'type': 'sequence', 'participants': parts, 'messages': msgs}


def _mermaid_state(lines):
    states, trans = [], []
    for ln in lines:
        m = _MM_STATE_T.match(ln)
        if m:
            a, b = m.group(1), m.group(2)
            for s in (a, b):
                if s != '[*]' and s not in states:
                    states.append(s)
            trans.append({'from': a, 'to': b, 'label': _clean(m.group(3)), 'n': len(trans) + 1})
    return {'type': 'state', 'states': states, 'transitions': trans}

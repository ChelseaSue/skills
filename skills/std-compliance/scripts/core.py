"""Shared model for std-compliance: project config, standard packs, applicability, verdict merge.

Nothing here knows about a particular project or standard: projects describe themselves in
std_project.json, standards live in packs/<pack>/ (pack.json + checklist.json + rules/ + host/).
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
PACKS = SKILL / "packs"
sys.path.insert(0, str(Path(__file__).resolve().parent))

PASS, FAIL, NA, TARGET, NOTRUN = "符合", "不符合", "不适用", "转SWE.6/HIL", "未检查"
VERDICTS = (PASS, FAIL, NA, TARGET, NOTRUN)
METHODS = ("config", "design", "host-test", "target")


def load_json(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


class Project:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.cfg = load_json(self.path)
        if self.cfg is None:
            raise SystemExit(f"project config not found: {self.path}")
        self.base = self.path.parent

    def get(self, dotted, default=None):
        cur = self.cfg
        for k in dotted.split("."):
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def p(self, rel):
        """Resolve a path from the config relative to the config file."""
        if rel is None:
            return None
        q = Path(rel)
        return q if q.is_absolute() else (self.base / q).resolve()

    @property
    def ws(self):
        return self.p(self.get("workspace", "std_ws"))

    def wsp(self, *parts):
        return self.ws.joinpath(*parts)

    @property
    def node(self):
        return self.get("node", {})


# --------------------------------------------------------------------------- packs

def load_pack(pack_id):
    d = PACKS / pack_id
    pack = load_json(d / "pack.json")
    if pack is None:
        raise SystemExit(f"unknown pack: {pack_id}")
    items = []
    sources = ([d / "checklist.json"] if (d / "checklist.json").exists() else []) + sorted((d / "items").glob("*.json"))
    for f in sources:                                  # one file per standard keeps reviews and diffs small
        data = load_json(f, default={"items": []})
        items += data.get("items", []) if isinstance(data, dict) else data
    pack["dir"] = str(d)
    pack["items"] = items
    return pack


def load_items(prj, extra_checklists=()):
    items = []
    for pid in prj.get("packs", []):
        pack = load_pack(pid)
        for it in pack["items"]:
            it = dict(it)
            it["pack"] = pid
            items.append(it)
    for cl in extra_checklists:                      # evals / fixtures
        data = load_json(cl, default=[])
        for it in (data.get("items", data) if isinstance(data, dict) else data):
            it = dict(it)
            it.setdefault("pack", "fixture")
            items.append(it)
    ids = [i["id"] for i in items]
    dup = {x for x in ids if ids.count(x) > 1}
    if dup:
        raise SystemExit(f"duplicate checklist ids: {sorted(dup)}")
    return items


def pack_standards(prj):
    out = {}
    for pid in prj.get("packs", []):
        for s in load_pack(pid)["standards"]:
            out[s["key"]] = s
    return out


# --------------------------------------------------------------------------- applicability

ROLE_ALIASES = {"master": "commander", "slave": "responder"}


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def node_sids(prj):
    sids = prj.node.get("supported_sids", "auto")
    if sids == "auto":
        cache = load_json(prj.wsp("inputs", "supported_sids.json"))
        if cache is None:
            return None
        sids = cache
    return {int(s, 16) if isinstance(s, str) else int(s) for s in sids}


def applicability(item, prj, standards):
    """Return (applicable: bool, reason: str)."""
    ov = prj.get("applicability_overrides", {}).get(item["id"])
    if ov is not None:
        return bool(ov.get("applicable")), ov.get("reason", "项目配置覆盖")
    node = prj.node
    buses = set(_as_list(node.get("bus")))
    feats = set(_as_list(node.get("features")))
    roles = {ROLE_ALIASES.get(r, r) for r in _as_list(node.get("lin_role")) + _as_list(node.get("can_role"))
             + _as_list(node.get("uds_role"))}
    std = standards.get(item.get("standard_key") or item.get("standard", "").replace(" ", ""), {})
    conds = [std.get("applies_to", {}), item.get("applicability", {})]
    for c in conds:
        b = set(_as_list(c.get("bus")))
        if b and not (b & buses):
            return False, f"总线不适用（条款面向 {'/'.join(sorted(b))}，本节点 {'/'.join(sorted(buses)) or '未配置'}）"
        r = {ROLE_ALIASES.get(x, x) for x in _as_list(c.get("role"))}
        if r and "any" not in r and not (r & roles):
            return False, f"节点角色不适用（条款面向 {'/'.join(sorted(r))}）"
        f = set(_as_list(c.get("features")))
        if f and not (f & feats):
            return False, f"功能未启用（需要 {'/'.join(sorted(f))}）"
    sid = _as_list(item.get("applicability", {}).get("sid"))
    if sid:
        have = node_sids(prj)
        if have is None:
            return True, "服务适用性待定：未取得支持的 SID 清单（先运行 static 读取 Dcm 配置）"
        want = {int(s, 16) if isinstance(s, str) else int(s) for s in sid}
        if not (want & have):
            return False, f"本节点未支持服务 {', '.join(f'0x{s:02X}' for s in sorted(want))}"
    return True, ""


# --------------------------------------------------------------------------- static rules

class Ctx:
    """What a rule sees. Inputs are parsed lazily so a rule only pays for what it reads."""

    def __init__(self, prj):
        self.prj = prj
        self._ldf = self._arxml = self._sad = None

    @property
    def node(self):
        return self.prj.node

    @property
    def ldf(self):
        if self._ldf is None:
            from parsers import ldf as L
            files = [self.prj.p(f) for f in _as_list(self.prj.get("inputs.ldf"))]
            self._ldf = L.load(files[0]) if files and files[0].exists() else {}
        return self._ldf

    @property
    def ldf_node(self):
        """This ECU's name in the LDF (node.ldf_name) and its Node_attributes."""
        name = self.node.get("ldf_name")
        return name, (self.ldf.get("node_attributes", {}).get(name) if name else None)

    @property
    def arxml(self):
        if self._arxml is None:
            from parsers import arxml as A
            files = [self.prj.p(f) for f in _as_list(self.prj.get("inputs.arxml"))]
            self._arxml = A.load([f for f in files if f.exists()])
        return self._arxml

    @property
    def sad(self):
        if self._sad is None:
            p = self.prj.p(self.prj.get("inputs.sad"))
            self._sad = p.read_text(encoding="utf-8", errors="ignore") if p and p.exists() else ""
        return self._sad

    def param(self, name, module=None, as_num=True):
        from parsers import arxml as A
        vals = A.param_values(self.arxml, name, module)
        return [A.num(v) for v in vals] if as_num else vals


def load_rules(prj, extra_dirs=()):
    rules = {}
    dirs = [PACKS / pid / "rules" for pid in prj.get("packs", [])] + [Path(d) for d in extra_dirs]
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.py")):
            spec = importlib.util.spec_from_file_location(f"stdrule_{d.parent.name}_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for k, fn in getattr(mod, "RULES", {}).items():
                if k in rules:
                    raise SystemExit(f"rule {k} defined twice ({f})")
                rules[k] = fn
    return rules


def result(verdict, evidence, **details):
    if verdict not in (PASS, FAIL, NOTRUN):
        raise ValueError(f"rule verdict must be {PASS}/{FAIL}/{NOTRUN}, got {verdict}")
    return {"verdict": verdict, "evidence": evidence, "details": details}


# --------------------------------------------------------------------------- host markers

SKELETON_MARK = 'TEST_IGNORE_MESSAGE("not implemented: '
MARK_RE = re.compile(r"/\*\s*STD:\s*([^*]+?)\s*\*/")
TEST_RE = re.compile(r"^\s*void\s+(test\w+)\s*\(\s*void\s*\)", re.M)


def test_marks(test_dir):
    """{file_stem::test_name: [item ids]} plus unmarked tests (marker governs following tests)."""
    out, unmarked = {}, []
    for f in sorted(Path(test_dir).glob("test_*.c")):
        text = f.read_text(encoding="utf-8", errors="ignore")
        if SKELETON_MARK in text:          # untouched skeleton: not a test yet
            continue
        events = [(m.start(), "mark", [x.strip() for x in re.split(r"[,\s]+", m.group(1)) if x.strip()])
                  for m in MARK_RE.finditer(text)]
        events += [(m.start(), "test", m.group(1)) for m in TEST_RE.finditer(text)]
        cur = None
        for _, kind, val in sorted(events, key=lambda e: e[0]):
            if kind == "mark":
                cur = val
            elif cur:
                out[f"{f.stem}::{val}"] = cur
            else:
                unmarked.append(f"{f.stem}::{val}")
    return out, unmarked


def ceedling_results(host_dir):
    res = {}
    for sub in ("gcov", "test"):
        rd = Path(host_dir) / "build" / sub / "results"
        if not rd.is_dir():
            continue
        for f in rd.glob("*.*"):
            if f.suffix not in (".pass", ".fail"):
                continue
            section, cur = None, None
            for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"^:(successes|failures|ignores):", ln)
                if m:
                    section = m.group(1)
                    continue
                if re.match(r"^:\w+:", ln):
                    section = None
                if section is None:
                    continue
                m = re.match(r"^\s*-\s*:test:\s*(\S+)", ln)
                if m:
                    cur = {"status": {"successes": "pass", "failures": "fail", "ignores": "ignored"}[section],
                           "message": ""}
                    res.setdefault(f"{f.stem}::{m.group(1)}", cur)
                    continue
                m = re.match(r"^\s*:message:\s*'?(.*?)'?\s*$", ln)
                if m and cur is not None:
                    cur["message"] = m.group(1)
        if res:
            break
    return res


# --------------------------------------------------------------------------- verdict merge

def merge_verdicts(prj, items, standards):
    static = load_json(prj.wsp("results", "static.json"), default={})
    host = load_json(prj.wsp("results", "host.json"), default={})
    reviews = prj.get("reviews", {})
    notes = prj.get("notes", {})          # per-item root cause / fix / open question; appended, never changes a verdict
    rows = []
    for it in items:
        ok, why = applicability(it, prj, standards)
        m = it.get("method")
        row = {"item": it, "applicable": ok, "na_reason": why, "verdict": NOTRUN, "evidence": "", "source": ""}
        if not ok:
            row.update(verdict=NA, evidence=why, source="applicability")
        elif m == "target":
            row.update(verdict=TARGET, evidence=it.get("target_note", "需真实总线/时序，转 SWE.6、HIL 或一致性测试"),
                       source="method")
        elif it["id"] in reviews:
            r = reviews[it["id"]]
            row.update(verdict=r.get("verdict", NOTRUN), evidence=f"{r.get('evidence', '')}（{r.get('by', '?')} {r.get('date', '')}）",
                       source="review")
        elif m == "config" and it["id"] in static:
            r = static[it["id"]]
            row.update(verdict=r["verdict"], evidence=r["evidence"], source="static")
        elif m == "host-test" and it["id"] in host:
            r = host[it["id"]]
            row.update(verdict=r["verdict"], evidence=r["evidence"], source="host")
        else:
            row["evidence"] = {"config": "未有静态规则或输入缺失", "design": "未记录评审结论（std_project.json reviews）",
                               "host-test": "未执行宿主机测试"}.get(m, "方法未定义")
        if it["id"] in notes and ok:
            row["evidence"] = f"{row['evidence']}；备注：{notes[it['id']]}"
        rows.append(row)
    return rows

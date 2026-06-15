# 跨项目模块移植/复用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 code-generator 生成的模块加 `reuse`（reusable/project-specific）分类，对 reusable 模块自动产出自包含契约头与移植说明，并用一条机检门禁挡住 reusable→project-specific 的反向依赖。

**Architecture:** 扩展现有文件（不新增独立脚本）。`reuse` 字段进 module_spec（单一真源）；模块名即文件 stem，所以分类按 stem 解析，无需复制 scaffold 的目录放置逻辑。scaffold_tree.py 对 reusable 模块多生成 `<Module>_contract.h` + `<Module>_port.md`；check_layering.py 新增可选 `--modules`，据此对每条 `#include` 追加 reusable→project-specific 检查。

**Tech Stack:** Python 3（标准库，无第三方）；stdlib `unittest`（环境无 pytest）；Markdown 规则/模板文档。

参考 spec：[2026-06-15-cross-project-module-reuse-design.md](../specs/2026-06-15-cross-project-module-reuse-design.md)

---

## File Structure

- `assets/module_spec.schema.json` — module 加 `reuse` 字段定义
- `assets/module_spec.example.json` — 示例标注几个 reusable / project-specific
- `scripts/scaffold_tree.py` — 默认分类 + reusable 模块多生成 contract.h/port.md
- `scripts/check_layering.py` — 可选 `--modules`，追加 REUSE 反向依赖门禁
- `tests/test_scaffold_reuse.py` — scaffold 行为测试（新建）
- `tests/test_check_reuse.py` — 门禁行为测试（新建）
- `references/layering-rules.md` — 新增 §8
- `references/module-templates.md` — contract.h / port.md 模板
- `references/conformance-checklist.md` — 跨项目移植核查组
- `SKILL.md` — 点出 reuse 分类与门禁

---

## Task 1: module_spec 加 `reuse` 字段（schema + 示例）

**Files:**
- Modify: `assets/module_spec.schema.json`（module 的 properties 内）
- Modify: `assets/module_spec.example.json`

- [ ] **Step 1: 给 schema 加 `reuse` 属性**

在 `assets/module_spec.schema.json` 里 module 的 `properties` 内，`"layer"` 属性之后插入：

```json
          "reuse": {"type": "string", "enum": ["reusable", "project-specific"], "description": "可选：跨项目复用分类。缺省按层默认（App→project-specific，其它层→reusable）。reusable 模块会自动生成 <Module>_contract.h 与 <Module>_port.md，且不得 #include 任何 project-specific 模块的头（门禁硬挡）"},
```

- [ ] **Step 2: 在示例里标注分类**

在 `assets/module_spec.example.json` 中：给 `"name": "MainOrchestrator"` 模块对象加一行 `"reuse": "project-specific",`（放在它的 `"layer": "App",` 之后）；给 `"name": "ParameterNvm"` 模块对象加一行 `"reuse": "reusable",`（放在它的 `"layer": "Service",` 之后）。

- [ ] **Step 3: 校验两个 JSON 仍合法**

Run: `python3 -c "import json; json.load(open('assets/module_spec.schema.json')); json.load(open('assets/module_spec.example.json')); print('ok')"`
Expected: 输出 `ok`

- [ ] **Step 4: Commit**

```bash
git add assets/module_spec.schema.json assets/module_spec.example.json
git commit -m "feat: add reuse classification field to module_spec"
```

---

## Task 2: scaffold_tree 默认分类 + 为 reusable 生成 contract.h/port.md

**Files:**
- Modify: `scripts/scaffold_tree.py`
- Test: `tests/test_scaffold_reuse.py`（新建）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_scaffold_reuse.py`：

```python
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAFFOLD = os.path.join(ROOT, "scripts", "scaffold_tree.py")

LAYERS = {
    "layers": ["App", "Service", "Hal", "Mcal"],
    "path_map": {"Source/App": "App", "Source/Service": "Service",
                 "Source/Hal": "Hal", "Source/Mcal": "Mcal"},
    "file_prefix": {},
}
SPEC = {"project": "T", "modules": [
    {"name": "FocCore", "layer": "Service", "reuse": "reusable"},
    {"name": "ProjOrch", "layer": "App", "reuse": "project-specific"},
    {"name": "ParamSvc", "layer": "Service"},  # 缺省 -> reusable
]}


class ScaffoldReuseTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.layers = os.path.join(self.d, "layers.json")
        self.spec = os.path.join(self.d, "spec.json")
        self.out = os.path.join(self.d, "code")
        json.dump(LAYERS, open(self.layers, "w"))
        json.dump(SPEC, open(self.spec, "w"))
        subprocess.run([sys.executable, SCAFFOLD, "--spec", self.spec,
                        "--layers", self.layers, "--out", self.out], check=True)

    def _exists(self, *parts):
        return os.path.exists(os.path.join(self.out, *parts))

    def test_reusable_gets_contract_and_port(self):
        self.assertTrue(self._exists("Source/Service", "FocCore", "FocCore_contract.h"))
        self.assertTrue(self._exists("Source/Service", "FocCore", "FocCore_port.md"))

    def test_default_service_is_reusable(self):
        self.assertTrue(self._exists("Source/Service", "ParamSvc", "ParamSvc_contract.h"))

    def test_project_specific_has_no_contract_or_port(self):
        self.assertFalse(self._exists("Source/App", "ProjOrch", "ProjOrch_contract.h"))
        self.assertFalse(self._exists("Source/App", "ProjOrch", "ProjOrch_port.md"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_scaffold_reuse -v`
Expected: FAIL —— `FocCore_contract.h` 不存在（scaffold 还没生成 contract/port）。

- [ ] **Step 3: 在 scaffold_tree.py 加默认分类与生成逻辑**

在 `scripts/scaffold_tree.py` 的 `guard()` 函数之后、`header_text()` 之前插入：

```python
_DEFAULT_REUSE = {"App": "project-specific"}


def reuse_of(m):
    """模块的复用分类：显式 reuse 字段优先，否则按层默认（App→project-specific，其它→reusable）。"""
    return m.get("reuse") or _DEFAULT_REUSE.get(m["layer"], "reusable")


def contract_text(m):
    mod = m["name"]
    g = guard(mod + "_contract")
    lines = ["/*!", f"** @file    {mod}_contract.h",
             f"** @brief   {mod} 自包含横切契约：本模块用到的信号/事件 ID、Cfg 默认、返回码扩展集中于此，",
             "**          整个模块文件夹可整体移植。只依赖稳定横切（IF_Types 返回码、Bus 注册 API），",
             "**          不直接引用其它项目专属的全局 ID。",
             "*/", f"#ifndef {g}", f"#define {g}", "", '#include "IF_Types.h"', "",
             "/* TBD: 本模块自有的信号/事件 ID 枚举、Cfg 默认值、返回码扩展。移植时只动这里与 Impl/Cfg。 */", "",
             f"#endif /* {g} */"]
    return "\n".join(lines) + "\n"


def port_md_text(m, today):
    mod = m["name"]
    impls = ", ".join(m.get("implements", [])) or "（待补充需求 ID）"
    return f"""# {mod} 移植清单（参考说明，自动生成）

## 1. 模块身份
- 层：{m['layer']}　复用类型：reusable　对应 SRS 需求 ID（旧项目）：{impls}

## 2. 依赖
- 自带：{mod}_contract.h、{mod}.h/.c、本模块单测
- 需新项目提供：稳定 IF_Types 返回码、Bus 注册 API（若用）

## 3. 需重新适配的接驳点（移植时逐条改）
- [ ] Impl/ → 绑定新项目 MCAL/SDK（仅 HAL 模块）
- [ ] {mod}_Cfg.h → 新项目板级/通道/参数
- [ ] 信号/事件 ID → 在新项目登记 {mod}_contract.h 里的 ID
- [ ] 文件名/符号前缀 → 若新项目 file_prefix 不同则改

## 4. 追溯重映射
- 旧 SRS ID（{impls}）→ 新项目 SRS ID：TBD（移植时回填）

## 5. 主机单测
- 如何脱离硬件跑本模块单测（打桩点说明）：TBD
"""
```

- [ ] **Step 4: 在生成循环里写出 contract.h/port.md**

在 `scripts/scaffold_tree.py` 的 `main()` 内，找到构造 `files = { ... }` 字典那一段（约在 `files = {` 到 `}` 之间，含 `{mod}.h`/`{mod}_Cfg.h`/`{mod}.c` 三项）。在 `files` 字典赋值语句之后、`planned.append((mod, files))` 之前插入：

```python
        if reuse_of(m) == "reusable":
            files[os.path.join(out, hdr_dir, f"{mod}_contract.h")] = contract_text(m)
            files[os.path.join(out, hdr_dir, f"{mod}_port.md")] = port_md_text(m, today)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python3 -m unittest tests.test_scaffold_reuse -v`
Expected: PASS（3 个测试全过）

- [ ] **Step 6: Commit**

```bash
git add scripts/scaffold_tree.py tests/test_scaffold_reuse.py
git commit -m "feat: scaffold contract.h and port.md for reusable modules"
```

---

## Task 3: check_layering 追加 reusable→project-specific 门禁

**Files:**
- Modify: `scripts/check_layering.py`
- Test: `tests/test_check_reuse.py`（新建）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_check_reuse.py`：

```python
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "scripts", "check_layering.py")

LAYERS = {
    "layers": ["App", "Service", "Hal", "Mcal"],
    "path_map": {"Source/App": "App", "Source/Service": "Service",
                 "Source/Hal": "Hal", "Source/Mcal": "Mcal"},
    "file_prefix": {},
}
SPEC = {"modules": [
    {"name": "FocCore", "layer": "Service", "reuse": "reusable"},
    {"name": "ProjOrch", "layer": "Service", "reuse": "project-specific"},
]}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)


class CheckReuseTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.layers = os.path.join(self.d, "layers.json")
        self.spec = os.path.join(self.d, "spec.json")
        self.code = os.path.join(self.d, "code")
        json.dump(LAYERS, open(self.layers, "w"))
        json.dump(SPEC, open(self.spec, "w"))
        write(os.path.join(self.code, "Source/Service/ProjOrch/ProjOrch.h"), "#ifndef P\n#define P\n#endif\n")

    def _run(self, c_body):
        write(os.path.join(self.code, "Source/Service/FocCore/FocCore.c"), c_body)
        return subprocess.run(
            [sys.executable, CHECK, "--root", self.code, "--layers", self.layers,
             "--modules", self.spec, "--json"], capture_output=True, text=True)

    def test_reusable_including_project_specific_is_violation(self):
        r = self._run('#include "ProjOrch.h"\n')
        self.assertEqual(r.returncode, 1)
        data = json.loads(r.stdout)
        kinds = [v["kind"] for v in data["violations"]]
        self.assertIn("REUSE", kinds)

    def test_reusable_including_reusable_is_ok(self):
        write(os.path.join(self.code, "Source/Service/Other/Other.h"), "#ifndef O\n#define O\n#endif\n")
        # Other 未在 spec -> 不分类 -> 不触发 REUSE
        r = self._run('#include "Other.h"\n')
        kinds = [v["kind"] for v in json.loads(r.stdout)["violations"]]
        self.assertNotIn("REUSE", kinds)

    def test_no_modules_arg_keeps_old_behavior(self):
        write(os.path.join(self.code, "Source/Service/FocCore/FocCore.c"), '#include "ProjOrch.h"\n')
        r = subprocess.run(
            [sys.executable, CHECK, "--root", self.code, "--layers", self.layers, "--json"],
            capture_output=True, text=True)
        kinds = [v["kind"] for v in json.loads(r.stdout)["violations"]]
        self.assertNotIn("REUSE", kinds)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_check_reuse -v`
Expected: FAIL —— `test_reusable_including_project_specific_is_violation` 失败（returncode 0，无 REUSE，因为 `--modules` 尚未支持）。

- [ ] **Step 3: 加 `--modules` 解析与 reuse 索引构建**

在 `scripts/check_layering.py` 的 `main()` 里，`ap.add_argument("--json", action="store_true")` 之后插入：

```python
    ap.add_argument("--modules", help="可选 module_spec.json：启用 reusable→project-specific 反向依赖门禁")
```

然后在 `hdr_index = build_header_index(root)` 这一行之后插入：

```python
    reuse_by_module = {}
    if args.modules:
        with open(args.modules, encoding="utf-8") as mf:
            spec = json.load(mf)
        file_prefix = cfg.get("file_prefix", {})
        default_reuse = {"App": "project-specific"}
        for m in spec.get("modules", []):
            name = m["name"]
            pfx = file_prefix.get(m["layer"], "")
            if pfx and not name.startswith(pfx):
                name = pfx + name
            reuse_by_module[name] = m.get("reuse") or default_reuse.get(m["layer"], "reusable")
```

- [ ] **Step 4: 加 stem→reuse 解析函数**

在 `scripts/check_layering.py` 的 `build_header_index()` 函数之后、`def main():` 之前插入：

```python
def reuse_of_basename(basename, reuse_by_module):
    """按文件名 stem 找模块的复用分类（模块名即 stem）。无法分类返回 None。"""
    stem = basename
    for ext in (".h", ".c"):
        if stem.endswith(ext):
            stem = stem[:-len(ext)]
            break
    for suf in ("_Cfg", "_contract"):
        if stem.endswith(suf):
            stem = stem[:-len(suf)]
    return reuse_by_module.get(stem)
```

- [ ] **Step 5: 在 include 循环里追加 REUSE 检查**

REUSE 与分层判定相互独立（不依赖本轮尚未计算的 `tgt_layer`），所以放在 `base = os.path.basename(inc)` 之后、紧接其前即可。找到 `base = os.path.basename(inc)` 这一行，在它之后插入下面这段（注意 `"to": ""` 留空，REUSE 不关心目标层级）：

```python
                if reuse_by_module:
                    cur_reuse = reuse_of_basename(os.path.basename(rel), reuse_by_module)
                    tgt_reuse = reuse_of_basename(base, reuse_by_module)
                    if cur_reuse == "reusable" and tgt_reuse == "project-specific":
                        violations.append({
                            "file": rel, "line": ln, "include": inc,
                            "from": cur_layer, "to": "", "kind": "REUSE",
                            "msg": f"复用反向依赖：reusable 模块 {os.path.basename(rel)} 依赖 project-specific 模块 {base}（破坏跨项目移植，禁止）"})
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python3 -m unittest tests.test_check_reuse -v`
Expected: PASS（3 个测试全过）

- [ ] **Step 7: 确认旧有分层测试未被破坏（手动冒烟）**

Run: `python3 scripts/check_layering.py --root .tmp_layering_test --layers assets/layers.example.json --json`
Expected: 命令正常退出并输出 JSON（不报 Python 异常）；无 `--modules` 时不应出现任何 `"kind": "REUSE"`。

- [ ] **Step 8: Commit**

```bash
git add scripts/check_layering.py tests/test_check_reuse.py
git commit -m "feat: gate reusable modules against depending on project-specific ones"
```

---

## Task 4: 文档落地（layering-rules §8 / 模板 / conformance / SKILL）

**Files:**
- Modify: `references/layering-rules.md`
- Modify: `references/module-templates.md`
- Modify: `references/conformance-checklist.md`
- Modify: `SKILL.md`

- [ ] **Step 1: layering-rules.md 新增 §8**

在 `references/layering-rules.md` 文件末尾追加：

```markdown

## 8. 跨项目移植/复用（reusable vs project-specific）

目标：让 HAL/Service/App 各层模块在「新项目有同样需求」时能从旧项目直接移植，而不是每次重写。手法是**显式分类 + 对可复用模块加护栏 + 一条机检门禁**。

### 8.1 分类与标注
- 在 `module_spec` 给每个模块加 `reuse`：`reusable` | `project-specific`。缺省按层默认：**App → project-specific，其它层 → reusable**。
- 各层典型：
  - **HAL**：`If/` 接口头是 reusable（硬件无关）；`Impl/` 与 `*_Cfg.h` 是 project-specific（板级/SDK 绑定）。
  - **Service**：算法核（FOC/PID/滤波）、通用协议栈、诊断/参数框架 → reusable；绑定本项目业务语义的 Native/Device Service → project-specific。
  - **App**：顶层编排/主状态机/任务调度强制 project-specific（它就是把 reusable 部件组装成本项目的地方）；可复用的业务子功能（通用故障管理、参数管理、按键/LED 行为库等）单独切模块后可标 reusable。

### 8.2 reusable 模块四条护栏
1. **反向依赖禁止（机检硬挡）**：reusable 模块**不得 `#include` 任何 project-specific 模块**的头。与「不向上依赖」同构——一旦反向依赖，模块就被钉死在本项目，无法移植。`check_layering.py --modules <module_spec.json>` 据此判 `REUSE` 违规并门禁失败。
2. **横切依赖收敛为自包含契约**：reusable 用到的横切语义（信号/事件 ID、Cfg 默认、返回码扩展）收进自己文件夹的 `<Module>_contract.h`，不直接引用项目全局专属 ID；共用只准依赖**稳定横切**（`IF_Types` 稳定返回码、`Bus` 注册 API 本身）。→ 整个文件夹可搬走编译。
3. **可选注入**：配置量大或需运行期替换的 reusable 模块，把横切依赖在 `<Module>_Init(const <Module>Cfg_t* cfg, ...)` 注入，模块内零项目全局引用。
4. **移植参考说明**：每个 reusable 模块文件夹带 `<Module>_port.md`（scaffold 自动生成、预填已知信息，**不机检、不硬挡**，纯给移植者当接驳点清单）。

### 8.3 组装方向
- **project-specific 可以依赖 reusable（合法）；reusable 依赖 project-specific（门禁失败）。** 这正是「App 顶层编排调用 reusable 子功能」的合法路径。

### 8.4 机检边界（诚实划线）
- **硬挡**：reusable `#include` project-specific（`REUSE` 违规，非零退出）。
- **自动生成、不挡**：`<Module>_contract.h` 占位、`<Module>_port.md`。
- **靠 conformance 人工核**：port.md 接驳点是否填全填对、追溯 ID 的新项目重映射、自包含程度是否足够。
```

- [ ] **Step 2: module-templates.md 加两个模板**

在 `references/module-templates.md` 文件末尾追加：

```markdown

## reusable 模块附加文件（scaffold 自动生成）

仅当模块 `reuse: reusable` 时，scaffold 在模块文件夹内额外生成下面两个文件。

### `<Module>_contract.h`（自包含横切契约）

```c
/*!
** @file    <Module>_contract.h
** @brief   <Module> 自包含横切契约：本模块用到的信号/事件 ID、Cfg 默认、返回码扩展集中于此，
**          整个模块文件夹可整体移植。只依赖稳定横切（IF_Types 返回码、Bus 注册 API）。
*/
#ifndef <MODULE>_CONTRACT_H_
#define <MODULE>_CONTRACT_H_
#include "IF_Types.h"
/* TBD: 本模块自有的信号/事件 ID 枚举、Cfg 默认值、返回码扩展。移植时只动这里与 Impl/Cfg。 */
#endif /* <MODULE>_CONTRACT_H_ */
```

### `<Module>_port.md`（移植参考说明）

固定五节：1. 模块身份；2. 依赖（自带 / 需新项目提供）；3. 需重新适配的接驳点（Impl、Cfg、信号 ID、前缀的 `[ ]` 勾选项）；4. 追溯重映射（旧 SRS ID → 新项目 SRS ID）；5. 主机单测打桩点。由 scaffold 预填层/前缀/SRS ID。
```

- [ ] **Step 3: conformance-checklist.md 加核查组**

在 `references/conformance-checklist.md` 文件末尾追加：

```markdown

## H. 跨项目移植/复用（reusable 模块）
- [ ] 每个模块在 `module_spec` 有明确 `reuse` 分类（或接受层默认），App 顶层编排为 project-specific。
- [ ] `check_layering.py --modules` 跑过，无 `REUSE` 违规（reusable 未依赖 project-specific）。
- [ ] reusable 模块的横切语义收在 `<Module>_contract.h`，未直接引用项目专属全局 ID。
- [ ] reusable 模块文件夹存在 `<Module>_port.md`，接驳点（Impl/Cfg/信号 ID/前缀）已按本项目填写。
- [ ] port.md 第 4 节追溯 ID 已对新项目重映射（移植场景）。
```

- [ ] **Step 4: SKILL.md 点出 reuse 分类与门禁**

在 `SKILL.md` 中找到描述 `check_layering.py` 的那一行（位于工具/脚本列表，约 `discover_inputs.py` 附近，文本含 “check_layering”）。在该行之后补一行：

```markdown
- 跨项目移植：`module_spec` 的 `reuse`（reusable/project-specific）分类——reusable 模块自动生成 `<Module>_contract.h`/`<Module>_port.md`，且 `check_layering.py --modules` 硬挡其依赖 project-specific 模块（详见 layering-rules §8）。
```

- [ ] **Step 5: 校验文档无明显破坏**

Run: `python3 -c "import pathlib; [print(p, pathlib.Path(p).stat().st_size) for p in ['references/layering-rules.md','references/module-templates.md','references/conformance-checklist.md','SKILL.md']]"`
Expected: 四个文件都打印出 >0 的字节数。

- [ ] **Step 6: Commit**

```bash
git add references/layering-rules.md references/module-templates.md references/conformance-checklist.md SKILL.md
git commit -m "docs: document reuse classification, guardrails, and gate"
```

---

## Task 5: 端到端集成冒烟

**Files:**
- 仅运行，不改文件。

- [ ] **Step 1: 用示例 spec 跑全流程并断言产物**

Run:
```bash
TMP=$(mktemp -d) && \
python3 scripts/scaffold_tree.py --spec assets/module_spec.example.json --layers assets/layers.example.json --out "$TMP/code" >/dev/null && \
test -f "$TMP/code/Source/Service/ParameterNvm/ParameterNvm_port.md" && echo "PORT_OK" && \
test ! -f "$TMP/code/Source/App/MainOrchestrator/MainOrchestrator_contract.h" && echo "PROJ_OK" && \
python3 scripts/check_layering.py --root "$TMP/code" --layers assets/layers.example.json --modules assets/module_spec.example.json --json | python3 -c "import json,sys; d=json.load(sys.stdin); print('REUSE_VIOLATIONS', sum(1 for v in d['violations'] if v['kind']=='REUSE'))"
```
Expected: 依次输出 `PORT_OK`、`PROJ_OK`，以及 `REUSE_VIOLATIONS 0`（示例骨架本身不应有 reusable→project-specific 依赖；scaffold 的 .c 只包含自身头）。

- [ ] **Step 2: 跑全部单测**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 PASS（test_scaffold_reuse 3 个 + test_check_reuse 3 个）。

- [ ] **Step 3: 合并到 main**

```bash
git checkout main
git merge --no-ff feat/cross-project-module-reuse -m "feat: cross-project module reuse classification and gate"
```
（若希望走 PR 而非直接合并，改为 `git push -u origin feat/cross-project-module-reuse` 并开 PR。）

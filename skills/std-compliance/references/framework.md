# 框架：标准包、检查项、规则、标记

## 标准包 `packs/<pack>/pack.json`

| 字段 | 说明 |
|---|---|
| `id` / `title` / `version` | 包标识与版本（检查项增删改即升版本） |
| `standards[]` | 每份标准：`key`（检查项用它引用，如 `ISO17987-3`）、`number`、`edition`、`title`、`scope_note`、`applies_to`（bus/features/role 条件）、`file_glob`（原文 PDF 文件名匹配） |
| `tags` | 本包使用的适用性标签全集（新增标签先登记在这里） |
| `role_aliases` | 旧称映射，如 master→commander |

## 检查项 `checklist.json`

```json
{"id": "LIN3-CKS-01", "standard": "ISO 17987-3", "standard_key": "ISO17987-3", "clause": "5.2.2.6",
 "title": "校验和计算", "requirement": "<自述要点，不是原文>",
 "applicability": {"bus": ["LIN"], "role": ["responder"], "features": ["diag"], "sid": ["0x22"]},
 "method": "config | design | host-test | target",
 "params": {"<名称>": "<期望值或范围>"},
 "check_hint": "<怎么查：看哪个配置参数 / 测什么输入输出>",
 "target_note": "<target 项：为什么不能在宿主机判、建议在哪测>",
 "source": {"page": 17, "verified": true, "by": "claude", "date": "2026-11-26"}}
```

- `id` 稳定不复用：`<标准缩写>-<主题>-<序号>`，如 `LIN3-`（17987-3）、`LIN2-`（17987-2）、`UDS1-`（14229-1）、
  `UDS2-`、`UDS3-`、`UDS7-`、`CANTP-`（15765-2）、`CAN1-`（11898-1）。
- 一条检查项对应一个**可判定**的要求；一个条款里有多个独立要求就拆成多条。
- `applicability` 缺省表示对标准适用范围内的所有节点适用；`role` 写 `any` 表示两端都适用。

## 结论取值

`符合` / `不符合` / `不适用`（必须有理由）/ `转SWE.6/HIL` / `未检查`。

## 规则 API（config 类）

```python
from core import PASS, FAIL, NOTRUN, result

def check(ctx):
    name, attrs = ctx.ldf_node                 # 本节点 LDF 名称与 Node_attributes
    ldf = ctx.ldf                              # parsers/ldf.parse() 的结果（header/nodes/frames/diagnostic_frames/...）
    p2 = ctx.param("DcmDspSessionP2ServerMax", "Dcm")   # ARXML 参数值列表（已转数值）
    exp = ctx.prj.get("expected.nad_physical")           # 项目期望值
    return result(PASS, "证据：写清楚比较了什么、取值来自哪个文件/参数")

RULES = {"LIN3-CKS-01": check}
```

- 输入缺失返回 `NOTRUN` 并说明缺什么；不要因输入缺失判 `FAIL`。
- 证据要能让评审人复核：列出参数名、文件、实际值、期望值。
- 规则只读输入，不写文件。

## 宿主机测试标记

测试文件 `test_*.c` 中，`/* STD: <id>[, <id>] */` 管到下一个标记之前的所有测试函数。一个检查项可有多个测试，
全部通过才算符合。没有标记的测试、引用不存在检查项的标记都会被报出（后者门禁 FAIL）。

时间按节拍：`STD_RUN_CYCLES(LinIf_MainFunction, STD_MS_TO_CYCLES(1000u, 5u))`。不要用宿主机墙钟时间。

## 工作区（`workspace`，默认 `std_ws/`）

```
extract/        标准原文候选（仅建包时；自带 .gitignore，禁止提交）
inputs/         supported_sids.json 等从配置读出的中间结果
results/        applicable.json / static.json / host.json / ceedling_stdout.log
host/           Ceedling 工程（project.yml、test/、support/）
report/         <项目>_协议符合性矩阵.xlsx、<项目>_协议符合性检查报告.md
```

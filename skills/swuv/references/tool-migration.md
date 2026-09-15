# 迁移到 Tessy / VectorCAST

本 skill 用开源链（Ceedling + Unity + CMock + gcovr + cppcheck）。若项目后续拿到商用授权，
**用例本身不需要重写**——迁移只换执行引擎。

## 为什么用例可以直接迁移

`cases.json` 里每条用例记录的是**工具无关的三件事**：

- 输入组合（`steps`：各变量与桩返回值的设定）
- 期望输出（`expected`：返回值与副作用）
- 覆盖目标（`covers_branches`：SWDD 的分支编号）

这三样在 Tessy 的测试表格、VectorCAST 的 test case 里都有对应字段。
`test_target` 的「覆盖分支 N」是本 skill 的核心资产，两个商用工具都能保留这条追溯。

## Tessy

- 导入：TIE（Tessy Interface Editor）解析被测文件的接口，用例可经 `.tst` 或 Excel 导入
- 批处理：`tessycmd` 命令行执行、生成报告
- 追溯：支持需求/设计条目关联，可承接 `unit_id`
- 覆盖率：原生支持语句/分支/MC-DC

## VectorCAST

- 环境：`clicast` 建 environment，脚本化程度更高
- 自动化：`vpython` 提供 Python API，可直接把 `cases.json` 灌进去
- 追溯：Requirements Gateway
- 覆盖率：语句/分支/MC-DC/基本路径

**若要自动化程度优先，VectorCAST 的 `clicast` + `vpython` 组合更好写。**

## 迁移时需要改的

| 项 | 改动 |
|---|---|
| `ut_spec.json` 的 `precondition_default` | 「Ceedling 搭建测试环境」→「Tessy/VCAST 搭建测试环境」 |
| 报告的工具列 | gcovr → 商用工具名与版本 |
| 覆盖率证据 | gcovr HTML 路径 → 商用工具的报告文件 |
| 桩 | CMock 自动生成 → 工具自带的 stub 机制 |

## 关于 MC/DC 的现实判断

历史上「要 MC/DC 就必须买商用工具」的论据已经不成立：
**gcc 14+ 的 `-fcondition-coverage`、clang 18+ 的 `-fcoverage-mcdc` 都能出 MC/DC**。
若项目是 ASIL QM 或采购流程漫长，开源链足以支撑；
商用工具的真正优势在成熟的目标板执行、认证材料背书与厂商支持，而不在覆盖率算法本身。

## 关于 MCP

Tessy 与 VectorCAST **均无官方 MCP server**。两者都有可用 CLI（`tessycmd` / `clicast` + `vpython`），
在 Claude Code 里直接调 CLI 即可；包一层 MCP 只在需要跨客户端复用时才划算，优先级最低。


## 与 VectorCAST 报告的对照

评审常问"换成开源链之后，商用工具报告里的东西还剩多少"。逐节比对 VectorCAST 的
full report，答案是七缺二，且缺的两项有明确理由：

| VectorCAST 章节 | 开源链的对应物 | 结论 |
|---|---|---|
| Configuration Data | `build_evidence.py` 第 1 节（spec + 工具版本探测） | 等价 |
| Overall Results | 第 2 节（gcovr 汇总 + Ceedling 计数） | 等价 |
| Testcase Management | 第 3 节（`.pass`/`.fail` 的 `:successes:` 明细） | 等价，并多一列"覆盖分支" |
| Test Case Data（输入/期望） | 第 4 节（来自 `cases.json`） | 等价 |
| Aggregate Coverage（逐行标注源码） | `gcovr --html-details` | 等价 |
| Metrics（每函数复杂度/语句/分支） | 第 5 节（详设 CCN + gcovr 逐行按函数聚合） | 等价 |
| Execution Results（打桩事件时间线） | 无 | Unity 只在断言失败时输出上下文，CMock 不导出调用序列。要做等价物须给每个桩挂 callback 记录调用顺序与实参 |
| Probe Points（探针） | 不适用 | VectorCAST 靠插桩在运行中改写内部状态；整 TU 测法可直接读写文件级静态变量，手段不同、目的等价 |

多出来的一项：VectorCAST 的用例与被测代码之间没有"设计分支号"这一层，
本方案的用例"测试目标"与测试注释都锚定 SWDD 的连续分支编号，
因此**用例↔详设的追溯是可计算的**，不依赖人工填表。

`build_evidence.py` 还会把三类追溯断裂显式列出来，而不是让它们淹没在通过率里：
覆盖了分支却匹配不到用例的测试、缺标记注释的测试、没有测试实现的用例。

## 与既有 VectorCAST 结果做对比（迁移验收）

项目里已经有一份 VectorCAST full report 时，用它来核对 swuv 的产出，也顺便审一下旧报告：

```bash
python scripts/parse_vcast_report.py unit_test/<模块>_full_report.html -o vcast.json --summary
```

输出每个子程序的测试数、总体结果、每函数语句/分支指标、探针点，以及三类值得追问的东西：

| 现象 | 含义 | 对比时怎么处理 |
|---|---|---|
| **Probe Points** 列表非空 | 该分支是靠在被测函数里注入代码（`if (vcast_test_name_equals("X")) { var = v; }`）走到的，不是靠输入。被测代码在运行时已不是交付代码 | 在 swuv 里必须用真实输入或文件级静态量摆出来；摆不出来就是不可达分支，写进报告 |
| `stubbed_calls` 里出现**本模块自己的函数** | 被测单元的一部分被替掉了，覆盖率里那几行是"被跳过"不是"被验证" | swuv 的整 TU 测法不打桩模块内部函数；对比时把这些用例标为"覆盖但未验证" |
| `has_expected_data == false` | 测试跑了，但没有任何期望值，通过是必然的 | 只能算覆盖率贡献，不能算验证；对比表里单列 |
| `input_user_code` 非空 | 用例靠 user code 直接改内部变量 | 与整 TU 测法读写静态量同源，可等价迁移 |

覆盖率数字对比前先统一口径：VectorCAST 按**判定**计分支（`if (a||b)` = 2 条出边），
gcov 按**条件**计（4 条出边）。同一份代码、同样的测试，gcov 的分母更大、百分比更低，
差的那部分是子条件的短路路径，与详设的分支编号无关。SWDD 的 Branch No 按 swuv 的规则数
（if/else 1 个、switch N 个 case N 个），与两个工具的分母都不是一回事，三者不能直接互相减。

对比报告只列**事实差异**（哪条分支旧报告靠探针、哪条用例没有期望值、哪个函数计数口径不同），
每条差异附原因；不做"哪个工具更好"的结论——那是验证策略层面的话题。

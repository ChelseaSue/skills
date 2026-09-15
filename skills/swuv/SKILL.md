---
name: swuv
description: >
  软件单元验证（SWE.4 / Software Unit Verification）：把**软件详细设计（SWDD）+ 模块源码**转成
  一套可执行的单元测试与三份受控交付物——**软件单元测试用例（AU-QR-R&D-046）、软件单元测试报告
  （AU-QR-R&D-048）、软件单元测试追溯矩阵（AU-QR-R&D-038）**。无论用户说"做单元测试""生成单元
  测试用例""写单元验证报告""建单元测试追溯矩阵""按 SWE.4 做单元验证""跑 Ceedling/Unity 单测"
  "统计语句/分支覆盖率""做 MISRA 静态检查并出报告""software unit verification / unit test cases
  from detailed design"，还是问"做单元验证还缺哪些输入"，都应使用本 skill。即使用户没明说"用
  skill"或"按 SWE.4"，只要是**从详细设计或源码往下生成单元测试用例、执行单元测试、统计覆盖率、
  建立用例↔详设双向追溯**，也要触发。本 skill 以 SWDD 流程图里的**连续分支编号**为锚点派生用例，
  因此用例的"测试目标"能机械对应到设计分支，覆盖缺口可计算而非估计；工具链全部开源
  （Ceedling/Unity/CMock + gcovr + cppcheck/MISRA）。
  区分：`srs-generator` 产软件需求规范（SRS）；`sad-generator` 产软件架构设计（SAD）；
  `code-generator` 产工程源码；`swdd-generator` 产软件详细设计（SWDD，**本 skill 的主输入**）；
  本 skill 产的是 V 模型右侧与 SWE.3 对位的**软件单元验证（SWE.4）**工作产品。
---

# 软件单元验证（SWE.4：SWDD + 源码 → 用例 / 报告 / 追溯矩阵）

## V 模型定位（先确认对位关系，别做错层）

```
SWE.1 SRS   ←→ SWE.6 软件合格性测试
SWE.2 SAD   ←→ SWE.5 软件集成测试
SWE.3 SWDD  ←→ SWE.4 软件单元验证   ← 本 skill
```

**单元验证的对标物是详细设计，不是需求。** SWDD 模板本身就以 `3.4 Unit Verification Criteria`
收尾——验证判据是详设的法定内容。需求追溯是 SWDD 的 `3.3 Traceability` 带下来的**继承属性**，
不需要把 SRS 当作本 skill 的输入。

被测对象是**函数单元**。若被测对象是组件间接口（对标 SAD）或整块软件（对标 SRS），那是 SWE.5 /
SWE.6，不属于本 skill。

## 通用性（务必保持——本 skill 设计为可用于任意嵌入式 C 项目，不绑定任何单一项目）

可移植性靠把"项目相关"的东西**全部外置成每项目一份的 `ut_spec.json`**，脚本据此工作，
因此换项目只是换这份配置，skill 本体不动：

- 模块名、路径、源码目录、include 路径、编译宏
- ASIL 等级与由此决定的结构化覆盖率目标（**QM 默认不做 MC/DC**）
- 用例 ID 前缀与位数、详设单元 ID 前缀
- 测试方法与用例生成方法的可选值、优先级 H/M/L 的映射阈值
- 固定话术（预置条件、判定准则）——各公司措辞不同
- 三份公司模板的路径
- 静态检查工具、MISRA 规则原文路径、圈复杂度阈值

配置骨架见 `assets/ut_spec.example.json`。
**改写本 skill 时守住这条底线：任何只对某一个项目成立的内容，必须外置成配置或标注为"示例"，
不得硬编码进脚本或流程。** 示例里出现的 `OXY` / `SWC_O2` / `SUT-` 只是说明格式，真实取值一律来自
配置与输入文档。

## 核心机制：分支编号是用例的锚点

`swdd-generator` 强制流程图的每个判断出边带**连续编号**（`-->|"1) Y"|`、`-->|"2) N"|`）。
本 skill 把这些编号当作一等数据：

| SWDD 里的东西 | 在单元验证里的用途 |
|---|---|
| `2.4.2` 总览表（Unit ID / External-Internal / **ASIL**） | 单元清单；按 ASIL 定覆盖率目标 |
| `2.7/2.8` 流程图的**编号分支** | 用例的"测试目标"（覆盖分支 N）；覆盖缺口可机械计算 |
| `2.5` Data Design（Enum / Constant / Calibration） | 边界值与等价类的取值来源 |
| `2.6` Dynamic Behavior | 周期与调用链 → 决定怎么摆桩、怎么推时间 |
| 函数属性表（Branch No / Complexity / Importance / Priority） | 用例优先级 H/M/L；圈复杂度核验 |

用例的"测试步骤"逐条标注命中的分支（`--3`），与"测试目标"呼应，使**用例↔设计的对应关系可被人工复核**。

## 工作流

### 第 0 步 — 输入发现与缺失确认（必做）

1. 定位模块源码与 SWDD。SWDD 通常在 `swdd/{模块}/*_Software_Detailed_Design_Document*.md`。
2. **若目标模块没有 SWDD**：不得静默降级。必须用 `AskUserQuestion` 让用户明确选择：
   - 先跑 `swdd-generator` 生成详设（**推荐**，追溯链完整）
   - 无 SWDD 降级模式：直接从源码推分支与边界
3. 若用户选择降级，**必须在报告与追溯矩阵中显著标注"设计侧缺失，追溯不完整"**，
   反向追溯表的设计侧留空并写明原因；**不得伪造 SWDD ID 或覆盖率统计**。
4. 准备 `ut_spec.json`（拷贝 `assets/ut_spec.example.json` 后按项目改写）。
   `asil`、`coverage_targets`、`test_methods`、`derivation_methods` 应取自项目的
   《软件单元验证策略》——该策略由人工编写，**不是本 skill 的输出**。
5. `include_dirs` / `defines` **从目标机构建产物里抄，不要凭目录结构猜**：
   Eclipse/S32DS 工程看 `<Debug>/src/<xx>.args`（`-I` / `-D` 逐行）或 `.cproject`，
   Makefile 工程看 `make -n` 的实际命令行。真头文件在宿主 gcc 上基本都能编译，
   自己"精简"一套 include 列表只会在 CMock 生成桩时缺类型。
   `include_dirs` 会同时喂给 Ceedling 与 cppcheck，`gen_project_yml.py` 据此生成 `project.yml`：

   ```bash
   python scripts/gen_project_yml.py --spec ut_spec.json        # 已存在时需 --force
   ```

### 第 1 步 — 解析 SWDD

```bash
python scripts/parse_swdd.py <swdd.md> -o swdd_model.json
python scripts/parse_swdd.py <swdd.md> --summary      # 一致性核验
```

`--summary` 会核对每个单元的 `Branch No` 与流程图实际判断数，并核对 `2.4.2` 总览表与
`2.7/2.8` 章节是否一一对应。**有 MISMATCH 必须先回去修 SWDD**，不要带着不一致往下走——
详设与用例不一致会在评审第 18 项上被打回。

分支计数规则：if/else 的两条出边算 **1 个分支**；switch 的 N 个 case 算 **N 个分支**。

### 第 2 步 — 派生用例

```bash
python scripts/gen_cases.py --model swdd_model.json --spec ut_spec.json -o cases.json --summary
```

做法是枚举流程图上 Start→终点的路径（同一路径内不重复走同一条边，因此循环只进入一次），
再用**贪心集合覆盖**挑出覆盖全部编号分支的最小路径集，一条路径产出一条用例。
这样 100% 分支覆盖是**构造出来的**，不是事后统计出来的。

在集合覆盖之前，先用 `_feasibility.py` 沿路径做常量传播，剔除数据上走不通的组合
（详见常见坑）。`--summary` 会列出被剔除的路径及理由，逐条可核，例如：

```
O2_UpdateSeatDuty [2, 3, 6]: 分支 6：路径上此前已把 s_ctx.au16SeatPullInMs[u8SeatIdx]
  赋为 300，因此 `s_ctx.au16SeatPullInMs[u8SeatIdx] > 0u` 只能取 真，与本分支要求的 假 矛盾
```

**只出现在被剔除路径上的分支会单独列出**——那通常意味着详设里有走不到的分支，
是要查的东西，不要当成生成器的缺陷放过。

`--summary` 末尾还会报告是否有未覆盖分支。**有未覆盖必须处理**：要么补用例，要么在报告里说明
该分支不可达及理由（例如防御性分支）。

生成结果是**草稿**：测试步骤给的是路径上的判断走向，`预期输出` 取自流程图节点。
**必须逐条复核并补全具体取值**——等价类与边界值要从 `2.5` 的常量、枚举、标定表取真实数字，
把 `u16GaugeKpa < OXY_O2_PRESS_START_KPA` 这类条件落实成 `399 / 400 / 401` 这样的具体输入。
这一步是 LLM 的工作，不要交给脚本。**但具体文本不要直接改 `cases.json`**——第 5 步对账
和重跑第 2 步都会重建它。把文本写进按"单元 + 分支路径"作键的 `case_text.json`，
每次重建后重新合并：

```bash
python scripts/apply_case_text.py --cases cases.json --text case_text.json
```

它对没拿到文本、或仍含 `待填` 的用例非零退出，草稿不会悄悄进交付物。格式见脚本 docstring。
加 `--spec` 后还会核对**「设计方法」列只含方法名**：`基于需求分析、等价类、边界值` 这种，
取值限于 `derivation_methods`。等价类怎么划、边界取了哪几个值写进测试步骤，不写进这一列——
评审按这一列筛选统计，夹了说明文字就筛不动了（`self_check` 第 6 项同样按此判）。

### 第 3 步 — 静态验证（SWE.4-A04）

```bash
python scripts/run_static.py --spec ut_spec.json --model swdd_model.json -o static.json
```

cppcheck + MISRA addon；圈复杂度取自 SWDD 的判断数（McCabe CCN = 判断数 + 1），
与详设同源，避免两处测量互相打架。

除 `static.json`（机器可读，供后续脚本用）外，还会产出独立的
`<output_dir>/report/static_verification_report.html`：结论、按规则统计、每条发现附源码行、
逐单元 CCN、命令行。048 报告「静态验证情况总结」的结果说明列自动带上这个路径；
cppcheck 自己不出报告文件（`--xml` 只是另一种文本格式，`cppcheck-htmlreport` 不随 MinGW 包发布），
不要另外去找。

**通过判据**：MISRA mandatory 违规为 0；required/advisory 允许存在但需要在报告中给出理由；
圈复杂度不超过配置的阈值。MISRA 规则原文属授权内容，未配置时只报规则号，不影响判级。
报告里静态验证一栏据此三态判定：`Pass` / `Pass with conditions`（仅 CCN 超限）/ `Fail`；
没跑就是 `not run`。

只统计 `source_dirs` 下的发现；供应商头文件里的告警计入 `findings_outside_object`，
不参与判级——被测对象是本模块，不是 MCAL。

**AutoSAR/MCAL 工程的两个 cppcheck 专属问题**（它们只影响 cppcheck，gcc 没事）：
- `*_MemMap.h` 的 `#error "no valid memory mapping symbol"`：cppcheck 的预处理器
  不按 gcc 的方式处理该协议，整个文件被放弃、MISRA 什么都没查。
  用 `gen_memmap_stubs.py --search <MCAL 目录> -o <output_dir>/static_support` 生成
  只含版本宏的替身，填进 `static.extra_include_dirs`（它排在 `include_dirs` 之前）。
- 编译器抽象头（`Mcal.h` / `Compiler.h`）遇到不认识的编译器就 `#error`：
  把 `__GNUC__` 放进 `static.extra_defines`。**不要放进 `defines`**，gcc 自己会预定义它。

`run_static.py` 若报"分析了 0 个函数/0 条发现"，先怀疑上面两条，不要当成代码干净。

### 第 4 步 — 执行单元测试与采集覆盖率

**一条用例只验证一个单元。** 被测单元调用的**模块内部函数**也要替换掉，不能让它真跑——
否则用例的预期里就得写别人的行为，覆盖率的调用次数也混在一起。三种情况：
- 调的是别的模块：CMock 桩，本来就如此；
- 调的是**同一个 `.c` 里的 static 函数**：整 TU 测法替换不了，只能真调。用例文本只写被测单元
  自己的可观察结果（"X() 被调用一次"），不描述被调函数内部；
- 调的是**同模块另一个 `.c` 里的函数**（如 `DMCU_prg.c` 调 `DMCU_cfg.c` 的 `MCU_vidWkupConfig`）：
  那个 `.c` 单独编译链接（放 `support/`，需要时经 `gen_host_shim.py`），测试文件里定义同名计数桩，
  `link_flags: ["-Wl,--allow-multiple-definition"]`——测试目标文件排在链接首位，它的定义胜出；
  验证被调函数本身的测试文件不定义桩，链接到真实现。**不要用弱符号**：MinGW/PE 上
  `__attribute__((weak))` 的定义解析不到跨目标文件的引用（链接报 undefined 或运行时跳到 0）。

**源文件在宿主机上编不过（而且不是 include 问题）时，用 `gen_host_shim.py`，不要手改副本。**
典型的是 32 位向量表存函数地址：`(uint32)(uint32 *)&Reset_Handler` 在 64 位 gcc 上是
"initializer element is not constant"，整个文件被拒，文件里的其他单元也测不了。
把逐字替换与理由写进 `ut_spec.json` 的 `host_shims`，脚本生成 `support/<file>_host.c`：
每个 `old` 必须恰好出现一次、不得改变行数，副本以 `#line 1 "<原文件>"` 开头，
于是 gcov / cppcheck / 单元验证报告仍然记在原文件上，单元验证报告第 1 节会列出全部替换。
只允许替换目标机上也不执行的东西（未激活的表项、死代码里的常量）；
被测单元的任何一行都不能进这个列表。

```bash
python scripts/gen_host_shim.py --spec ut_spec.json      # 每次构建前重新生成
```

用 Ceedling（Unity + CMock）在宿主机执行，gcovr 出覆盖率。
被测模块若含 `static` 函数与文件级状态，测试文件用 `#include "<模块>_Prg.c"` 的**整 TU 测法**，
以便直接摆放内部状态并逐周期推进。
CMock 从服务层头文件自动生成桩——**这正是分层架构的回报**：应用层只调纯函数接口，桩点天然清晰。

`project.yml` 的关键约定（示例见 `references/ceedling-setup.md`）：

- 被测模块目录放 `:paths :include`，**不要放 `:paths :source`**——整 TU 测法下它已被测试文件
  包含，再让 Ceedling 单独编译一次会在链接期重复符号
- `support/` 只放 MCAL 基础类型（`Platform_Types.h` / `Std_Types.h` / `Compiler.h`）与 OS 替身，
  **不要引入真的 MCAL 头**，否则会拖进整个寄存器映射
- CMock 插件至少启用 `:ignore`、`:expect_any_args`、`:ignore_arg`、`:return_thru_ptr`、`:array`；
  通过指针返回值的服务接口（`DEV_GetPressure(ch, &val)`）必须靠 `:return_thru_ptr` 打桩，
  带缓冲区入参的（`Eeprom_Write(addr, buf, len)`）靠 `:array` 的 `_ExpectWithArrayAndReturn`
- `:treat_externs: :include` **必配**。项目头文件的原型几乎都带 `extern`，CMock 默认跳过它们，
  生成的 mock 是空的——症状是链接期一堆 `undefined reference`，而不是 CMock 报错
- `:treat_as` 要把项目自己的 typedef 名（`u8`/`u16`/`u32`/`bool`）全列进去，否则 CMock
  按结构体比较、断言信息不可读

```bash
ceedling test:all          # 功能
ceedling gcov:all          # 带覆盖率
python scripts/collect_coverage.py --spec ut_spec.json --build <build 目录> \
    --cases cases.json --model swdd_model.json -o coverage.json
```

覆盖率证据以**报告文件路径**记入交付物（对齐公司报告里 `Report：XXX` 的写法），
**不往 Excel 里嵌截图**。

**gcc 的分支覆盖是条件级，不是判定级。** `if (a || b)` 在 SWDD 里是 1 个分支 2 条出边，
gcov 里是 2 个条件 4 条出边。所以：
- 详设分支 100% 不等于 gcov 100%。前者靠用例集构造出来，后者要靠**补充测试**把每个
  子条件的两侧都走到（标 `/* supplementary - 不新增分支：覆盖 xxx 子条件 */`）；
- 短路后不可达的子条件（前一个子条件为真时后一个永远不求值，或数据上矛盾）在 gcov 里
  永远是缺口，**报告的「未达成说明」写清是哪个子条件、为什么不可达**，不要硬凑；
- 与 VectorCAST 等按判定计数的工具对数时，先把口径说明白，再比数字。

### 第 5 步 — 对账：让用例表与实际测试一致（必做）

```bash
python scripts/reconcile_cases.py --model swdd_model.json --spec ut_spec.json \
    --cases cases.json --root .                    # 先看 diff
python scripts/reconcile_cases.py ... --apply   # 确认后落盘
```

写测试时发现生成的路径走不通、改走了别的路径，是**正常流程**，不是事故。
但用例表必须跟着改，否则交付物会烂掉：用例没人实现、测试没法追溯。
本步以**测试注释里声明的实走分支**为准回写用例，并按需要补建用例。

> 重跑第 2 步会**覆盖**对账结果。详设改动后的正确顺序是：第 2 步重新生成 → 第 5 步重新对账。
> 不要手工编辑 `cases.json` 绕过对账，那样下次重新生成就又丢了。

它会区分五种情况，只有前三种会改文件：

| 情况 | 处理 |
|---|---|
| 实走分支与用例声明不符 | 用实走路径重新派生该用例的测试目标与步骤 |
| 测试没有对应用例 | 补建一条用例，并给出该写的注释 |
| 修正后某分支失去用例 | 再补用例，保证用例集仍覆盖全部详设分支 |
| 实走分支正好是同单元另一条用例 | **不改用例表**，报"注释里用例号写错了" |
| 声明为 supplementary 的补充测试 | 不进用例表，单独列出 |

剩下两类必须人工判：分支组合在流程图上找不到完整路径（多半是注释只写了增量分支）、
用例始终没有测试实现。

还有一类它**只报不改**：同一个用例号被两个路径不同（且互不为子集）的测试同时声明。
以前这会让每次 `--apply` 把用例改成后到的那条路径、下次再改回去，永不收敛。
现在先到者胜出、后到者按"未标记"列出——去改注释，给第二条路径一个自己的用例号。

### 第 6 步 — 生成单元验证报告（HTML）

```bash
python scripts/build_evidence.py --spec ut_spec.json --build <build 目录> \
    --cases cases.json --model swdd_model.json --static static.json \
    --coverage coverage.json --root .
```

产出 `<output_dir>/report/unit_verification_report.html`，是交付物里"证据"列引用的那份东西：
总体结果、逐条用例的输入/期望/实测、每函数复杂度与语句分支指标、
以及 gcovr 的逐行标注源码（`coverage/index.html`）。
**报告里只写被测软件的事实，不写工具选型的辩解。**"开源链相比商用工具缺什么"
属于验证策略（A02）层面的一次性说明，写在 `references/tool-migration.md`，
不要放进每个模块的交付物——那会在每份报告里重复一遍，读起来像自我辩护。

「用例执行清单」**一条测试函数一行**，不是一条用例一行：每个测试有自己的判定与耗时，
那正是这一节存在的意义，合并成一行会把它们抹掉，其中一个失败时也看不出是哪个。
同一条用例的连续行会**空掉重复的单元/用例ID/用例名**格子，分组一眼可见而不丢证据；
需要"一条用例、测试函数合并显示"的视图，看第 4 节「用例明细」的「实现测试函数」列。

「覆盖分支号」列是该测试走过的**详设分支编号**，以 `/` 分隔，**不是分数**——
`2/3` 读作"分支 2 和分支 3"。位数不同是路径长度不同：在前面的判断处提前返回的路径，
经过的判断本来就少。分隔符与 SWDD 的「测试目标：覆盖分支 2/3」和 046 用例表保持一致，
歧义靠列名和表下说明消除，不靠跟另外两份文档分家。

它还会把三类追溯断裂显式列出来——覆盖了分支却匹配不到用例的测试、缺标记注释的测试、
没有测试实现的用例。**这些告警是要处理的，不是背景噪音**：
前两类通常意味着实现时改写了不可行路径而用例表没同步，第三类会让追溯矩阵的正向追溯断掉。

任何一步 gcovr 失败或返回 0 个函数，脚本**非零退出**，不会产出一份看着正常其实是空的页面。

### 第 7 步 — 生成三份交付物

```bash
python scripts/build_deliverables.py --cases cases.json --model swdd_model.json \
    --spec ut_spec.json --static static.json --coverage coverage.json --all
```

`--coverage` 缺省时报告里的覆盖率与执行率会标成「未执行/Not run」，**这是正确行为**——
不要为了让表格好看而填 0 或 100%。

`.xlsx` 模板会被**克隆**，封面与修订记录页原样保留；`.xls` 旧格式模板 openpyxl 无法写，
按 `references/template-structure.md` 记录的列契约重建。

### 第 8 步 — 自检

```bash
python scripts/self_check.py --cases cases.json --model swdd_model.json \
    --spec ut_spec.json --root .
```

对照 `references/review-checklist.md`（22 项评审检查项）逐条确认。
第 11、17、18 项（覆盖所有详设单元、追溯建立且内容一致）机械判定；
**加 `--root` 后第 19/20 项（测试脚本与用例一致）也变成机械判定**——
它读测试源码里的标记注释，比对实走分支与用例声明。其余需要人工确认并留下证据。

## 输出

| 交付物 | 模板 | 内容 |
|---|---|---|
| 软件单元测试用例 | AU-QR-R&D-046 | 一模块一 sheet，13 列；同一函数的连续行只在首行填单元 ID/名称 |
| 软件单元测试报告 | AU-QR-R&D-048 | 测试目标 / 静态验证 / 覆盖率 / 测试实施 / 缺陷解决 五个总结区 |
| 软件单元测试追溯矩阵 | AU-QR-R&D-038 | 正向（用例→详设）+ 反向（详设→用例），含四项统计与设计覆盖率 |
| 单元验证报告（HTML） | 无模板（HTML） | 配置数据 / 总体结果 / 用例执行清单 / 用例明细 / 代码指标 / 逐行覆盖 |
| 静态验证报告（HTML） | 无模板（HTML） | MISRA/cppcheck 结论、按规则统计、发现明细（附源码行）、逐单元 CCN、命令行 |

三份 Excel 里的比率均以百分比格式呈现（`0.0%`），单元格仍是数值，可继续参与统计。

**范围内**：A03 用例、A04 静态验证、A06 执行、A07 报告。
**范围外**：A02 验证策略与 T06 测试大纲（人工编写）、A05 代码评审（人工会议）。

## 常见坑

- **不要把 SRS 当输入**。单元验证对标详设；需求经详设传导，SWDD 的 `3.3` 已承接。
- **不要静默降级**。缺 SWDD 必须先问用户（第 0 步）。
- **不要伪造覆盖率**。测试没跑就写"未执行"，别填 0 或 100%——两者都会误导评审。
- **克隆模板后必须先解除合并单元格再写入**。openpyxl 对合并区域非锚点单元格的写入会**静默丢弃**，
  表现为零散几行数据凭空消失。`build_deliverables.py` 的 `_reset_sheet()` 已处理。
  同一函数还会清掉模板作者留在数据 sheet 上的**示例图片、图表和批注**——048 模板的
  「静态验证结果」页就带着一张命名规则截图，`delete_rows` 删不掉它，会压在重生成的表上。
  封面页的 logo 不在重填范围，不受影响。
- **重跑 `build_deliverables.py --only report` 会覆盖手工填写的理由单元格**（未达成说明、
  MISRA 偏离理由、缺陷分析）。重跑前先把这些格子读出来，写完再回填；不要靠记忆重写。
- **不要直接采信 Ceedling gcov 插件给出的覆盖率汇总**。它按 `:paths :source` 过滤，
  而整 TU 测法下被测文件恰恰不在那条路径上，**结果是汇总里根本没有被测文件，只剩 mock 和 vendor 代码**，
  数字看着有、其实测的是别的东西。用 `collect_coverage.py`，它按 `source_dirs` 的**完整路径**过滤。
  过滤器不能只用目录末段：构建目录常叫 `unit_test/<模块>/`，与源码目录同名，会把 mock 一起匹配进来。
- **同一个坑还有第二面：插件产出的 HTML/Cobertura 文件本身是空的**（`Lines: 0.0% 0/0/0`、`<packages/>`）。
  只修数字而仍在交付物里引用那个文件，评审员点开就是一片空白。
  `:gcov:` 段下不要配 `:reports:`，覆盖率报告交给 `build_evidence.py`。
  **空报告比没有报告更危险。**
- **Ceedling 1.x 配置语法与 0.x 不同**。`:use_test_preprocessor` 的取值是
  `:none` / `:all` / `:tests` / `:mocks`，写 `TRUE` 会直接校验失败。
- **生成的路径可能不可行，这是路线本身的代价**。路径枚举走的是控制流图，
  图上有边不等于数据上走得通。实例：`O2_UpdateSeatDuty` 曾生成"覆盖分支 2/3/6"，
  但分支 3 会把计时器置成 300，之后不可能再走到"计时器为 0"的分支 6。

  现在有两道防线，但**都不能完全消除**这个问题：
  1. `_feasibility.py` 沿路径做常量传播，判定与此前赋的常量矛盾就剔除该路径。
     它只认最简单的 `x = <常量>` 赋值，遇到表达式、函数返回值、未知变量就**忘掉**该变量
     而不是猜——所以不会误杀可行路径，代价是抓不全。跨函数、数组下标、循环多轮都抓不到。
     `x++` / `x += n` / `&x` 同样会让它忘掉 `x`（否则 `i = 0` 之后的 `i < 64` 永远为真，
     循环出口被当成不可达）。第二条规则：**同一个只含局部变量的判断在路径上出现两次、
     其间没有语句改过这些变量，两次结果必须一样**——`if (BBS_ARMED == sta) … if (BBS_ARMED == sta)`
     的 Y/N 交叉组合直接剔除。局部变量取自流程图里 `类型 名字` 形式的声明节点。
  2. 抓不到的由第 5 步 `reconcile_cases.py` 事后收回来。

  彻底判定可行性需要符号执行加约束求解，与"SWDD 文本就能跑"的路线不是一个量级，不做。
- **路径枚举不复用边**，因此一条路径最多进入循环一次。
  测试若驱动循环跑多个元素，会走到循环内判定的两侧，其分支集是用例的**超集**——
  这不是漂移，工具按超集放行。
- **测试函数的序号与用例号不是一回事**。`test_<单元>_001_...` 完全可能实现的是 `<单元>.004`，
  两套编号各自独立。所以测试与用例的对应**只能靠标记注释**，不能按名字里的序号去猜——
  猜出来的映射会静默错位。注释的两种合法形态见 `references/ceedling-setup.md`。
- **`covers branches` 写的是完整路径，不是"本测试新增的分支"**。
  只写增量会让对账找不到对应路径。测试若确实在用例集之外，用
  `/* supplementary - adds branches ... */` 声明，它就不再被当成缺陷。
- **别把"同一条用例的另一个取值"误标成 supplementary**。判据是实走分支集：
  等于某条用例就标那条用例号，**换了输入取值也仍然是那条用例**；
  只有走出用例集里没有的路径，才是补充测试。
  实例：`SCN_SanitizeGear(255u)` 与 `SCN_SanitizeGear(2u)` 都走分支 1，
  是同一条用例的两个边界取值，不是两件事。**一条用例有多个测试是等价类/边界值的常态**，
  报告会把它们归到一组；标错会让交付物凭空多出一串"补充测试"，
  掩盖掉真正在用例集之外的那几条。判不准时先按用例号标，跑 `reconcile_cases.py` 验。
- **修正用例走向可能让某个分支失去用例**。改窄了某条用例的路径后，它原先顺带覆盖的分支
  可能没有别的用例接手。`reconcile_cases.py` 会重算并补建，别手工改用例表绕过这一步。
- **CMock 的 `*_ReturnThruPtr_*` 存的是指针，不是值**，调用发生时才解引用。
  若把局部变量地址传进去，辅助函数一返回就悬空，读到栈上残值。症状极具迷惑性：
  测试有时通过（残值恰好还在）、有时给出毫不相干的失败值。**打桩用的缓冲必须是 static**；
  一次排队多个期望时还要各占一个槽位，见 `references/ceedling-setup.md`。
- **报告的「未达成说明」不能空着**。空的 "Not Reach" 会在评审被打回。
  `build_deliverables.py` 会自动把未覆盖行号写进该列，但**理由仍须人工补**——
  说明它属于详设已排除的死代码，还是不可达的防御性分支。
- **优先级不是拍脑袋**。取自 SWDD 的 `Priority = Complexity × Importance`，按配置阈值映射 H/M/L。
- **MC/DC 按 ASIL 决定**。QM 项目默认不做；需要时把 `coverage_targets.mcdc` 设成目标值，
  gcc 14+ 用 `-fcondition-coverage`、clang 18+ 用 `-fcoverage-mcdc`。
- **一个用例号只对应一条路径**。给同一个号标两条不同路径，对账会来回翻；
  同一条路径的多组取值才共用一个号（见上一条 supplementary 判据）。
- **固定地址的寄存器块（`#define IP_X ((X_Type *)0x4xxxxxxx)`）在宿主机上一碰就崩**。
  整 TU 测法下先包含定义它的头，再 `#undef IP_X` / `#define IP_X (&ut_x)` 指向测试里的 RAM 副本，
  然后才 `#include` 被测 `.c`；寄存器的写入就成了可断言的值。不要为此做 shim 副本。
- **配置表长度宏与初始化项数不一致**（`T tab[N] = { 23 项 }`，N = 24）：多出的项是全零，
  循环会把"引脚 0 / 通道 0"当真配置。gcc 不报，MISRA 9.3 会报——静态结果里的 9.3 要看一眼，
  测试则按表实际内容断言并把它记进报告的缺陷项，而不是绕开。
- **函数内 `static` 局部变量的状态跨测试残留**。整 TU 测法能清文件级静态量（`setUp` 里 memset），
  但函数内的 `static u8 u8Delay` 谁都摸不到，只能靠"前一个测试跑到了某个值"。
  这类测试**必须写明顺序依赖**（注释 + 用例的预置条件），并且放在同一个测试文件里；
  要彻底解耦就得改源码把它提升成文件级静态量——那是设计问题，先记进报告，不要在测试里绕。
- **CMock 生成的 mock 是空的、链接期一堆 undefined reference**：头文件原型带 `extern`，
  缺 `:treat_externs: :include`。见第 4 步。
- **cppcheck 报 0 条发现或 0 个函数**：多半是 MemMap `#error` 或编译器抽象头让它放弃了整个文件，
  不是代码干净。见第 3 步。
- **与 VectorCAST/商用工具的历史结果对比**时，用 `parse_vcast_report.py` 把 full report 结构化，
  先看三件事：探针点（靠改写被测代码走到的分支，不是靠输入）、被打桩的模块内部函数
  （被测单元自己的一部分被替掉了）、没有期望数据的用例（只是跑了，没验证）。
  流程见 `references/tool-migration.md`。

## 工具链（全开源）

| 用途 | 工具 | 说明 |
|---|---|---|
| 用例执行 | Ceedling + Unity + CMock | 需要 Ruby；CMock 从头文件自动生成桩 |
| 覆盖率 | gcovr | HTML + Cobertura XML |
| 静态检查 | cppcheck + misra addon | 规则原文需自备授权副本 |
| MC/DC（可选） | gcc `-fcondition-coverage` / clang `-fcoverage-mcdc` | 仅在 ASIL 要求时启用 |

商用工具（Tessy / VectorCAST）迁移路径见 `references/tool-migration.md`：
用例的输入组合与期望值是工具无关的，迁移只换执行引擎。

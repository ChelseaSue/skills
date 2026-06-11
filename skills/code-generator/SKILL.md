---
name: code-generator
description: >
  把软件需求规范（SRS/软件需求文档）+ 软件架构设计（SAD/软件架构文档）+ 基础 SDK 代码（BSP/MCAL/OS 等）
  转成一套**分层、模块化、满足 MISRA C:2012、可移植/可维护/可测试**的嵌入式 C 工程代码。无论用户说
  "按软件需求和软件架构生成代码""把 SAD/SRS 落地成代码""生成固件/工程代码骨架""实现某个 SWC/HAL 模块""搭分层
  代码目录""按 MISRA 生成驱动/应用层代码""generate firmware code from SRS/SAD""scaffold a layered embedded
  project"，还是问"生成代码还缺哪些输入/信息"，都应使用本 skill。即使用户没明说"用 skill"或"按架构"，只要是
  从软件需求/软件架构往下生成或补全 C 代码、要求分层（硬件抽象/高内聚低耦合/接口可注入）、要求 MISRA 合规、
  或询问代码生成需要什么输入，也要触发。本 skill 先做缺失输入提示，再按 SAD 派生"分层+模块"计划，支持两种模式：
  ①脚手架（生成整套分层目录+全模块骨架与接口契约）②逐模块实现（按 SAD 章节+SRS 需求补全单个模块完整逻辑）；
  并强制做需求→代码 100% 追溯、跨层依赖静态核查、cppcheck --addon=misra 门禁，最后用一致性检查清单核验。
  区分：`srs-generator` 产软件"需求规范"（SRS，上游）；`sad-generator` 产软件"架构设计"（SAD，中游，本 skill 的
  主输入）；`swdd-generator` 是 code→"详细设计"（SWDD，下游）；本 skill 产的是**架构落地后的工程源代码**。
---

# 代码生成器（软件需求 SRS + 软件架构 SAD + 基础 SDK → 分层 MISRA-C 工程代码）

把"软件要做什么"（SRS）和"软件怎么搭"（SAD）落地成**真正可编译、可维护的分层 C 工程**。SAD 已经给出了分层架构图、
组件分解与接口、状态机与时序——本 skill 的工作是把这些**忠实地翻译成目录结构 + 头文件接口契约 + 实现逻辑**，
而不是凭空发挥。

文档/代码链：系统需求 →（`srs-generator`）→ SRS →（`sad-generator`）→ **SAD** →（**本 skill**）→ **工程源代码** →（`swdd-generator`）→ SWDD。

**核心立场（务必内化，别变成机械填模板）：**
- 代码的**分层与模块边界由 SAD 决定**，不是由本 skill 预设。本 skill 提供的是一套通用分层模型和约束规则，
  具体有几层、每层哪些模块、模块间依赖，都从 SAD 的分层架构图 / 组件表 / 接口表里读出来。
- **不要把任何一个具体项目（包括示例里出现的命名）硬编码进生成结果**。示例只是说明"好的分层长什么样"，
  真实命名/层数/模块一律以输入文档为准。
- 三件事是这套代码的灵魂，缺一不可：**分层不可逆（上层依赖下层，不能跨层）**、**模块高内聚低耦合
  （同层之间靠接口/总线解耦，不互相直接调）**、**接口可注入（硬件相关都藏在抽象层接口后，便于替换与打桩测试）**。

## 通用性（务必保持——本 skill 设计为可用于任意嵌入式 C 项目，不绑定任何单一项目）
本 skill 不假设特定公司/项目的目录布局、命名、层数或需求 ID 格式。可移植性靠把"项目相关"的东西全部**外置成
两个每项目生成的配置**，而不是写死在 skill 里：
- `layers.json`：声明本项目的层序、横切层、`path_map`（路径→层）、放行边、是否严格相邻——**从该项目的 SAD 读出来**。
- `module_spec.json`：声明本项目的模块、接口、依赖、覆盖需求——**从该项目的 SAD/SRS 读出来**。
脚本据此工作，因此换项目只是换这两份配置，skill 本体不动。其余通用化保障：
- 输入发现 `discover_inputs.py` 关键词**中英双语 + 通用词**，并非只认某套中文文件夹名；找不到时让用户直接给路径即可。
- 需求 ID 追溯默认正则兼容多种方案（`PREFIX_SRS_001`/`SWREQ_45`/`REQ-001`/`SR-7`…），异类格式用
  `conformance_check.py --req-pattern '<正则>'` 覆盖。
- 文档/注释语言**跟随该项目的 SRS/SAD**（中文项目用中文，英文项目用英文）。
- 参考资料里出现的层名/前缀/范式（App/Service/Hal、`IF_`、SignalBus、If/Impl…）都是**说明性示例**，
  真实项目一律以其 SAD 为准；**绝不要把示例命名搬进生成结果**。
> 改写本 skill 时守住这条底线：任何新增内容若只对某一个项目成立，就该外置成配置或写成"示例"，不能硬编码进流程。

## 何时用、产出什么
- **输入**：① SRS（软件需求，优先 `.md`，其次 docx）② SAD（软件架构，优先 `.md`，其次 docx）——**主驱动**
  ③ 基础 SDK 代码根（含 BSP/MCAL/OS/RTOS、芯片驱动、已有 HAL 等，是生成代码要对接的底座）
  ④（可选）通信矩阵/DBC（让收发逻辑对接真实 CAN 信号）⑤ MISRA C:2012 规范 PDF（权威，但日常用 cppcheck 自动门禁）。
- **产出**：一套分层目录下的 C 源码（`.h` 接口 + `.c` 实现 + `_Cfg.h` 配置），每个文件头标注它实现/覆盖的需求 ID；
  附带：需求→代码追溯表、跨层依赖核查报告、MISRA（cppcheck）报告、**一致性检查清单核验报告**。
- **语言**：注释与文档统一中文（代码标识符用英文），与同项目 SRS/SAD 一致。

## 四条硬性要求（用户明确，务必满足）
1. **调用即先做缺口提示**（第 2 步，不可跳过）——动手生成前先点出"SRS/SAD/SDK 之外还缺什么"，把判断权交还用户。
2. **分层 + 模块化 + 可注入**——严格按 SAD 的层次落目录与依赖：上层只能依赖**相邻下层**的公开接口，**不能跨层**
   （不向上依赖、不跳层直够更底层）；同层模块之间高内聚低耦合，靠接口/总线/回调解耦（上下层与同层的通信机制——SignalBus/回调/EventBus/接口——按产品场景选，见 `references/layering-rules.md` §4）；硬件相关全部收敛到抽象层
   接口（`.h`）之后，实现（`.c`）可替换、可打桩注入。规则与判定见 `references/layering-rules.md`。
3. **MISRA C:2012 合规**——按构造满足（详见 `references/misra-c2012.md`），并以 `cppcheck --addon=misra` 作为
   自动门禁；不可消除的偏离要在代码处写明 `/* MISRA deviation Rx.y: <理由> */` 并登记。
4. **目录结构清晰 + 100% 需求追溯 + 可核查**——目录能一眼看出分层与模块关系；每条 SRS 需求都落到某个模块/函数；
   结尾用 `references/conformance-checklist.md` 的清单（配 `scripts/conformance_check.py`）核验是否符合本 skill 全部设计要求。

## 两种工作模式（先判断在哪个模式）
- **脚手架模式（scaffold）**：新项目从零搭，或需要把 SAD 的整套分层一次性铺成代码骨架。产出整套分层目录树 +
  每个模块的头文件（含从 SAD 抄来的 API 契约 + 追溯标注）+ `_Cfg.h` + `.c`（函数桩 + `TBD` 占位体）。目标是
  **可编译的外壳 + 完整追溯底座**，逻辑随后逐模块填。
- **逐模块模式（module）**：项目骨架已存在（如已有 SDK/HAL/部分 SWC），本次只实现/补全**一个**模块。读该模块的
  SAD 章节 + 对应 SRS 需求 + 它依赖的下层接口头文件，写出**完整实现逻辑**，遵守分层与 MISRA 规则。
- **怎么判断**：用户说"搭工程/铺骨架/从零生成整套"→脚手架；说"实现/补全 XX 模块/某 SWC/某驱动"→逐模块。
  拿不准就问一句，或先看代码根是否已有分层目录（已有→多半是逐模块）。

---

## 工作流（按顺序；第 2 步缺口提示不可跳过）

### 1. 定位输入
确认 SRS（优先 `.md`）、SAD（优先 `.md`）、SDK 代码根、（可选）通信矩阵的路径。运行发现脚本扫描同项目：
```bash
python3 scripts/discover_inputs.py <项目根目录>
```
它按目录/文件名把文件归类（SRS/SAD/SDK 代码根/通信矩阵/MISRA 规范/系统需求…），输出"已找到 vs 缺失"。
若用户只给了某个文件没给根，以该文件目录的上一级当根。

### 2. 缺口提示（调用时必做——硬性要求）
**在动手生成之前**，给用户一张"代码生成所需输入 vs 已找到 vs 缺失"清单，明确点出缺什么、缺了会怎样，请用户补充
或确认"以 TBD/默认假设继续"。为什么必须先做：从 SAD 到可运行代码之间还有大量**实现级信息** SAD 里未必写全——
具体寄存器/管脚映射、时钟与分频、外设实例号、缓冲区尺寸、任务优先级与栈、定时器节拍、NVM 块布局、CAN 报文周期、
错误码取值……闷头生成只会硬编造或静默留洞。把这些点名问清楚，远比事后返工便宜。

判定细节与给用户的提示输出范例见 `references/input-checklist.md`。把用户已确认的范围决定（如"功能安全本期不涉及"
"通信矩阵已就绪"）记在清单顶部，避免反复追问。

### 3. 解析输入，建"分层 + 模块"计划（codegen plan）
这是把 SAD 翻译成代码的关键中间步骤——**先有计划，再生成文件**，否则容易层次混乱、漏需求。
- **读 SAD（主驱动）**：若是 `.md` 直接读；只有 docx 时 `python3 scripts/extract_docx.py <sad.docx>`。从中抽：
  ① 分层架构图 → **层清单与层序**（哪层在上、哪层在下、哪些是横切层如 Types/Bus）；
  ② 组件分解与组件 ID → **每层有哪些模块**；
  ③ 组件 API / 接口表 → **每个模块的公开函数原型与契约**（线程安全/ISR 安全/阻塞时长/返回码语义）；
  ④ 状态机、时序图 → 模块内部行为与模块间交互（决定 `.c` 里的逻辑、`Tick` 周期、谁调谁）。
- **读 SRS**：拿到每条需求 ID（如 `*_SRS_*`）及其内容，记录"哪条需求由哪个模块/函数实现"——**追溯底座**。
- **读 SDK 代码根**：盘点已有的 BSP/MCAL/OS/RTOS API 与已存在的 HAL/驱动接口——生成代码要**对接这些已有接口**，
  不要重造；HAL 实现层（`.c`）就是调这些 SDK/驱动把抽象接口落到具体硬件。
- 把以上汇总成 `module_spec`（一份描述"层 + 模块 + 每模块接口/依赖/覆盖需求"的结构化清单）。schema 与字段说明见
  `assets/module_spec.schema.json`；同时产出 `layers.json`（层序 + 横切层 + 路径→层映射），供后续跨层核查用。
  `assets/` 下有 `module_spec.example.json` / `layers.example.json` 可参照（**仅示例，按真实 SAD 改写**）。

### 3.5 出分层架构图（可视化校验，建议每次做）
`layers.json` + `module_spec.json` 一建好，先出一张分层架构图，**在写代码前肉眼校验**它和 SAD 分层图对不对得上：
```bash
python3 scripts/render_layer_diagram.py --layers <layers.json> --spec <module_spec.json> \
    --out <输出基名> --title "<项目名> 软件分层架构"
```
绘图硬性要求见 `references/diagram-guide.md`：纵向逐层（左侧竖标签+紫标题条+模块卡片，可按 `group` 分组）；
**横切层（`cross_cutting`）必须画成右侧竖条、只跨它的使用者层**，不得塞成横向普通层。图与配置、代码**同源**——
不一致就回第 3 步改配置而非改图。出图后对照 SAD 分层图核一遍：层序、横切竖条范围、每层模块是否齐全正确。

### 4a. 脚手架模式：铺目录树 + 生成模块骨架
依据 `module_spec` + `layers.json` 生成分层目录与每模块骨架：
```bash
python3 scripts/scaffold_tree.py --spec <module_spec.json> --layers <layers.json> --out <代码根>
```
它为每个模块生成：`<Module>.h`（公开接口 + API 契约注释 + `@implements <需求ID>` 追溯标注 + 头文件保护）、
`<Module>_Cfg.h`（编译期配置占位）、`<Module>.c`（`#include` 仅含**相邻下层接口 + 同层 + 横切层**、函数桩 +
`/* TBD: ... */` 体）。生成后**人工/模型补全**头文件契约细节与目录 README，确保骨架可被编译器解析。
目录布局原则与命名规范见 `references/layering-rules.md` 与 `references/module-templates.md`。

### 4b. 逐模块模式：实现单个模块完整逻辑
1. 读目标模块的 SAD 章节 + 对应 SRS 需求 + 它声明依赖的下层接口头（`module_spec` 里的 deps）。
2. 在 `<Module>.c` 写完整逻辑：调下层接口完成功能；同层协作经总线/回调/对方公开接口（机制按产品场景选，
   见 `references/layering-rules.md` §4），下→上通知走回调或 EventBus；绝不 `#include` 上层、绝不直够更底层
   （要更底层能力就让相邻下层封装一个接口）。状态机/时序严格对齐 SAD。
3. MISRA 按构造写（见 `references/misra-c2012.md`）：显式类型与 `u/U` 后缀、入参 NULL/范围检查、`(void)` 标注
   丢弃返回值、无动态内存、单一退出或受控多退出、无隐式窄化转换、`switch` 带 `default`、布尔表达式不混用。
模块实现的骨架与契约写法见 `references/module-templates.md`。

### 5. 核查（生成后必跑，作为门禁）
```bash
# ① 跨层依赖核查：上层只依赖相邻下层 + 同层 + 横切层；任何向上/跳层 include 都报错
python3 scripts/check_layering.py --root <代码根> --layers <layers.json>
# ② MISRA 门禁（cppcheck 未装时先 `sudo apt-get install -y cppcheck`，自带 misra 插件）
python3 scripts/run_misra.py --root <代码根>
# ③（可选）主机侧编译烟雾测试：对纯逻辑/可打桩模块用 gcc 试编，快速抓语法/类型错
#    （硬件相关模块缺交叉工具链时跳过，靠 ①②③ + 人工核查）
```
①必须 0 违规；②把 cppcheck 的 Mandatory/Required 违规清零或登记为带理由的 deviation；③能编尽量编。
有违规就回第 4 步改，别带病往下走。

### 6. 一致性检查清单核验（req 7，收尾必做）
按 `references/conformance-checklist.md` 逐条核验生成结果是否符合本 skill 的设计要求（分层、模块化、不跨层、
可注入、目录清晰、MISRA、100% 追溯）。可自动跑：
```bash
python3 scripts/conformance_check.py --root <代码根> --spec <module_spec.json> --layers <layers.json> --srs <srs.md>
```
它聚合 check_layering / run_misra 结果、扫 `@implements` 追溯标注与 SRS 需求集求差、核对目录分层，输出一张
**通过/未通过 + 证据**的报告。**这张清单是迭代护栏**：代码后续被改动后，重跑它就能判断是否仍符合 skill 设计要求。
未通过项要么修代码、要么明确记为已知偏离。

---

## 参考资料（按需读）
- `references/layering-rules.md` — 通用分层模型、层间依赖规则（上层→相邻下层、不跨层、不向上）、HAL 接口/实现
  可注入的 If/Impl 拆分、同层解耦（信号/事件总线）、目录布局与命名规范、check_layering 的判定逻辑。
- `references/misra-c2012.md` — 与代码生成强相关、cppcheck 能查的 MISRA C:2012 规则清单（带"为什么"与按构造写法）、
  deviation 登记格式、cppcheck --addon=misra 用法。
- `references/input-checklist.md` — 各步骤需要什么输入、为什么、从哪来、缺了如何提示、能否 TBD/默认兜底 + 提示范例。
- `references/module-templates.md` — `.h` / `_Cfg.h` / `.c` 的骨架模板（API 契约注释、追溯标注、头文件保护、
  MISRA 友好写法），脚手架与逐模块都用它。
- `references/conformance-checklist.md` — 收尾的一致性检查清单（逐条可核查项 + 期望证据）。
- `references/diagram-guide.md` — 分层架构图绘制要求：纵向逐层卡片 + 横切层画成竖条跨使用者层，数据同源、用法。

## 脚本一览
- `discover_inputs.py` — 扫项目根，分类 SRS/SAD/SDK/通信矩阵/MISRA 等，报已找到 vs 缺失。
- `extract_docx.py` — 把 SAD/SRS 的 docx 结构化导出（标题+段落+表格）以便阅读。
- `scaffold_tree.py` — 按 module_spec + layers 生成分层目录与模块骨架（脚手架模式）。
- `render_layer_diagram.py` — 按 module_spec + layers 出卡片风格分层架构图（横切层自动画成竖条跨使用者层）；SVG，装 cairosvg 出 PNG。
- `check_layering.py` — 静态核查 include 依赖是否守层（上层→相邻下层/同层/横切，禁向上、禁跳层）。
- `run_misra.py` — `cppcheck --addon=misra` 包装，汇总 MISRA 违规。
- `conformance_check.py` — 跑完整一致性检查清单，输出通过/未通过+证据报告。

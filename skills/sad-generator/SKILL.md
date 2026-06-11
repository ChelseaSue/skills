---
name: sad-generator
description: >
  把软件需求规范（SRS，软件需求文档）转成符合公司模板（AU-QR-R&D-032 软件架构设计规格说明书 /
  Software Architecture Design Specification）的软件架构文档 SAD。无论用户说"软件需求转软件架构""生成
  软件架构设计/SAD/架构文档""按 AU-QR-R&D-032 模板写软件架构""从 SRS 派生软件架构""software architecture
  design specification from SRS"，还是问"做软件架构还缺哪些文档/输入/信息"，都应使用本 skill。即使用户没明说
  "用模板"或"按 SAD"，只要是从软件需求规范往下推导软件架构（分层架构、组件分解、状态机、时序图），或询问软件
  架构需要哪些输入，也要触发。本 skill 会先做缺失输入提示，自动发现同项目补充文档，全力起草 SAD（缺信息处用
  【TBD】标注），先出 Markdown（图统一用 PlantUML 源码），最终把图渲染成 PNG 并克隆模板 docx 输出；并强制
  做需求→架构的 100% 追溯核验。三类必含图：软件分层架构图、软件状态机图、各功能动态时序图（标注真实 CAN 信号）。
  区分：`srs-generator` 产出的是软件"需求规范"（SRS，上游）；`swdd-generator` 产出的是软件"详细设计"（SWDD，
  下游，基于源码）；本 skill 产出的是中间层——软件"架构设计"（SAD）文档。
---

# SAD 生成器（软件需求 SRS → 软件架构设计 SAD）

把按"软件组件(SWC)需求"组织的 SRS，转成一份**软件架构设计规格说明书**：分层架构、组件分解与接口、
实时/内存/鲁棒性设计、各功能的动态时序，并保证**每条软件需求都在架构中有去向**。

文档链：系统需求 →（`srs-generator`）→ **SRS** →（**本 skill**）→ **SAD** →（`swdd-generator`）→ SWDD。

这不是格式转换：SRS 说"软件要做什么"，SAD 说"软件怎样搭起来去满足这些需求"。模板里大量内容（RTOS/调度选择、
CPU 负载、内存映射、NVM 设计、中断/任务划分、看门狗、组件 API、部署视图……）是**设计决策**，SRS 里没有。
所以**先盘点缺什么，再起草，缺的地方明确标 TBD**，并把判断权交还用户。

## 何时用、产出什么
- 输入：一份 SRS（优先 Markdown，其次 docx，**主输入**）+ AU-QR-R&D-032 软件架构模板（.doc/.docx）+
  通信矩阵（CAN/LIN，供时序图标注真实信号）+ 同项目其它文档（本 skill 自动发现）。
- 中间产物：**中文 Markdown 版 SAD**，所有图以 **PlantUML 源码**内嵌（```plantuml``` 代码块）。
- 最终产物（按需）：把 PlantUML 图渲染成 PNG、克隆模板 docx 填充后的 `.docx`。
- 语言：**统一中文**。模板原文是中英双语，只借它的结构，不照抄英文。

## 三条硬性要求（用户明确，务必满足）
1. **调用即先做缺口提示**（见第 2 步）——动手生成前先点出"SRS 之外还缺什么"。
2. **100% 可追溯覆盖 SRS**——每条 `HOD_SRS_*` 软件需求都要在 SAD 里落到某个组件/时序/章节；结尾给全量追溯
   矩阵；用 `trace_check.py` 核验未覆盖集为空。
3. **三类必含图，统一用 PlantUML**——① 软件分层架构图（→7.2.1）② 软件状态机图（→5.3/5.4）③ 各功能动态
   时序图，**标注实际使用的 CAN 信号名+报文ID+收发方向**（→第 9 章）。

## 工作流（6 步，按顺序做，第 2 步不可跳过）

### 1. 定位输入
确认 SRS（优先 `.md`）、AU-QR-R&D-032 模板、通信矩阵的路径。运行发现脚本扫描同项目补充文档：
```bash
python3 scripts/discover_inputs.py <项目根目录>
```
它按目录/文件名分类（SRS/架构模板/通信矩阵/系统需求/产品需求/HSI/外设/硬件架构…），输出"已找到 vs 缺失"，
并列出**通常无文件可扫的"设计决策类"输入**供第 2 步点名。若用户只给一个文件没给项目根，以该文件目录的上一级当根。

### 2. 缺口提示（调用时必做——这是用户的硬性要求）
**在动手生成之前**，先给用户一张"SAD 所需输入 vs 已找到 vs 缺失"清单，明确点出**SRS 之外还缺什么**，
请用户补充、或确认"以 TBD 占位继续"。为什么必须先做：SAD 模板要求 RTOS/调度选择、CPU 负载预算、内存映射、
NVM 数据字典、中断/任务划分、看门狗策略、组件 API 契约、部署视图等——这些 SRS 里没有；闷头生成会编造或静默
漏掉。把判断权交还用户。

**尊重用户已定的范围决定**：本项目 SRS 已确认"**功能安全本期不考虑**"——ASIL 相关一律填 `NA（本期不涉及
功能安全）`，不要满屏 `【TBD-待 HARA】`、不要把它再当缺口。同理"通信矩阵已补充"——时序图直接用真实信号。
把这些已确认的范围决定记在缺口清单顶部，避免反复追问。

缺口判断细节见 `references/input-checklist.md`，含给用户的提示输出范例。

### 3. 解析输入
- **SRS（主输入）**：若是 `.md`，直接读——它已是结构化中文，含每条 `HOD_SRS_*` 需求表（13 字段）、SWC 清单
  （3.7.1）、逐信号 CAN 表（3.5/3.6）、覆盖自检表。若只有 docx：`python3 scripts/extract_docx.py <srs.docx>`。
- **通信矩阵 → 信号查找表**（时序图要用）：
  ```bash
  python3 scripts/parse_can_matrix.py <通信矩阵.xlsx>            # 报文/信号/起始位/收发方向
  python3 scripts/parse_can_matrix.py <通信矩阵.xlsx> --signal OXY_Status_Concentration  # 单信号速查
  ```
  它能恢复每个报文的**收发方向**（如 0x201 控制 整车→制氧机、0x203 状态 制氧机→整车），决定时序图箭头朝向。
- **HSI 逐一核对软件外部接口（§3.5 关键，别照搬 SRS）**：用 openpyxl/pandas 读 `HSI/*端口定义*.xlsx`
  （连接器→信号）与 `HSI/*管脚定义*PINMUX*.xlsx`（MCU 网络端口名）。**§3.5 软件外部接口必须对照 HSI 逐一列全**
  ——SRS 的接口章节常是节选且可能有错。本项目实测到的典型坑：① PM2.5 走独立内部 CAN（CAN1）不是 ADC；
  ② 车身 CAN0 引脚以 PINMUX 实配为准（SRS 写的可能是未用的 ALT 脚）；③ 流量阀是步进电机不是 PWM；④ 压缩机是
  6 路 BLDC/FOC PWM + 相/母线电流采样。**冲突时以 HSI 为准**，并在 §3.5 末尾注明"与 HSI 核对的更正"。
- **模板骨架核对**：`python3 scripts/extract_docx.py <032模板.docx> --headings`（.doc 先 `soffice --headless
  --convert-to docx` 转一次）。章节树与各表 schema 已整理在 `references/template-structure.md`。
- **复用源图**：SRS 已有的系统框图/产品外形图在其 `srs_images/` 里，可直接 `![](…)` 引用，不必重画。

### 4. 架构推导 + 建追溯底座
- **分层归位**：把 SRS 的 SWC（MCU/IN/OUT/COM + O2/ION/SCN/SWT/HMI/SAFETY/PWR/DIAG/CAL/GAS）归入分层
  子系统：应用层 APP（O2/ION/SCN/SAFETY/GAS…）/ 服务层 SVC（PWR/DIAG/HMI/COM 协议…）/ 硬件抽象层 HAL /
  芯片抽象 MCAL / OS。给每个组件定**组件 ID**。
- **建追溯映射**：为每条 `HOD_SRS_*` 记下"实现于哪个组件 / 体现在哪张时序图或状态机 / 落在 SAD 哪一章节"。
  这是结尾追溯矩阵的数据底座。一条需求可由多个组件/时序共同实现；不要丢需求。
- 详见 `references/template-structure.md`（追溯矩阵列定义）。

### 5. 生成 Markdown SAD
严格按 032 九大章结构（见 `references/template-structure.md`）输出中文 Markdown，**所有图用 PlantUML 源码**
（```plantuml``` 或 `@startuml`）。画法见 `references/diagram-guide.md`：
- **软件分层架构图**（7.2.1）：PlantUML `package`/component 分层，APP→SVC→HAL→MCAL→OS，各 SWC 落层、层间依赖。
- **软件状态机图**（5.3 + 5.4）：PlantUML `state`，**两层 + 三段式**（详见 `diagram-guide.md`）。5.3 全局运行
  模式机（初始化/运行/故障降级/休眠，功能无关、统一门控；休眠判据要"功能感知"——**所有功能空闲且总线静默才休眠**，
  否则按键单独开的香氛/负离子会被误关）。5.4 各功能并行模式机（O2/ION/SCN/GAS/SWT/SAFETY 各一台，**不合并成组合
  大机**；按键>CAN>UART 仲裁放指令层）。每个状态机小节都给 **状态机图（连线仅标序号 C/F）+ 状态说明表 +
  状态转移条件表 + 设计要点**。
- **各功能动态时序图**（第 9 章）：PlantUML `sequence`，**每个功能模块一张**（O2/PWR/DIAG/ION/SCN/SWT/HMI/
  SAFETY/GAS）+ 模板固有的初始化/休眠/唤醒时序。participant 用 整车/App/COM/各 SWC/执行器；箭头标**真实
  CAN 信号**：`整车 -> COM : 0x201 OXY_Seat1_Ctrl_Nasal_Gear`、`COM -> 整车 : 0x203 OXY_Status_Concentration`
  （信号名/报文ID/方向取自 `parse_can_matrix.py`）。
- **追溯**：每个组件定义、每张时序图、每个架构元素都**标注它实现/覆盖的 `HOD_SRS_*`**；结尾给**全量追溯矩阵**
  （每条 SRS 需求 → 实现组件/子系统 → 相关时序/状态机 → SAD 章节 → 状态 ✅/🟡预留/🔩硬件域），镜像 SRS 的
  覆盖自检表风格。
- 缺信息处统一写 `【TBD-待补充：<具体需要什么>】`，不要编造数值；备选方案（第 6 章）缺真实评审记录时写
  "建议方案，待软件架构评审确认"。
- **交付物口吻**：缺口分析、gap 报告、"项目无 XX 文档"这类话只属于缺口提示，**不要写进 SAD 正文**。
默认输出到 `软件架构/多功能制氧机软件架构设计_draft.md`（或用户指定路径）。

### 6.（按需）生成最终 docx + 追溯核验
用户说"出 docx / 转成 Word / 生成最终文档"时：
```bash
# 渲染图：rendered-md 要和 --outdir 在同一目录，否则图片相对路径对不上、贴不进 docx（踩过的坑）
python3 scripts/render_diagrams.py <sad.md> --outdir 软件架构/sad_images \
    --rendered-md 软件架构/<同名>.rendered.md
python3 scripts/build_sad_docx.py 软件架构/<同名>.rendered.md --template <032模板.doc/.docx> --out <输出.docx>
soffice --headless --convert-to pdf <输出.docx>                                    # "能否打开"烟雾测试
python3 scripts/trace_check.py --srs <srs.md> --sad <sad.md>                        # 必跑：未覆盖须为 0
```
`build_sad_docx.py` 以模板为基底克隆，填章节、克隆表格、插入 PNG；`.doc` 模板会自动先转 `.docx`。它已内置两个
公司模板的坑修复：① 按**样式名**解析 Heading（python-docx 默认按 styleId 查会漏，导致标题退化成正文、丢目录层级）；
② **抑制 Heading 样式自带的多级自动编号**（否则与正文手写的 `4.1` 叠加成"3.1 4.1"乱号）。要修一份已有的 docx 编号，
单独跑 `python3 scripts/fix_heading_numbering.py <file.docx>`。
**`trace_check.py` 必须跑通且未覆盖集为空**（需求 ID 前缀随 SRS，脚本默认前缀无关，自动识别 `OXY_SRS_`/`HOD_SRS_`），
否则回到第 5 步把漏掉的需求补进对应组件/时序/章节。

## 参考资料（按需读）
- `references/template-structure.md` — 032 九大章节树 + 组件定义表/组件 API 表/内存映射表/追溯矩阵的字段 schema。
- `references/diagram-guide.md` — 三类 PlantUML 图（分层架构/状态机/带 CAN 信号的时序图）的画法、骨架与约定。
- `references/input-checklist.md` — 每章需要什么、为什么、从哪来、缺了如何提示、能否 TBD 兜底 + 提示输出范例。

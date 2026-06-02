---
name: srs-generator
description: >
  把系统需求文档（System Requirements）转成符合公司模板（AU-QR-R&D-027 软件需求规范 / Software
  Requirements Specification）的软件需求规范 SRS。无论用户说"系统需求转软件需求""生成 SRS/软件需求规范/
  软件需求文档""按 AU-QR-R&D-027 模板写软件需求""从系统需求派生软件需求""software requirements
  specification from system requirements"，还是问"做软件需求还缺哪些文档/输入/信息"，都应使用本 skill。
  即使用户没明说"用模板"或"按 SRS"，只要是从系统需求/产品需求文档往下推导软件层需求、或询问 SRS 需要哪些输入，
  也要触发。本 skill 会先做缺失输入提示，自动发现同项目补充文档，全力起草 SRS（缺信息处用【TBD】标注），先出
  Markdown（图用 mermaid/plantuml），最终可渲染成 PNG 并克隆模板 docx 输出。区分：`swdd-generator`
  产出的是软件"详细设计"（SWDD），`stakeholder-requirements-extractor` 回填的是干系人需求 Excel；
  本 skill 产出的是软件"需求规范"（SRS）文档。
---

# SRS 生成器（系统需求 → 软件需求规范）

把按"系统功能"组织的系统需求文档，转成按"软件组件(SWC)"组织、每条需求是结构化需求表的 SRS。
两者的组织维度不同，且模板里有很多系统需求文档没有的信息（ASIL/功能安全、网络安全、软件架构分解、
NVM、Bootloader、编码规范……）。所以这不是简单格式转换：**先盘点缺什么，再起草，缺的地方明确标 TBD。**

## 何时用、产出什么
- 输入：一份系统需求 docx（必给）+ 同项目其它文档（本 skill 自动发现）+ 一份 SRS 模板 docx。
- 中间产物：**中文 Markdown 版 SRS**（图用 mermaid/plantuml 代码块）。
- 最终产物（按需）：把图渲染成 PNG、克隆模板 docx 填充后的 `.docx`。
- 语言：**统一中文**。模板原文是中英双语，只借它的结构，不照抄英文。

## 工作流（6 步，按顺序做，第 2 步不可跳过）

### 1. 定位输入
确认系统需求 docx 与 SRS 模板 docx 的路径。运行发现脚本扫描同项目补充文档：
```bash
python3 scripts/discover_inputs.py <项目根目录>
```
它会按目录/文件名分类（系统需求/产品需求/HSI/外设/硬件架构/原理图/模板），输出"已找到 vs 缺失"清单。
若用户只给了一个文件、没给项目根，就以该文件所在目录的上一级作为项目根来扫。

### 2. 缺口提示（调用时必做——这是用户的硬性要求）
**在动手生成之前**，先给用户一张"SRS 所需输入 vs 已找到 vs 缺失"清单，明确点出**系统需求文档之外还缺什么**，
并请用户补充、或确认"以 TBD 占位继续"。为什么必须先做：SRS 模板要求 ASIL、软件架构分解、NVM、安全等信息，
系统需求文档里这些被标"预留"或根本没有；如果闷头生成，会编造或静默漏掉，反而误导。把判断权交还用户。

**尊重用户的"本期不考虑"决定**：如果用户明确说某一项本期不做（最常见的是"功能安全/ASIL 先不考虑"），
就不要再把它当缺口、也不要满屏 `【TBD-待 HARA】`。把相关字段填 `NA（本期不涉及功能安全）`、相关章节（如 5.7
安全性、2.2 ASIL 列）写一句"本期不涉及功能安全，待立项后补充"即可。同理用户补充了某份输入（如通信矩阵），
就把对应缺口划掉、改用真实数据填充。下次调用时把这些已确认的范围决定记在缺口清单顶部，避免反复追问。

缺口判断细节见 `references/input-checklist.md`。下面是速查（本项目典型情况）：

| SRS 章节 / 字段 | 需要的输入 | 常见来源 | 典型状态 |
|---|---|---|---|
| 功能列表 ASIL 级别、功能安全需求 | HARA / 安全概念 | 系统文档多标"预留" | **缺失** → 提示 |
| 网络安全需求 | TARA | 系统文档多标"预留" | **缺失** → 提示 |
| 软件架构 / SWC 分解 / 功能间接口 | 软件架构文档 | 一般没有 | **缺失** → 由本 skill 初步推导并标 TBD |
| HSI 软硬件接口、信号映射 | 端口/管脚定义 | `HSI/` | 多为可用 |
| 各 I/O 的 范围/单位/来源/目标 | 外设参数 / HSI | `外设/`、`HSI/` | 部分可用 |
| 产品定义 / 功能列表 / 产品背景 | 产品需求 | `产品需求/` | 多为可用 |
| 硬件框图 | 架构图 | `硬件架构/*.vsdx` | 可用（脚本自动转 PNG） |
| 通信管理 / 通信矩阵 | CAN DBC / LIN LDF | `通信矩阵/` 或系统文档协议描述 | 有矩阵则可用（逐信号填 3.5/3.6），否则部分 |
| NVM / Data flash 内容 | 标定/存储定义 | 一般没有 | **缺失** → 提示 |
| Bootloader 版本 | Boot 说明 | 一般没有 | **缺失** → 提示 |
| 实时约束 / CPU 负载 / 内存预算 具体值 | 资源预算 | 系统文档部分有 | 部分 |
| 编码 / 文件命名 / 设计规范 | 公司规范文档 | 一般没有 | **缺失** → 提示（可引用公司标准编号占位）|
| 测试方式 / 验证标准 | 测试策略 | 一般没有 | 推导并标 TBD |

### 3. 解析输入
把 docx 抽成结构化文本再读，别靠肉眼翻原文：
```bash
python3 scripts/extract_docx.py <系统需求.docx>            # 系统功能、接口/引脚、CAN协议、非功能需求
python3 scripts/extract_docx.py <模板.docx> --headings      # 只看模板章节骨架时加 --headings
```
重点抽取：系统功能清单（含 `SR-xx-xxx` 需求 ID）、接口/引脚定义、电源状态、性能/质量/物理需求。
HSI/外设是 xlsx，用 `xlsx` skill 或 pandas 读信号、管脚、负载参数。

### 4. 映射（系统功能 → 软件组件 SWC）
依据 `references/mapping-guide.md` 把系统功能拆到软件模块（如 制氧→O2 浓度闭环 + 压缩机 BLDC/FOC；
电源管理→PWR；故障诊断→DIAG；物理按键→Switch Input；App→BLE/HMI；安全保护→SAFETY）。
**关键：每条软件需求的"覆盖需求 Covered Req"字段要回链到来源 `SR-xx-xxx`**，保住可追溯性。
Req ID 默认沿用模板的 `HOD_SRS_<MODULE>_NNN`（模块名按 SWC 取，如 `HOD_SRS_O2_001`）。

### 5. 生成 Markdown SRS
严格按模板 7 大章节结构（见 `references/template-structure.md`）输出中文 Markdown：
- 框图/功能关系图 → mermaid（``` ```mermaid ```）或 plantuml（``` ```plantuml ```）代码块。
- **复用源文档里的图**：系统需求文档里已有的系统框图、产品外形图、引脚图等，不必重画——用
  `python3 scripts/extract_docx.py <系统需求.docx> --extract-images <软件需求/srs_images>` 把内嵌图按章节抽出来，
  挑出需要的（如"系统框图"那张），在 md 里用 `![系统框图](srs_images/系统框图.png)` 引用。生成 docx 时会自动贴进去。
  比起用 mermaid 重绘，直接引用原图更准、更省事；mermaid 适合画原文没有的软件视角逻辑图。
- 每条需求写成需求表，**含模板全部 13 个字段**（需求ID/标题/描述/类型/成熟度/变体/分配/测试/ASIL/功能/验证标准/覆盖需求/发布计划）。
- 缺信息处统一写 `【TBD-待补充：<具体需要什么>】`，不要编造数值或 ASIL 等级。
- **SRS 正文用交付物口吻**：缺口分析、`gap_report`、"项目无 XX 文档（见 G3）"这类话只属于缺口清单，**不要写进 SRS 正文**。正文里缺信息就用中性措辞——`【TBD-待补充：…】` 或"建议性方案，待评审确认"，不要在交付文档里自我批评或交叉引用缺口报告编号。
默认输出到 `软件需求/多功能制氧机软件需求规范_draft.md`（或用户指定路径）。

### 6.（按需）生成最终 docx
用户说"出 docx / 转成 Word / 生成最终文档"时：
```bash
python3 scripts/render_diagrams.py <srs.md> --outdir <图片目录>      # mermaid/plantuml/vsdx → PNG
python3 scripts/build_srs_docx.py <srs.md> --template <模板.docx> --out <输出.docx> --img <图片目录>
```
`build_srs_docx.py` 以模板为基底克隆，填章节、克隆需求表、插入 PNG。完成后用
`soffice --headless --convert-to pdf <输出.docx>` 做一次"能否打开"的烟雾测试。

## 参考资料（按需读）
- `references/template-structure.md` — 模板 7 大章节树 + 需求表/IO表/功能列表表的字段 schema。
- `references/input-checklist.md` — 每个章节需要什么、为什么、从哪来、缺了如何提示、能否 TBD 兜底。
- `references/mapping-guide.md` — 系统功能↔SWC 映射建议、Req ID 规则、覆盖需求追溯、TBD 文案约定。

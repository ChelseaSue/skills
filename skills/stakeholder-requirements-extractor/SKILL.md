---
name: stakeholder-requirements-extractor
description: 将客户/法规/合同/矩阵/模板文档中的干系人需求整理为结构化条目，并回填到类似“相关方需求分析表”的 Excel 模板中。用户只要提到“干系人需求”“相关方需求分析表”“stakeholder requirements”“从输入文档清单整理需求”“把 PDF/Word/Excel 章节拆成条目”“回填需求分析表”“从 ESOW/SOW/SRS/Compliance Matrix 提取条目”等场景，就应该使用这个 skill，哪怕用户没有明确说“做一个 skill”或“按模板回填”。当输入是 Excel 模板、输出仍是 Excel 模板，且需要解析多个源文档、识别章节、按条目回填时，也要优先触发。
---

# Stakeholder Requirements Extractor

把多份输入文档整理成“干系人需求条目”，并稳定回填到 Excel 模板。

这个 skill 适合汽车电子、ASPICE、SOW/SRS/ESOW、合规矩阵等文档，但也可泛化到其他“从输入文档清单抽取条目并回填模板”的任务。

需要细看字段映射时，读取 [references/field-mapping.md](references/field-mapping.md)。
需要细看误拆、软换行、OCR 断句、matrix 拆分案例时，读取 [references/splitting-cases.md](references/splitting-cases.md)。
需要直接运行可复用脚本时，读取 [scripts/README.md](scripts/README.md) 并优先使用 [scripts/fill_stakeholder_requirements.py](scripts/fill_stakeholder_requirements.py)。

## 适用目标

让模型完成下面这类工作：

- 从 Excel 模板里的“输入文档清单”筛选适用文档
- 自动匹配实际文件
- 解析 PDF、Word、Excel、矩阵、模板类文档
- 将章节、小标题、编号项、说明段落、要求项整理成条目
- 回填到“相关方需求分析表”或同类模板
- 在解析受限时，走 OCR 兜底

## 先做什么

1. 先读模板工作簿，确认：
   - 输入文档清单所在 sheet
   - 目标回填 sheet
   - 表头名称和列位置
2. 再筛选输入文档：
   - 默认按“是否适用=是”
   - 默认忽略 `*.dbc`、`*.ldf`
   - 若清单名和实际文件名不完全一致，但只有唯一候选文件，视为同一文档
   - 若同一文档在清单中重复出现，默认只保留一次，除非用户要求保留重复来源
3. 回填前务必备份原 Excel。

## 文档匹配规则

优先级按下面顺序：

1. 文件名完全匹配
2. 主文件名匹配（忽略扩展名）
3. 规范化匹配：
   - 统一中英文破折号
   - 忽略空格、下划线、大小写差异
4. 名称不完全一致但只有唯一候选文件时，直接采用该文件

若出现多个候选而用户没有额外规则，优先：

- 用户当前项目目录下的正式版本
- 路径里更接近文档清单备注/章节名的文件
- `定点前ESOW`、正式发布目录、非临时文件

## 支持的输入类型

- PDF
- DOCX / DOC / DOCM
- XLSX / XLSM / XLS
- 无扩展名但实际是 Office/PDF 的文件

## 解析总原则

目标不是“只抽要求句”，而是“把整份文档映射成条目”。

每个条目都要尽量对应原文中的一个稳定结构单元：

- 文档标题
- 一级章节
- 二级章节
- 编号条款
- 说明段
- Note / Purpose / Scope
- 表格中的编号要求行

不要为了压缩条目数而粗暴合并整章。
也不要因为 PDF 自动换行而把同一段拆成多条。

## 条目拆分规则

### 1. 标题类

下面这些通常单独成条，`类型=标题`：

- 文档主标题
- 章节标题
- 小标题
- Excel/Matrix 的 sheet 名
- 编号型标题，如 `3.1 AUTOSAR`、`6. Coding Rules`

### 2. 信息类

下面这些通常单独成条，`类型=信息`：

- Purpose / Scope / Description / Note 等说明段
- 章节下的前置说明文字
- 不属于明确要求、但需要保留的背景说明

### 3. 需求类

下面这些通常单独成条，`类型=需求`：

- 含 `shall` / `must` / `required` / `应` / `必须` / `不得` 等明确约束的句子
- 末级编号要求项，如 `3.1.2.1`
- 表格或矩阵中的 requirement 行
- 列表项中明显独立的要求

## 段落合并规则

PDF、OCR、Word 表格导出后，常会把同一段拆成多行。必须先判断是否是“软换行”，再决定是否合并。

优先合并这些情况：

- 上一行没有句号结束，下一行不是新标题/新编号项
- 下一行明显是上一行的续写
- 上一行以 `for each`、`to`、`with`、`and`、`or`、冒号、逗号等结尾
- PDF 把一个句子折成两三行
- 列表项正文被折行

不要合并这些情况：

- 新章节标题
- 新编号项
- 明确的表头
- 新的 sheet 区块
- 明显属于封面元数据的行

如果已经生成了条目，仍发现相邻两条其实属于同一段，可以在“条目层”再做一次相邻合并。

## OCR 兜底

当原生解析出现下面任一情况时，尝试 OCR 或版式兜底：

- PDF 只提取出页眉页脚
- 提取结果缺页、缺段
- 正文几乎为空但视觉上可读
- 章节结构明显存在，但文本提取失败

OCR 后仍按原文结构拆分：

- 优先识别编号层级，如 `1.`、`1.2.`、`3.1.1.`
- 若层级不稳定，则按视觉标题块 + 正文块拆条
- 若列表项可识别，则逐项拆开

## Excel / Matrix 文档处理

矩阵文件不要默认忽略。只有 `*.dbc` 和 `*.ldf` 忽略。

对矩阵/模板/Compliance Matrix：

- sheet 名单独成 `标题`
- 区块标题单独成 `标题`
- Note、说明、前提段落记为 `信息`
- 末级 requirement 行记为 `需求`
- 编号列如 `3.1.1.1` 可直接作为 `条款/章节`
- 响应列、审批列、备注列只有在本身属于原始要求时才纳入正文

空白占位字段不要回填成条目，例如：

- `Project:`
- `Module Name:`
- `Supplier Name:`
- 仅字段名、无实际值的元数据行

## 封面元数据处理

纯封面元数据通常不进表，例如：

- Document name
- Issuer
- Version
- Date
- Reg. No.
- Security class
- Project / Supplier / Module Name 等空白字段

但如果这些字段本身被用户明确要求保留，则按用户要求处理。

## 回填和分类

字段映射、类型/类别规则、默认值、`相关方ID` 的适用范围，统一遵守 [references/field-mapping.md](references/field-mapping.md)。

## 写 Excel 时的要求

- 先备份原始工作簿
- 保留现有表头、样式、模板结构
- 使用模板示例行复制样式
- 只清理和重写数据区，不改封面和历史页
- 不要破坏现有合并单元格、列宽、样式

## 常见坑

误拆、误并、标题误判、列表折行、matrix 区块拆分等具体案例，统一参考 [references/splitting-cases.md](references/splitting-cases.md)。

## 推荐工作流

1. 读取模板和表头
2. 筛选适用文档
3. 匹配实际文件
4. 解析每份文档
5. 先做行级清洗和段落重建
6. 再拆分成条目
7. 再做相邻续行合并
8. 分类 `类型`
9. 仅对 `需求` 分类 `类别`
10. 回填 Excel
11. 抽查关键样例：
   - PDF 段落是否误拆
   - OCR 文档是否恢复编号结构
   - Matrix 文档是否保留章节和末级要求
   - `标题/信息` 的 `类别` 和 `相关方ID` 是否为空
   - 同一段被 PDF 折行的内容是否已重新合并

## 输出检查清单

交付前至少确认：

- 没有漏掉适用文档
- `*.dbc` / `*.ldf` 已忽略
- `标题/信息` 的 `类别` 为空
- `标题/信息` 的 `相关方ID` 为空
- 原文没有被截断
- 明显属于同一段的软换行已合并
- 关键章节标题和末级要求都已体现

## 示例

**示例 1：PDF 段落**

输入：

- `Purpose of the ‘ESOW – Material Sheet’ document`
- 下一段正文被 PDF 切成两行

输出：

- 1 条 `标题`
- 1 条完整正文 `需求/信息`

不要输出成两条断裂句子。

**示例 2：Coding Rules**

输入：

- `6. Coding Rules`
- 下有 1..10 编号项

输出：

- `6. Coding Rules` 作为 1 条 `标题`
- 10 个编号项各自作为 10 条 `需求`

**示例 3：Compliance Matrix**

输入：

- sheet `Compliance Matrix`
- `3.1 AUTOSAR`
- `3.1.1.1 Licensing and availability...`

输出：

- `Compliance Matrix` -> `标题`
- `3.1 AUTOSAR` -> `标题`
- `3.1.1.1 ...` -> `需求`

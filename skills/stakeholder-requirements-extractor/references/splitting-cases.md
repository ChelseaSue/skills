# Splitting Cases

这个文件记录常见误拆、误并、OCR 断句、matrix 拆分案例。

## 目标

条目拆分的目标是：

- 完整覆盖文档内容
- 保持原文结构
- 避免把同一段拆碎
- 也避免把多个独立要求糊成一条

## Case 1: PDF 软换行导致同一段被拆成两条

**原文视觉效果：**

`The ‘ESOW - Material Sheet’ document is part of the ESOW contract and defines the Buyer Company’s Material`

`Sheet requirements. This attachment works together with Volvo Cars CAD Standard ...`

**正确处理：**

合并成一条。

**原因：**

- 第一行未结束
- 第二行不是新标题、不是新编号项
- 第二行明显是上一行句子的续写

## Case 2: 段落说明被 PDF 折成两三行

**示例：**

`A prerequisite for handling the applied material from Supplier is that the material is registered in Buyer`

`Company’s Material Catalogue. To start register a new material in Buyer Company’s Material Catalogue, ...`

**正确处理：**

合并成一条完整正文。

## Case 3: 列表起始说明 + 列表正文续行

**示例：**

`The Supplier is responsible to ensure requested Material Sheet is available to the Buyer Company, for each`

`material applied to the component: • Check if chosen material is available within Buyer Company’s Material List* or CATIA Material`

`Catalogue**.`

**正确处理：**

这三行应重建为一条连续说明，不要拆成 2 到 3 条碎片。

## Case 4: 标题不能并进正文

**示例：**

`6. Coding Rules`

`The following coding rules shall be followed:`

`1. A software delivery may only include OSS ...`

**正确处理：**

- `6. Coding Rules` -> 单独 1 条 `标题`
- `The following coding rules shall be followed:` -> 单独 1 条 `信息/需求`
- `1.` 到 `10.` -> 各自独立成条

## Case 5: 标题下的编号项必须展开

**示例：**

`6. Coding Rules` 下有 `1` 到 `10`。

**错误处理：**

- 合并成 2 条或 3 条摘要

**正确处理：**

- 标题 1 条
- 编号子项 10 条

## Case 6: Matrix 文件不能整表一条

**示例：**

`SWSOW A - 2.1.xls`

有：

- `Compliance Matrix` sheet
- `3.1 AUTOSAR`
- `3.1.1.1 Licensing and availability...`

**正确处理：**

- `Compliance Matrix` -> `标题`
- `3.1 AUTOSAR` -> `标题`
- `3.1.1.1 ...` -> `需求`

不要把整个 sheet 合成 1 条。

## Case 7: 空白占位字段不要入表

**示例：**

- `Project:`
- `Module Name:`
- `Supplier Name:`

如果没有实际值，这些是模板占位，不应回填为条目。

## Case 8: 封面元数据不要误入正文

**示例：**

- `Document name`
- `Issuer`
- `Version`
- `Date`
- `Reg. No.`
- `Security class`

**正确处理：**

默认不进表。

## Case 9: OCR 恢复后优先按层级拆，而不是按视觉块粗分

如果 OCR 后能识别：

- `1.`
- `1.2.`
- `3.1.1.`

则优先按这些编号拆分。

只有在层级确实不稳定时，才退回到“视觉标题块 + 正文块”拆法。

## Case 10: `标题/信息` 的联动规则

如果条目类型是：

- `标题`
- `信息`

则：

- `类别` 留空
- `相关方ID` 留空

只有 `需求` 才继续识别 `类别` 和 `相关方ID`。

## Case 11: 相邻条目层面的二次合并

有时候行级合并还不够，已经生成条目后仍可能出现：

- 同文档
- 同章节
- 相邻两条都不是标题
- 后一条明显是前一条续写

这时可以在“条目层”再做一次相邻合并。

适合二次合并的信号：

- 前一条没有句号结束
- 后一条首字母小写
- 前一条以 `for each`、`to`、`with`、`and`、`or` 等结尾
- 两条属于同一 `clause_desc`

## Case 12: 不要为了修误拆而误并整页

如果规则太宽，容易把下面这些糊到一条里：

- 文档标题
- 封面元数据
- 正文第一段

这是错误的。

修段落合并时，必须同时保证：

- 封面元数据不并进正文
- 标题不并进正文
- 新编号项不并进上一条


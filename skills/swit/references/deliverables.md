# 交付物

| 文档 | 模板 | 生成 | 主要数据来源 |
|---|---|---|---|
| 软件集成和集成测试策略 | AU-QR-R&D-050（.doc 自动转换） | `draft_docs.py` → `ws/docs/strategy_content.json` → `build_docx.py` | 配置、arch_model（集成对象 + 四类锚点清单）、用例统计、工具版本 |
| 软件集成测试指南 | AU-QW-R&D-56 | 同上（guide） | 接口清单、执行步骤、记录清单 |
| 软件集成测试用例 | AU-QR-R&D-052（.xls 自动转换） | `build_xlsx.py --what cases` | cases.json（Active） |
| 软件集成测试追溯矩阵 | AU-QR-R&D-022 | `--what trace` | 接口/动态行为/资源/性能 × 正向/反向 8 个 sheet + 统计 |
| 软件集成测试记录 | AU-QR-R&D-236 | `--what record --round N` | round_N.json（首轮/执行轮） |
| 软件集成回归测试记录 | AU-QR-R&D-237 | `--what regression --round RN` | round_RN.json（回归轮） |
| 软件集成测试报告 | AU-QR-R&D-238 | `--what report --rounds 1 R1 …` | 各轮结果、覆盖率、缺陷清单、设计覆盖 |

软件集成记录 AU-QR-R&D-235（A04 集成与冒烟）是人工活动；报告第 2 节默认写【TBD-取自 235】，或在配置 `integration.rounds` 中提供后自动填写。

## 文件名

`output.names`（默认按 BBS 实例）：`{project}-Software Integration Test Cases.xlsx`、`…Test Records_{round}.xlsx`、`…Regression Test Records_{round}.xlsx`、`…Test Report_{round}.xlsx`、`…Trace the matrix-SWE.5.xlsx`、策略/指南 docx。轮次：首轮 `1`、执行轮 `2…`、回归轮 `R1…`。

## 计数口径（rounds.py，所有文档共用）

- 判定：pass / fail / na / blocked / skipped / not_run。下拉文字取模板数据验证（`通过P,失败F,用例不适用NA,阻塞B,跳过S`）。
- `na` 只允许用于 `execution=swe6`（转 SWE.6）；这些用例单列，不进执行率/通过率分母，022 视为已追溯。
- 执行率 = 已执行（pass+fail）/ 选择（不含 swe6）；通过率 = pass / 已执行。未执行永不计通过。
- 报告第 1 节：设计时覆盖（有用例的锚点 / SAD 锚点）与执行结果分列；多轮时以最终有效判定（回归覆盖首轮）计算。
- 报告结论：KPI 全达且无未关缺陷 → Pass；KPI 达但有非 A/B 级未关缺陷 → Conditional Pass；否则 Not Pass。

## 模板适配（换模板版本不改代码）

- 模板按文档编号通配找，同目录多版本取最高。
- xlsx：按表头文字定位列与 sheet；样例行清空；超出模板样式行时复制首数据行样式；下拉验证范围随行数扩展；合并单元格会吞列时自动拆分；活文档追加「文档修订记录」行，封面日期刷新。
- docx：按标题（去编号）正则定位章节，删除【样本示例/【填写说明及示例正文，复用该章节第 n 张模板表（`fill_table`）或改列（`set_column`，用于 ISO 26262 方法选择表），可插入新表与图片；`placeholders` 替换 ＸＸＸＸＸ。未覆盖的章节保留模板原文，残留标记由 check 拦截。

## 内容 JSON（docx）

```json
{"what": "strategy", "placeholders": {"ＸＸＸＸＸ": "PROJ"},
 "sections": [{"match": "(?i)^集成方法|^integration methods", "nth": 0,
               "blocks": [{"p": "…"}, {"bullets": ["…"]}, {"fill_table": 0, "rows": [["…"]], "header_rows": 1},
                          {"set_column": 0, "col": 6, "values": {"^\\s*1a\\b": "是 Yes"}, "match_col": 0, "header_rows": 2},
                          {"table": {"header": ["…"], "rows": [["…"]]}, "caption": "…"},
                          {"image": "seq.png", "width_cm": 15}]}]}
```
`draft_docs.py` 不覆盖已存在的内容文件（可能含人工审定措辞）；SAD 变更后用 `docs --force` 重起草并对比旧版合并人工修改。

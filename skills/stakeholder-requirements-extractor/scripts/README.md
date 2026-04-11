# Scripts

这个目录放可直接复用的脚本入口。

## fill_stakeholder_requirements.py

把“输入文档清单 + 多份源文档”解析成条目，并回填到 Excel 模板。

### 典型用法

```bash
python fill_stakeholder_requirements.py \
  --workbook /path/to/BBS_相关方需求分析表.xlsx \
  --source-root /path/to/ESOW
```

### 可选参数

- `--report-path`
- `--source-sheet`
- `--target-sheet`
- `--col-seq`
- `--col-name`
- `--col-version`
- `--col-applicable`
- `--col-discipline`
- `--col-remark`

### 默认假设

- 输入清单 sheet 默认叫 `相关方输入文档清单`
- 目标 sheet 默认叫 `相关方需求分析表`
- 适用列默认叫 `是否适用`
- 仅忽略 `*.dbc` 和 `*.ldf`

### 注意

- 脚本会先备份原 workbook
- 会覆盖目标 sheet 的数据区
- 仍建议先抽查 2 到 3 份关键文档，确认拆条效果符合当前项目期望


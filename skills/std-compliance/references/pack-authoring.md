# 从标准原文建（或更新）标准包

## 版权规则（先读）

ISO/IEC/SAE 等标准文本受版权保护，公司许可通常只允许内部阅读使用。因此：
- 检查项只记录**条款号、标题、自述要点**（用自己的话概括“要做什么、怎么判定”），不粘贴原文句子或表格。
- `stdc.py extract` 的输出含原文，只能放在项目工作区 `extract/`（自动生成 `.gitignore`），用完可删；不得复制进 skill、报告或提交到代码库。
- 自检：任一 `requirement` 与原文连续 12 个英文单词以上重合即视为违规，改写后再提交（见文末脚本）。

## 流程

1. **放原文**：解密后的标准 PDF 放到 `inputs.standards_dir`。公司加密文件（文件头 `%TSD-Header` 等）工具读不出，需先申请解密。
2. **提取**：`stdc.py extract --project P` → 每份标准一个目录：
   - `pages/p####.txt`：重建后的逐页文本（字形逐个绘制的 PDF 会有少量拆词，如 `N ode`，不影响阅读）
   - `clauses.json`：条款树（条款号、标题、页码）
   - `norms.jsonl`：含 shall / shall not / should 的规范性语句候选，带条款号与页码
3. **筛选**：只为“节点软件可判定”的要求建检查项。下列内容一般不建：术语定义、信息性附录、只约束工具或文档格式的要求、
   纯物理层电气参数（收发器/线束，除非软件配置可影响）。
   对 commander/responder、client/server 两侧的要求分别标 `role`；只约束对端的要求，若本端需配合（如“响应方必须在 P2 内应答”），
   以本端视角写。
4. **写检查项**：对照 `pages/` 原文写 `requirement`（自述）、`applicability`、`method`、`params`、`check_hint`；`source.page` 写原文 PDF 页码，
   `verified=true`、`by`、`date`。拿不准的写 `verified=false` 并在 `check_hint` 说明疑点。
5. **定方法**：
   - 能从 LDF/DBC/ARXML/代码常量直接看出的 → `config`，并在 `rules/` 写规则；
   - 需要读设计文档或源码结构判断的 → `design`；
   - 需要输入激励、观察输出的协议行为 → `host-test`；
   - 依赖真实位时序、总线负载、物理层、真实时间窗 → `target`，写 `target_note`。
6. **验证**：`stdc.py applicable/static/verify --project <evals 或试点项目>`；抽查每份标准 10 条的条款号与页码；跑版权自检。
7. **升版本**：`pack.json.version` 递增；标准换版时重新 extract，逐条比对条款号与要求变化。

## 版权自检脚本（示意）

```python
import json, re, glob
def words(s): return re.findall(r"[a-z0-9]+", s.lower())
src = " ".join(open(f, encoding="utf-8").read() for f in glob.glob("std_ws/extract/*/pages/*.txt"))
src_w = words(src); grams = {" ".join(src_w[i:i+12]) for i in range(len(src_w)-11)}
for it in json.load(open("packs/<pack>/checklist.json", encoding="utf-8"))["items"]:
    w = words(it["requirement"])
    if any(" ".join(w[i:i+12]) in grams for i in range(len(w)-11)):
        print("too close to source:", it["id"])
```
（`requirement` 用中文书写时基本不会触发；英文书写时必须跑。）

## 写测试时顺手核对
为某条检查项写宿主机测试或评审时，打开项目工作区 `std_ws/extract/<标准>/pages/pNNNN.txt` 对照原文：
要点有偏差就改正（只写自述，不抄原文），核对无误把 `source.verified` 改为 true、写日期并删除 `note`。
发现原文有规范性要求而清单漏掉时，新增检查项（如 UDS1-CC-03“controlType 实际生效”就是写 0x28 测试时补上的）。

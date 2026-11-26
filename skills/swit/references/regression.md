# 回归测试（只输出 237 + 238）

## 输入

- **上一轮测试记录** xlsx（236 或上一轮 237）：按表头「标识符 / 判定结果 / 缺陷ID」定位列，读每条用例的判定与缺陷号。记录里的 ID 必须来自本用例注册表（SWIT-XXXXX），否则告警。
- 可选：代码变更 `--svn r1:r2` / `--git a..b`（在 `sources.root` 下执行）或 `--changed-files`；缺陷清单 `defects_file`；`--include` 手工追加。

## 选择规则（每条用例记录理由，写入 `ws/results/selection_<RN>.json`）

1. 上一轮失败 / 阻塞 / 跳过 / 未执行（NA = 转 SWE.6 不重跑）
2. 上一轮记录了缺陷号的用例（验证修复）；缺陷清单中状态为 fixed/verified/closed 的关联用例
3. 代码变更影响：变更文件 → 组件（`sources.component_dirs`，或 `regression.change_map` 正则）→ 该组件的用例、它提供或使用的接口用例、名称/步骤涉及它的动态行为用例
4. `regression.always_include_priority` 中的优先级（冒烟集）

## 执行与输出

```bash
swit.py regress --project P --previous "<…Test Records_1.xlsx>" --round R1 --svn 1200:1234
swit.py run     --project P --round R1 --selection --ceedling
swit.py build   --project P --mode regression --rounds 1 R1
swit.py check   --project P --mode regression --rounds 1 R1
```
- 回归轮命名 `R1, R2…`，结果 `round_R1.json`；237 的列头写「第 n 轮回归测试」。
- 报告 238 第 4 节按轮次 × 类别列出首轮与各回归轮；第 1 节以最终有效判定计。
- check 确认回归轮没有生成 236。
- SAD 锚点自上次基线后有变化时，status 会提示：回归假设架构不变，应走 sad-change。

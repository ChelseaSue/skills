# 一致性检查清单（收尾核验 + 迭代护栏）

这张清单核验生成代码是否符合本 skill 的全部设计要求。**代码每次迭代更新后重跑它**，就能判断是否仍然合规——
这正是用户要的"可通过清单检查是否符合 skill 设计要求"。能自动化的项由 `scripts/conformance_check.py` 跑，
其余靠人工对照证据。

每项标注：**[A]** 自动可查（脚本）/ **[M]** 人工核查。期望全部 ✅；未过项要么修代码、要么明确记为已知偏离。

## A. 分层（可移植）
- [M] 若 SAD 与 skill 默认架构存在差异，已有用户明确选择记录（采用 SAD / 采用 skill 默认架构），且选择发生在
  `layers.json`、架构图和代码生成之前；无“生成者自行决定”的情况。
- [M] 架构决策记录至少包含 `architecture_source`、用户确认、日期、差异范围；全部生成产物与所选架构一致。
- [A] 不存在**向上 include**：任何模块都不 `#include` 更高层头。（`check_layering.py` 0 违规）
- [A] 不存在**未声明的跳层 include**：上层只够相邻下层、`architecture_edges`、同层和横切层
  （`strict_adjacent=true` 时）；默认允许片内 `HAL→MCAL` 与外挂芯片 `HAL→CDD→MCAL`。
- [A] 采用 skill 默认架构时，App 不直接依赖 HAL/CDD/MCAL；硬件访问经
  `App→Native/Device Service→HAL`。
- [A] `Service→Os` 的实际模块依赖仅来自 OSIF；Native/Device Service 和其它 Service 模块不得直接 include
  OS/RTOS 头文件，除非 SAD 明确批准并记录。
- [A] `peer_groups` 中不同层之间不存在未声明依赖；默认 `MCAL→OS` 与 `OS→MCAL` 均为 0。
- [M] 硬件相关代码全部收敛在抽象层（HAL/CDD）接口之后；上层无寄存器直操作、无芯片头直 include。
- [M] `layers.json` 的层序、平级组、横切层、`architecture_edges`、放行边与 SAD 分层架构图一致；MCAL 与 OS/RTOS
  在图中平级并共同连接硬件，结构边与架构偏离未混用。

## B. 模块化（高内聚低耦合）
- [A] 同层模块间无私有头互包（`check_layering.py` 同层耦合告警为 0 或均经公开接口/总线）。
- [A] 无裸 `extern` 全局变量做跨模块共享（`conformance_check.py` 扫描；命中需改访问函数或总线）。
- [M] 每个模块单一职责，对外只暴露必要接口；文件内私有状态用 `static`。
- [M] 同层/层间协作经总线/回调/公开接口契约（机制按产品场景选，见 layering-rules §4），无向上 include、无循环依赖。
- [M] 数据传递守 `layering-rules.md §6`：优先函数参数/返回值；复杂状态用结构体按指针传（入参 `const T*`）。

## C. 可测试（接口清晰、可注入）
- [M] HAL 等硬件接口为 If/Impl 拆分（或等效抽象）：上层只依赖接口头，实现可替换/可打桩。
- [M] 每个公开函数有契约注释（线程安全/ISR 安全/阻塞/返回码语义），便于写测试与打桩。
- [M] 关键逻辑模块不直接绑定硬件，能在主机侧链接桩实现单测。

## D. 目录结构清晰（模块化）
- [A] 顶层目录能体现分层（`path_map` 覆盖所有源文件，无"层外"游离文件）。
- [A] 文件名带层前缀且与所在层一致（`conformance_check.py` 按 `layers.json` 的 `file_prefix` 核对）。
- [M] 每层、每模块各有独立文件夹；模块文件 `<前缀><Module>.h/.c/_Cfg.h` 收在自己文件夹内（除非显式 flat 例外）。
- [M] 公共数据结构（typedef/enum/struct）定义在模块 `.h`；私有类型留在 `.c`。命名遵循项目 `NameRules.txt`/SAD。
- [M] 已用 `render_layer_diagram.py` 出分层架构图，且与 SAD 分层图一致（层序、横切层画成竖条跨使用者层、每层模块齐全）。见 `diagram-guide.md`。
- [M] SAD 无架构差异、未描述架构或用户选择 skill 默认架构时，架构图、`layers.json`、`module_spec.json` 与
  `assets/default-software-layered-model.svg` 的架构语义一致；用户选择 SAD 时，三者与 SAD 及决策记录一致。

## E. MISRA C:2012
- [A] `run_misra.py`（cppcheck --addon=misra）的 Mandatory/Required 违规为 0，或全部对应到带理由的 deviation。
- [M] deviation 均有 `/* MISRA deviation Rx.y: 理由 */` 就地注释（+ 可选 `deviations.md` 登记）。
- [A] 无动态内存调用（grep `malloc/free/calloc/realloc` 命中为 0）。
- [M] Advisory 违规已汇总，用户已知悉/接受。

## F. 需求追溯（100%）
- [A] 每条 SRS 需求 ID 至少出现在一处 `@implements`（`conformance_check.py` 求差：未覆盖集为空）。
- [A] 不存在指向不存在需求 ID 的 `@implements`（孤儿标注为 0）。
- [M] 追溯表（需求 → 模块/函数 → 文件）已产出，可供评审。

## G. 可编译性（按工具可用情况）
- [A] `check_layering` + `run_misra` 均通过（门禁）。
- [M] 有交叉工具链时工程编译通过；无则纯逻辑模块经 `gcc -fsyntax-only -Wall -Wextra -Wconversion` 无错。
- [M] 缺口处均为 `/* TBD: ... */` 显式占位，无硬编造的寄存器值/管脚/魔法数。

---

### 报告口径
`conformance_check.py` 输出一张表：每项 → ✅/❌/⚠️(人工待核) + 证据（违规计数、未覆盖需求列表、命中文件等）。
人工项需生成者对照本清单逐条确认并在报告里补结论。**任一 [A] 项失败即视为未通过本 skill 设计要求**，回到对应
工作流步骤修复后重跑。

## H. 跨项目移植/复用（reusable 模块）
- [ ] 每个模块在 `module_spec` 有明确 `reuse` 分类（或接受层默认），App 顶层编排为 project-specific。
- [ ] `check_layering.py --modules` 跑过，无 `REUSE` 违规（reusable 未依赖 project-specific）。
- [ ] reusable 模块的横切语义收在 `<Module>_contract.h`，未直接引用项目专属全局 ID。
- [ ] reusable 模块文件夹存在 `<Module>_port.md`，接驳点（Impl/Cfg/信号 ID/前缀）已按本项目填写。
- [ ] port.md 第 4 节追溯 ID 已对新项目重映射（移植场景）。

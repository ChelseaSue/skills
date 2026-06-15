# 跨项目模块移植/复用 设计（code-generator skill）

日期：2026-06-15
范围：在 code-generator skill 的架构规则与门禁里，把 HAL/Service/App 各层模块的**跨项目移植/复用**作为代码生成时的一等约束。

## 1. 目标与动机

现有 [layering-rules.md](../../../references/layering-rules.md) 已把"单项目内可移植（换硬件）"设计得很强：HAL 的 If/Impl 分离、算法核隔离在 Service、下层不依赖上层、一模块一文件夹、项目相关外置。这些为跨项目移植打下约 9 成土台，但"把旧项目已调好的模块直接搬到新项目"仍缺明确护栏：

- reusable 模块对横切层（SignalBus 信号 ID、Cfg 键、Types 返回码）的隐式依赖是项目固有的，搬走后接不上；
- `Impl/` 绑定旧项目 MCAL/SDK；`*_Cfg.h` 绑定旧板级；
- 文件名/符号前缀按项目不同；
- 追溯 ID 是旧项目 SRS 的。

目标：让生成的代码显式区分**可复用部件**与**项目专属部件**，对可复用部件施加移植护栏，并把真正破坏可移植性的依赖做成机检门禁。

## 2. 已定决策（brainstorming 结论）

1. **形态**：显式分两类 `reusable` / `project-specific`，只对 reusable 强制护栏（不强行通用化 App）。
2. **移植边界**：默认**自包含契约**（reusable 模块把横切语义收进自己的 contract 头，整文件夹可搬），配置量大/需运行期替换的叠加**依赖注入**。
3. **强度**：机检门禁——能机检的硬挡，语义靠 conformance 人工核。
4. **落点**：扩展现有文件（方案 1），不新增独立脚本/门禁。
5. **port.md**：**不设硬挡**，自动生成、作为移植参考说明文档；保留的硬挡只有"reusable 反向依赖 project-specific"这一条。

## 3. 模块分类与标注

`layers.json` 的 module_spec 加字段：

```json
{ "name": "FocCore", "layer": "Service", "reuse": "reusable", "reuse_note": "纯算法核，零硬件零业务" }
```

`reuse` ∈ {`reusable`, `project-specific`}；缺省按层默认。

| 层 | 默认 | reusable 典型 | project-specific 典型 |
|---|---|---|---|
| HAL | reusable | `If/` 接口头（硬件无关，强制 reusable） | `Impl/`、`*_Cfg.h` 引脚/通道映射（板级，强制 project-specific） |
| Service | reusable | 算法核（FOC/PID/滤波）、通用协议栈、诊断框架、参数/NVM 框架 | 绑定本项目业务语义的 Native/Device Service |
| App | project-specific | 可复用业务子功能模块（通用故障管理、参数管理、按键/LED 行为库等，按子功能粒度切分后标注） | 顶层编排/主状态机/任务调度（强制 project-specific，永不通用化） |

约束：
- HAL `If/` 强制 reusable，`Impl/`+`*_Cfg.h` 强制 project-specific（即"换硬件=换 Impl"）。
- App 顶层编排/主状态机强制 project-specific——它就是把 reusable 部件组装成本项目的地方。

## 4. reusable 模块的移植护栏（四条）

1. **反向依赖禁止（机检硬挡）**：reusable 模块**不得 `#include` 任何 project-specific 模块**的头。与"不向上依赖"同构。
2. **横切依赖收敛为自包含契约**：reusable 用到的横切语义（信号 ID 枚举、Cfg 默认值、返回码扩展）收进自己文件夹的 `<Module>_contract.h`，不直接引用项目全局专属 ID；共用只准依赖**稳定横切**（Types 稳定返回码、Bus 注册 API 本身）。→ 整个文件夹可搬走编译。
3. **可选注入（叠加）**：配置量大/需运行期替换的 reusable 模块，把横切依赖在 `<Module>_Init(const <Module>Cfg_t* cfg, ...)` 注入，模块内零项目全局引用。
4. **移植参考说明**：每个 reusable 模块文件夹带 `<Module>_port.md`（自动生成、不机检、不硬挡）。

组装方向：**project-specific 可以依赖 reusable（合法）；reusable 依赖 project-specific（硬挡）**。这正是"App 顶层编排调用 reusable 子功能"的合法路径。

## 5. `<Module>_port.md` 模板（自动生成的参考说明，不机检）

scaffold 对每个 reusable 模块自动产出并预填已知信息。固定小节：

```markdown
# <Module> 移植清单
## 1. 模块身份  —— 层 / reuse 类型 / 前缀 / 对应 SRS 需求 ID（旧项目）
## 2. 依赖
- 自带：<Module>_contract.h、核心 .c/.h、本模块单测
- 需新项目提供：稳定 Types 返回码、Bus 注册 API（若用）
## 3. 需重新适配的接驳点（移植时逐条改）
- [ ] Impl/ → 绑定新项目 MCAL/SDK（仅 HAL 模块）
- [ ] *_Cfg.h → 新项目板级/通道/参数
- [ ] 信号/事件 ID → 在新项目登记 contract 里的 ID
- [ ] 文件名/符号前缀 → 若新项目 file_prefix 不同则改
## 4. 追溯重映射  —— 旧 SRS ID → 新项目 SRS ID（占位，移植时回填）
## 5. 主机单测  —— 如何脱离硬件跑本模块单测（打桩点）
```

## 6. 机检边界（诚实划线）

**机检硬挡（门禁失败）——只此一条：**
- reusable 模块 `#include` project-specific 模块 → 反向依赖污染，非零退出。

**自动生成、不挡：**
- `<Module>_port.md`、`<Module>_contract.h` 占位。

**靠人（conformance 人工核）：**
- port.md 接驳点填写是否对/全；
- 第 4 节追溯 ID 的新项目重映射（实际移植时人回填）；
- 自包含程度是否够（部分由护栏 1 的 include 检查兜底）。

## 7. 实现落点（方案 1：扩展现有文件）

| 文件 | 改动 |
|---|---|
| `references/layering-rules.md` | 新增 **§8 跨项目移植/复用**：分类与各层默认、四条护栏、组装方向 |
| `layers.json` schema + `scripts/scaffold_tree.py` | module_spec 加 `reuse` 字段（缺省按层默认）；scaffold 时为 reusable 模块自动生成 `<Module>_contract.h` 占位 + 预填的 `<Module>_port.md` |
| `scripts/check_layering.py` | 复用已有 include 图，加规则：reusable `#include` project-specific → 违规、非零退出 |
| `references/module-templates.md` | 加 `<Module>_contract.h` 与 `<Module>_port.md` 模板 |
| `references/conformance-checklist.md` | 加「跨项目移植」核查组（自包含程度、接驳点、追溯重映射——语义人工核） |
| `SKILL.md` | 分层/门禁说明处点出 reuse 分类与反向依赖门禁；逐模块模式提示读 `reuse` 标注 |

## 8. 非目标（YAGNI）

- 不引入跨项目"复用库/沉淀库"仓库、版本管理（brainstorming 中作为 C 选项被排除，太重）。
- 不为 port.md 设存在性/完整性硬门禁。
- 不新增独立 portability 脚本或独立门禁步骤。
- 不强制 App 顶层编排通用化。

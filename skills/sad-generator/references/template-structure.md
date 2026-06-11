# SAD 模板结构参考（AU-QR-R&D-032 V2.1）

模板是中英双语 ASPICE 风格软件架构设计规格说明书。本 skill 只借它的**结构**，内容统一中文。模板里的
`<子系统名 #1>`、`e.g. APP`、`<服务名>` 等是**占位/示例**，生成时按本项目实际替换，不要照抄。模板原文件是
旧版二进制 `.doc`——读骨架/做最终 docx 前先 `soffice --headless --convert-to docx` 转一次。

## 目录（章节树）

```
1 引言 Introduction
  1.1 文档范围 Document Scope
  1.2 目的和目标 Goals and Objectives
  1.3 设计方法和标准 Design Methodology and Standards
  1.4 参考文档 Reference Documents              [表：缩略词|文档名称|版本|状态]
2 术语和缩写 Terms and Abbreviations            [表：术语/缩写 | 定义]
3 系统描述 System Description
  3.1 系统简介 System Overview
  3.2 部署视图 Deployment view                  [部署图：MCU/总线/外设拓扑]
  3.3 软件特性 Software Features                [表：特性 | 说明 | 覆盖需求]
  3.4 软件上下文图 Software Context Diagram      [上下文图：软件 ↔ 外部接口/总线/传感执行器]
  3.5 软件外部接口 Software External Interfaces  [表：接口|类型|方向|描述|信号]
4 设计约束 Design Constraints
  4.1 初始化约束 / 4.2 输入约束 / 4.3 输出约束 / 4.4 硬件约束与依赖 / 4.5 通信网络约束 /
  4.6 诊断约束 / 4.7 尺寸和性能约束 / 4.8 调度约束 / 4.9 集成约束 / 4.10 其它约束(工具/COTS bug)
5 实时分析 Real Time Analysis
  5.1 进程识别 Processes Identification          [表：进程/任务 | 周期 | 优先级 | 职责]
  5.2 时基识别 Timing bases identification       [表：时基(如1ms/10ms/100ms) | 用途]
  5.3 软件运行模式 Software Operating Modes       ← 【状态机图】电源/运行状态机
  5.4 软件功能模式 Software Functional Modes      ← 【状态机图】各功能模式机（制氧模式/降级…）
  5.5 共享资源 Shared Resources（硬件/软件）
  5.6 预估负载率 Estimated Workload（最坏 CPU 负载 + 测量步骤）
6 备选方案及论证 Design Alternatives and Justification
  6.1 RTOS/调度原则选择 / 6.2 NVM 设计选择 / 6.3 通信组件 MBR 选择 / 6.4 软件架构选择
      （每个：选择标准 / 设计方案选择 / 选择与依据）
7 架构设计 Architectural Design
  7.1 实时架构 Real Time Architecture（中断 / 循环任务 / 最坏 CPU 负载 / 共享资源保护）
  7.2 静态架构 Static Architecture
      7.2.1 分层架构 Layered Architecture         ← 【分层架构图】
      7.2.2 开发视图和用例视图 Development/use case view
      7.2.3 组件定义 Components Definition（按子系统 APP/HAL/… 展开）  [组件定义表]
      7.2.4 接口设计 Interfaces Design            [接口表]
      7.2.5 子系统 Subsystems
  7.3 内存消耗 Memory Consumption（内存大小 / 内存映射）   [内存映射表]
  7.4 软件鲁棒性 SW Robustness（故障处理/看门狗/IO/NVM/复位初始化/中断/结构体/变量/堆栈/OS/其他）
  7.5 软件设计局限性 SW Design Limitations
8 软件组件 Software Components                    ← 按 子系统 × 组件 展开
  8.x <子系统>
      8.x.y <组件>
          资源约束 / 外部接口(依赖) / 设计约束 / 组件 API(服务) / 组件配置
9 时序管理 Sequence Management
  9.1 初始化时序 Initialization Sequence          ← 【时序图】上电初始化
  9.2 休眠时序 Sleep Sequence                     ← 【时序图】进入休眠
  9.3 唤醒时序 Wakeup Sequence                    ← 【时序图】报文/按键唤醒
  9.4 时序图 Sequence Diagrams                    ← 【时序图】各功能模式，每功能一张，标真实 CAN 信号
```

三类强制图归属：**分层架构图→7.2.1**；**状态机图→5.3 + 5.4**；**各功能动态时序图→第 9 章**（含 9.1/9.2/9.3
固有时序 + 9.4 每功能一张）。画法见 `diagram-guide.md`。

## 关键表字段 schema

### 组件定义表（7.2.3，每个组件一行或一块）
`组件ID | 组件名 | 所属子系统/层 | 职责描述 | 对外提供的服务/接口 | 依赖(下层/其它组件) | 实现需求(HOD_SRS_*) | ASIL`
- ASIL 本期统一 `NA（本期不涉及功能安全）`。
- **实现需求** 列是追溯关键：列出该组件实现的 `HOD_SRS_*` ID。

### 组件 API / 服务表（8.x.y 组件 API → 服务）
每个服务一块：`服务名 | 原型/签名 | 方向(同步/异步,调用/被调用) | 入参 | 出参/返回 | 描述 | 关联信号/需求`
- Demo 阶段签名未定时给建议原型并标 `【TBD-待软件详细设计 SWDD 细化】`（详细设计是下游 swdd-generator 的事）。

### 进程/任务表（5.1）
`任务名 | 触发(周期/事件) | 周期(ms) | 优先级 | 承载组件 | 职责`
- 周期来源：SRS 5.2 实时约束（响应≤200ms、故障检测 200ms、休眠超时 5s…）；缺的标 TBD。

### 内存映射表（7.3）
`区域 | 起止地址 | 大小 | 用途 | 备注`——多为 `【TBD-待补充：需 MCU 数据手册/链接脚本/资源预算】`。

### 软件外部接口表（3.5）——**对照 HSI 逐一列全，别照搬 SRS**
按接口类别分组列表（每组一张小表）：**① 总线/通信**（CAN0/CAN1/LIN/UART/SPI…）**② 模拟输入 ADC**
**③ 数字输入 DI** **④ 数字/PWM 输出 DO** **⑤ 看门狗/复位**。每行带真实 **MCU 网络端口名**（取自 HSI PINMUX）：
`接口/信号 | MCU 网络端口 | 类型 | 方向 | 描述 | 关联信号/报文`。
- 数据源：`HSI/*端口定义*.xlsx`（连接器→信号）+ `HSI/*管脚定义*PINMUX*.xlsx`（网络端口名）；**不要只搬 SRS 3.6**
  （常是节选且可能有错）。与 SRS 冲突以 HSI 为准，并在表后注"与 HSI 核对的更正"。
- 易错点（本项目实测）：PM2.5=独立内部 CAN（CAN1）非 ADC；CAN0 引脚以 PINMUX 实配为准；流量阀=步进电机非 PWM；
  压缩机=6 路 BLDC/FOC PWM + 相/母线电流采样。

### 状态机表（5.3 运行模式 / 5.4 功能模式）——每个状态机配两张表
**状态说明表**：`内部状态编号 | 对外上报 | 状态 | 用途/职责 | 关键活动`
（5.4 功能机可按功能分组：`功能机 | 状态 | 说明 | 关键活动/信号`）。
**状态转移条件表**：`序号 | 起始状态 | 跳转状态 | 跳转条件`——序号 C1/C2…（全局机）或 F1/F2…（功能机），
与状态机图连线序号一一对应；条件保留 `&&`/`||`/`!`、`//` 后回链需求 ID（表格内 `|` 写 `\|`）。详见 `diagram-guide.md ②`。

### 追溯矩阵（文末，**逐条全列每个 HOD_SRS_***）
| SRS 需求 ID | 标题 | 实现组件/子系统 | 相关时序/状态机 | SAD 章节 | 状态 |
|---|---|---|---|---|---|
| HOD_SRS_O2_001 | 各座供氧电磁阀通断 | APP/O2、HAL/阀驱动 | 9.4 制氧时序 | 7.2.3、8、9.4 | ✅ |
| HOD_SRS_PWR_001 | 总线超时进入休眠 | SVC/PWR、OS | 5.3 电源状态机、9.2 休眠时序 | 5.3、9.2 | ✅ |

状态：✅已覆盖 / 🟡部分（含预留待释放，如标定 CAL、高氧停机）/ 🔩硬件域（软件不适用）。
**做法**：先用 `grep -oE 'HOD_SRS_[A-Z0-9]+_[0-9]+' <srs.md> | sort -u` 拿全量需求清单，逐条列；生成后用
`scripts/trace_check.py` 核验未覆盖集为空。覆盖率要真实——不能写"O2_001~007 已覆盖"这种笼统行盖住漏项。

## 与 SRS 的章节对应（便于搬运内容，避免重复造轮子）
- 032 第 2 术语 ← SRS 1.4 术语缩写。
- 032 第 3 系统描述 ← SRS 1.2 范围 / 2.x 产品总览 / 2.3 产品背景框图（可复用 SRS 的 srs_images 图）。
- 032 3.5 软件外部接口 ← SRS 3.5/3.6 通信管理 + 信号映射 + 通信矩阵。
- 032 第 4 设计约束 ← SRS 5.x 非功能需求（实时/资源/质量/设计规范）+ HSI/外设的电气约束。
- 032 5.3/5.4 运行/功能模式 ← SRS 3.7.2 各功能模式适用性 + PWR 电源状态描述。
- 032 7.2 静态架构 ← SRS 3.7.1 SWC 清单 + 3.7.3 功能间接口（升级为分层 + 组件 + 接口）。
- 032 第 8 软件组件 ← SRS 第 4 章各 SWC 需求表（每条 HOD_SRS_* 落到承载组件）。
- 032 第 9 时序管理 ← SRS 各功能 4.x.1 功能关联图 + 通信矩阵信号（升级为带真实信号的 PlantUML 时序）。
- 032 第 6 备选论证 / 7.3 内存 / 7.4 NVM·看门狗 ← SRS 多为预留或无 → TBD / "建议方案待评审"。

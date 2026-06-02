# SRS 模板结构参考（AU-QR-R&D-027 V3.0）

模板是中英双语 ASPICE 风格软件需求规范。本 skill 只借它的**结构**，填充内容统一用中文。
模板里大量 `e.g.`/示例行（如 `HOD_SRS_SWC_001`、SWC 按键/背光示例）是**示例**，生成时按本项目实际替换，不要照抄。

## 目录（章节树）

```
1 引言 Introduction
  1.1 目标 Purpose
  1.2 范围 Scope
  1.3 需阅读人员 Target Reader
  1.4 术语和缩写 Terms & Abbreviations          [表：术语 | 定义]
  1.5 参考文献 References                        [表：缩略词|文档名称|参考|状态|版本]
  1.6 适用文件 Applicable documents              [表：缩略词|文档名称|参考|状态|版本]
2 产品总览 Product Overview                       [产品外形图]
  2.1 产品定义 Product identification            [表：项目ID/项目名/... 见下]
  2.2 功能列表 Function list                     [表：NO.|Level1|Level2|Level3|ASIL|备注]
  2.3 产品背景 Product Context                   [系统框图：MCU↔传感器/电机/外设]
  2.4 产品变体 Product Variants
3 软件总体 Software Overall
  3.1 软件产品概览 Software Product overview      [表：MCU类型/主频/Flash/RAM/...]
  3.2 软/硬件环境 Hardware / Software Context     [HSI 图]
  3.3 变体管理 Variants Management
      3.3.1 硬件变体 / 3.3.2 软件变体
  3.4 引导程序 Bootloader
  3.5 通讯管理 Communication Management
  3.6 软件外部接口及信号映射 SW External Interfaces and Signal mapping
                                                 [表：接口|名称|类型|描述]
  3.7 软件功能 Software Features
      3.7.1 功能识别 Features Identification      [表：功能名称|描述]
      3.7.2 各功能模式适用性 Applicability         [表：功能×功能模式]
      3.7.3 功能间接口 Interface between features  [软件功能模块图]
4 功能需求 Functional Requirements                 ← 主体，按 SWC 模块逐个展开
  4.x 功能<模块名> Feature <Module>
      4.x.1 功能关联 Feature Context             [模块接口图]
      4.x.2 功能输入输出描述 Feature Inputs/Outputs[输入表 + 输出表，字段见下]
      4.x.3 功能需求 Feature Requirements         [需求表 × N，字段见下]
      (输入/输出模块可再嵌 SWC 子模块，模板示例用了 4-5 级标题)
5 非功能需求 Non Functional Requirements
  5.1 软件版本 / 5.2 实时约束 / 5.3 资源约束 / 5.4 质量约束
      (5.4.1 文件命名规则 / 5.4.2 编码规范 / 5.4.3 代码命名规范)
  5.5 设计规范 / 5.6 可靠性 / 5.7 安全性
6 非易失性存储器内容 Non-volatile Memory Content
  6.1 数据内存内容定义 Data flash Content definition
7 行业要求 Industry Requirements
```

## 关键表字段 schema

### 需求表（4 章每条软件需求，**必须含全部 13 字段**）
| 字段 | 含义 / 填写要点 |
|---|---|
| 需求ID Req ID | `HOD_SRS_<MODULE>_NNN`，模块名按 SWC，三位序号 |
| 标题 Title | 一句话需求名（中文）|
| 描述 Description | "The <模块> shall …" 句式的具体行为；可量化处给数值，缺则 `【TBD】`|
| 类型 Type | Functional / Safety / Performance / Interface 等 |
| 需求成熟度 Req Maturity | Draft / Reviewed / Approved（新起草填 Draft）|
| 变体 Variant | 适用变体；无填 NA |
| 分配 Assignation | 分配到的软件组件缩写（如 SWAD/PWR/DIAG）|
| 测试 Test by | 验证手段（单元测试/集成/HIL…），未定可空或 TBD |
| ASIL | 安全等级；**无功能安全分析时填 `【TBD-待 HARA】`，不要臆造** |
| 功能 Feature | 所属功能模块名 |
| 验证标准 Verification Criteria | 怎样算通过（可测的判据）|
| 覆盖需求 Covered Req | **回链来源系统需求 ID `SR-xx-xxx`**（追溯关键），及产品需求 FR-/DIAG-/REL- |
| 发布计划 Release Plan | 计划发布版本/里程碑，未定填 TBD |

### 输入/输出表（4.x.2）
`名称 Name | 类型 Type | 范围 Range | 单位 Unit | 描述 Description | 来源 Source | 目标 Destination`
（来源/目标 = 信号从哪个模块/管脚来、送到哪个模块；范围/单位多来自 HSI 与外设参数表）

### 功能列表表（2.2）
`NO. | 一级功能模块 Level1 | 二级功能模块 Level2 | 三级功能模块 Level3 | ASIL | 备注`

### 产品定义表（2.1）
`项目ID Project ID | 项目名 | 产品型号 | 客户 | ...`（键值两列）

### 软件产品概览表（3.1）
`MCU类型 | 主频 | Flash | RAM | 编译器 | ...`（键值两列）

## 与系统需求文档的章节对应（便于搬运内容）
- 模板 1.4 术语 ← 系统文档"名词缩写"表
- 模板 2.2 功能列表 ← 系统文档"功能清单"表（含 SR-ID/产品需求ID）
- 模板 2.3 产品背景 / 3.2 HSI ← 系统文档"系统框图/接口定义/引脚定义" + `HSI/`
- 模板 3.6 外部接口 ← 系统文档"接口定义/网络接口/CAN-UART 协议" + `HSI/`
- 模板 4 功能需求 ← 系统文档"系统功能"各节（功能概述 + 基本流程）按 SWC 拆解
- 模板 5 非功能需求 ← 系统文档"非功能需求"（性能/质量/物理）
- 模板 6 NVM、3.4 Bootloader、ASIL/网络安全 ← 系统文档多为"预留"或缺失 → TBD/提示补充

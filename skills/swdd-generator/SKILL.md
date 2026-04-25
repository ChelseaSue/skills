---
name: swdd-generator
description: 软件详细设计文档（SWDD）生成工具。用于根据嵌入式模块源代码自动生成符合ASPICE/ISO26262标准的软件详细设计文档。当用户需要：(1)生成软件详细设计文档 (2)创建模块设计文档 (3)编写函数接口设计 (4)生成静态图/时序图/流程图 (5)编写External/Internal函数设计 时使用此skill。支持自动生成Mermaid图表、PlantUML序列图、函数原型表格、变量定义表格等标准格式。本skill会严格遵守用户提供的参考文档格式要求。
---

# SWDD Generator Skill

用于根据嵌入式模块源代码自动生成符合汽车电子行业ASPICE标准的软件详细设计文档。

## §0 模块信息发现（每次生成 SWDD 的第 0 步，必须完成）

本 skill 不假设任何固定项目名、目录结构或文件命名模式（如 `*_prg.c` / `*_int.h` 等 APP 层惯例）。开始生成前，按以下步骤**自动发现**模块信息：

### 步骤 1 — 模块目录定位

用户仅需提供 `{模块名}`（如 `ADIAP`、`AINCU`、`DSPI`）。skill 在工作区搜索同名目录：

```bash
find . -maxdepth 6 -type d -name "{模块名}" \
    -not -path "*/swdd/*" \
    -not -path "*/node_modules/*" \
    -not -path "*/.git/*" \
    -not -path "*/.vscode/*" \
    -not -path "*/build/*" \
    -not -path "*/Debug_*/*" \
    -not -path "*/Release_*/*" 2>/dev/null
```

- **唯一命中** → 取该路径作为 `{模块路径}`
- **多个命中** → 用 `AskUserQuestion` 让用户选择具体目录
- **零命中** → 报错并要求用户手动提供 `{模块路径}` 完整相对路径

### 步骤 2 — 派生其他参数

从 `{模块路径}` 解析：

| 占位符 | 派生方法 | 示例 |
|--------|---------|------|
| `{项目根}` | `{模块路径}` 第一段（顶层目录名） | `BBS_K311_APP` / `BBS_K311_SWDL` |
| `{文档前缀}` | 默认同 `{项目根}` | `BBS_K311_APP` / `BBS_K311_SWDL` |
| `{模块名}` | 用户输入，保持不变 | `AINCU` / `ADIAP` |

`{文档前缀}` 极少需要与 `{项目根}` 不同；若项目有自定义约定，由用户在开始时明确指示覆盖默认值。

### 步骤 3 — 源文件枚举（不对文件名做任何假设）

```bash
ls {模块路径}/*.c {模块路径}/*.h 2>/dev/null
```

**把命中的所有 `.c` 和 `.h` 文件一视同仁地当作本模块源文件**。不假设 `_prg.c` / `_int.h` / `_priv.h` / `_cfg.c` / `_cfg.h` 这套命名模板 —— ADIAP 模块就是反例：文件名是 `bl_desc.c` / `bl_desc.h` / `bl_desc_adapter.c` / `bl_desc_funcfg.h` 等，完全不符合 APP 惯例。

### 步骤 4 — 语义角色推断（读内容，不读文件名）

遍历步骤 3 枚举出的每个文件，根据**内容**推断用途：

**`.c` 文件**：
- 读前 50 行获取 header comment 的 `Description:` 字段
- 如果有大量函数定义且本模块其他 `.c` 也调用它的函数 → 主实现
- 如果只有一张 const 数组/配置表 → 配置数据

**`.h` 文件**：判断公/私用**跨目录 include 扫描**，不看文件名后缀：
```bash
grep -rn '#include "{头文件名}"' {项目根}/ | grep -v "{模块路径}/"
```
- 有跨目录引用 → 对外 API 头文件（`External` 作用域）
- 仅本目录内引用 → 私有头文件（`Internal` 作用域）

**函数对外/内部分类**：通过 cscope 而不是通过头文件归属判断：
```bash
# 查某函数的所有调用者文件
cscope -dL -3 函数名 | awk '{print $1}' | sort -u
```
- 所有调用者都在 `{模块路径}/` 下 → Internal
- 有 `{模块路径}/` 之外的调用者 → External

### 步骤 5 — 多源文件目录处理（子组件识别）

当 `{模块路径}/*.c` 数量 ≥ 2 时，可能是多子组件目录（例：ADIAP = `bl_desc.c` + `bl_desc_adapter.c` + 相关 cfg 文件）。

**处理流程**：
1. 列出全部 `.c` 文件，用 `AskUserQuestion` 询问用户：视为单组件 vs 按子组件分组
2. **不自动判断** —— 用户明确指示优先；cscope 分析两组 `.c` 之间几乎无直接调用只作为辅助线索
3. 若确认为多子组件：
   - **§2.3 文件表**：按子组件分组列出，每组前加一行子组件简述
   - **§2.4.1 静态图**：每个子组件一个独立 `subgraph`（颜色区分），展示子组件间调用
   - **§2.4.2 表**：`Unit ID` 用 `{模块名}_unit_NN` 连续编号（跨子组件连续）；`Component ID` 列可用 `{模块名}/{子组件}` 区分
   - **§2.6 动态图**：若子组件间有调用链，用 `box` 分组
   - **§2.7/2.8**：按子组件聚类相邻排列，**不拆章节**（仍用 `2.7.1 / 2.7.2 / ...` 连续编号）

### 步骤 6 — cscope 数据库确认

生成前确保 `cscope.out` 已覆盖所有相关项目目录。构建命令见本文件末尾 "新项目启动检查清单"。

---

## 强制规范（必读，不得违反）

**生成或修改任何 SWDD 前必须先阅读并遵守：** [references/SWDD_Mandatory_Requirements.md](references/SWDD_Mandatory_Requirements.md)

### SWDD 正文必须由 LLM 直接编制（最高优先级）

**禁止采用“先生成脚本、再由脚本批量生成文档正文”的方式创建或重编 SWDD。** SWDD 的章节文本、Mermaid 静态图/流程图源码、PlantUML 动态图源码、数据表格、函数属性表和 Process Description，必须由 LLM 基于源码、cscope 结果和本 skill 规则逐条推理后，直接写入目标 `.md` 文档。

允许使用工具的边界：
- **允许**：源码检索、cscope 分析、格式校验、图块抽取渲染、PNG 生成、DOCX 转换、编号一致性检查等验证/转换工具。
- **禁止**：编写或运行会自动拼装 SWDD 正文、自动生成章节文本、自动生成 Mermaid/PlantUML 图源码、自动批量填表的文档生成脚本。
- 若已有生成脚本输出与本 skill 冲突，必须以本 skill 为准直接修订 `.md`，不得通过调整生成脚本后重新生成正文来替代人工推理编制。

**核心约束摘要：**
1. **正文直接编制**：不得用文档生成脚本自动生成 SWDD 正文、图源码或表格；必须由 LLM 逐条推理后直接写入 `.md`。
2. **禁止简化**：不得使用 Same pattern、omitted for brevity、Details omitted 等概括替代具体内容。
3. **一一对应**：每个对外/对内接口、每张图须与源码一致。
4. **2.4 静态图**：须包含本模块全部对外接口及与 Callers/下层的连线；2.4.2 表与 2.7/2.8 一致无遗漏。
5. **2.6 动态图**：须为 PlantUML 序列图；调用链完整，不得越级。
6. **2.7/2.8**：每个函数必须有完整 Mermaid 流程图。
7. **流程图分支编号**：每个判断出边必须用编号+右括号标注，格式 `-->|"1) Y"|` / `-->|"2) N"|`，禁止裸的 `"Y"`/`"N"`。**同一流程图内的所有分支必须连续编号**。
8. **流程图代码语言**：流程图中处理框/判断框必须为实际代码，禁止自然语言或概括描述。
9. **流程图与源码一一对应（重要！）**：
   - 每个流程图必须与源代码逐行对应，不得简化或编造
   - 空函数就是空函数（只有`}`），不能添加任何虚构步骤
   - 变量名、函数调用、赋值语句必须与源码完全一致
   - 禁止添加源码中不存在的操作（如"Clr Alarm"、"Set Status"等泛化描述）
10. **函数分类**：
   - External函数：被外部模块实际调用
   - Internal函数：仅被本模块函数调用

### 编写流程图前的源码分析检查清单（必须逐项完成！）

**每个状态机状态（case）编写流程图前，必须先分析源码：**

```
源码分析模板：
case IS_XXX:
    // 1. 第一个if语句
    if(条件1) {
        操作A;
        操作B;
        return/break;  // ← 关键：是否有return/break？
    }

    // 2. 第二个if语句（独立if，非if-else）
    if(条件2) {        // ← 关键：是否与第一个if互斥？
        操作C;
        操作D;
        return/break;  // ← 关键：是否有return/break？
    }

    // 3. entry & during（赋值语句）
    赋值语句1;
    赋值语句2;

    // 4. 第三个if语句
    if(条件3) {
        操作E;
        return/break;  // ← 关键：是否有return/break？
    }
    break;
```

**关键判断规则：**
| 源码结构 | 流程图绘制 | 示例 |
|---------|-----------|------|
| if后有 **return** | 该动作节点 → 直接到End | ArmingToDisarmed → End |
| if后 **无return**，后面还有代码 | 该动作节点 → 继续连接到下一个检查 | ArmingToIntDiag → ArmingExit2Check |
| if-else（互斥） | Y分支和N分支都画，但不能同时存在 | 判断框有两个分支 |
| 两个独立if（非if-else） | 两个独立的检查路径，后续if的入口需要额外连接 | ArmingExit1 → ArmingToIntDiag → ArmingExit2Check |
| **常量条件 if/while** | **只画实际可达的固定路径**：`if(1)`/`while(1)` 只连接到真路径；`if(0)`/`while(0)` 只连接到假路径；该唯一出边不标编号；禁止画不可能分支或自环 | `do {...} while(0)` 的 `while(0)?` 节点只能直接连到后续代码 |
| **ASSERT(条件)** | **必须作为判断分支**：Y分支继续正常流程，N分支连接到 "ASSERT failure" → End | 见下方 ASSERT 规则 |
| **switch-case** | **每个case和default分支都必须带编号**，格式 `-->\|"N) case值"\|`，编号与其他判断分支统一连续 | 见下方 switch-case 规则 |

### 常量条件 if/while 只画固定可达分支（重要！）

**规则**：源码中的 `if(1)`、`if(0)`、`while(1)`、`while(0)` 是编译期/代码固定条件，不是运行时二选一判断。流程图中必须保留判断框的实际代码表达式，但只能画实际可达的一条路径。由于没有两种及以上分支选择，这条唯一出边**不标注编号，也不标注 T/F/Y/N**。

| 源码条件 | 流程图分支 | 禁止 |
|---------|------------|------|
| `if(1)` | 只画 `-->` 到 if 体 | 禁止画 F 分支；禁止给唯一出边编号 |
| `if(0)` | 只画 `-->` 到后续代码 | 禁止画 T 分支；禁止给唯一出边编号 |
| `while(1)` | 只画 `-->` 到循环体/持续循环路径 | 禁止画 F 分支；禁止给唯一出边编号 |
| `while(0)` | 只画 `-->` 到后续代码 | 禁止画 T 分支或自环；禁止给唯一出边编号 |

**典型场景：`do { ... } while(0)`**
```mermaid
flowchart TD
    Body["actual statements in do block"] --> LoopCheck{"while(0)?"}
    LoopCheck --> Next["next statement after do-while"]
```

**错误做法**：
```mermaid
    LoopCheck{"while(0)?"}
    LoopCheck -->|"1) T"| LoopCheck
    LoopCheck -->|"2) F"| Next
```

**编号要求**：固定路径不参与全图连续编号。例如前一个真正分支编号到 `8)`，中间出现 `while(0)` 的唯一出边不编号，后续真正分支仍从 `9)` 继续。

### switch-case 分支必须全部编号（重要！）

**规则**：switch-case 语句在流程图中表示为判断菱形框，其所有分支（每个 case 值 + default）必须带编号，且与整个流程图的编号体系连续。

**错误做法**：
```mermaid
    SwitchAxis -->|"MC36XX_AXIS_X"| SetX["..."]
    SwitchAxis -->|"MC36XX_AXIS_Y"| SetY["..."]
    SwitchAxis -->|"default"| Next
```
问题：分支没有编号，且判断框文本不明确。

**正确做法**：
```mermaid
    SwitchAxis{"switch(axis)"}
    SwitchAxis -->|"1) MC36XX_AXIS_X"| SetX["_bRegData = 0x01"]
    SwitchAxis -->|"2) MC36XX_AXIS_Y"| SetY["_bRegData = 0x02"]
    SwitchAxis -->|"3) MC36XX_AXIS_Z"| SetZ["_bRegData = 0x03"]
    SwitchAxis -->|"4) default"| Next
```

**要点**：
- 判断框文本使用 `switch(变量名)` 格式，不能只写 `变量名?`
- 每个 case 值和 default 都必须有编号
- 编号与其他 if/else 判断分支连续递增（不单独编号）
- 即使 default 分支只是 break 不做任何事，也必须画出并编号

### ASSERT 必须作为流程图判断分支（重要！）

**规则**：源码中的 `ASSERT(条件)` 不是普通的赋值语句，它是一个**运行时检查**，必须在流程图中体现为判断菱形框，包含 Y/N 两个分支：
- **Y 分支**：条件成立，继续正常流程
- **N 分支**：条件不成立，进入 "ASSERT failure" 处理框 → End

**Mermaid 示例**：
```mermaid
flowchart TD
    PrevStep --> AssertChk{"ASSERT:<br/>pstrRequestSeed != NULL_PTR?"}
    AssertChk -->|"1) Y"| NextStep["正常流程继续"]
    AssertChk -->|"2) N"| AssertFail["ASSERT failure"]
    AssertFail --> End([End])
```

**错误做法**：将 ASSERT 视为普通语句放在处理框中，或直接省略不画。
**正确做法**：将 ASSERT 作为判断菱形框，标注 `ASSERT:` 前缀 + 判断条件，Y/N 分支各有编号。

**验证命令**：
```bash
# 在源码中查找所有 ASSERT 调用
grep -n "ASSERT(" {模块路径}/*.c
# 在对应流程图中确认 ASSERT 作为判断框存在
grep -i "ASSERT" swdd/{模块名}/img/*_Flowchart.mmd
```

### 流程图禁止任何形式的简写/缩写（重要！）

**规则**：流程图中所有标识符、函数调用、条件表达式必须与源码**完全一致**，禁止任何形式的省略或缩写。

**禁止的简写模式：**

| 禁止模式 | 示例（错误） | 正确写法 |
|---------|------------|---------|
| `...` 省略前缀 | `Rte_Write_...BbsLpc7LinFr01_` | `Rte_Write_Cfg_Tx_LPCSystem_LPC7LIN_BbsLpc7LinFr01_` |
| `...` 省略中间路径 | `strFr02...int_mem_ok` | `strFr02.SoundrBattBackedDiag.bits.int_mem_ok` |
| `...` 省略函数参数 | `AesCmacVerify(key, ...)` | `AesCmacVerify(key, len, plain, &authLen, authData, OPT)` |
| `...` 省略中间调用 | `mc_read_regs(X_LSB) ... mc_read_regs(Z_MSB)` | 逐个列出全部6次调用 |
| 范围简写 | `Nr1..Nr4`, `[0..3]`, `u8Index1..7` | 逐个列出每次赋值/调用 |
| 概括性描述 | `Any digit > 0x09?` | `serialUnits > 0x09 \|\|<br/>serialTens > 0x09 \|\|<br/>serialHundreds > 0x09 \|\|<br/>serialThousands > 0x09?` |
| 描述性过程 | `Validate serial BCD digits` | 逐行列出实际的变量提取代码 |
| 半条件省略 | `X < MIN \|\| > MAX` | `X < MIN \|\| X > MAX`（两侧都写完整变量） |

**验证命令**：
```bash
# 检查流程图中是否存在简写
grep -n '\.\.\.' swdd/{模块名}/img/*_Flowchart.mmd
# 应该无输出。如果有 "..." 就是简写。
```

**原因**：详设文档是代码审查和测试的基准，简写会导致：
1. 审查人员无法确认是否与源码一致
2. 测试人员无法依据流程图编写完整测试用例
3. 后续维护时无法判断简写代表的具体内容

### 死代码必须排除（重要！）

**规则**：以下三类"死代码"中的函数**禁止写入 SWDD 文档**的任何位置（静态图、总览表、动态图、函数详设）：

**三类死代码：**

| 类型 | 定义 | 示例 |
|------|------|------|
| 1. 条件编译未启用 | `#ifdef MACRO` 块内且该宏未 `#define`；`#if 0` 块内 | `#ifdef DMEM_FLS_FUNCTION_ENABLE` 包裹的 `DMEM_u8BlankCheck` |
| 2. 代码被注释 | 函数体、extern 声明或调用处被 `//` 或 `/* */` 注释掉 | `// extern void ADESC_vidDisable48VOptRsnInit()` |
| 3. 定义了但无有效调用路径 | 函数存在于 .c 文件中，但**所有潜在调用路径上都缺少一环有效代码**（直接调用、函数指针/地址存入数组/结构体、通过 `section` 段被硬件间接读取 —— 任一路径需全链路均在有效编译路径中，缺一环即作废） | `DESC_vidStorNewRsn` 唯一直接调用被注释；`MCU_vidFastWkupBootAddress` 仅通过 `FastWkupBootVectorTable[1]` 间接引用，但该表写入 `DCMRWF5` 的代码被 `#if 0` 包裹 ⇒ 硬件路径作废 ⇒ 死代码 |

**检查步骤**：

**类型1 - 条件编译未启用：**
```bash
# 查找源码中所有 #ifdef / #if 0 块
grep -n "#ifdef\|#ifndef\|#if 0" {模块路径}/*.[ch]
# 检查每个宏是否在项目中定义
grep -r "#define 宏名" {项目根}/
```

**类型2 - 代码被注释：**
```bash
# 查找 int.h 中被注释掉的 extern 声明
grep -n "//.*extern" {模块路径}/*.h
```

**类型3 - 定义了但无调用方（最重要！）：**

**⚠️ 必须使用 cscope 而非 grep 做调用方查询。** 详细命令见 [references/cscope_usage.md](references/cscope_usage.md)。

```bash
# 查找某函数的所有调用者（caller）
cscope -dL -3 函数名
# 无输出 = 没有调用方 = 死代码候选
# 注意：必须追踪完整的 RTE 宏链！
# 例如 HPWM_vidPwmInit → DRTE_vidPwmInit → HRTE_vidPwmInit → SRTE_vidPwmInit → SMIC_vidPwmInit
# 逐层 cscope -dL -3 向上追踪，直到链条末端仍无调用方，才算死代码
```

**⚠️ `cscope -3` 只有定义行的判定规则（重要！）：**

`cscope -dL -3 函数名` 查询 caller 时，如果：
- 无输出；或
- 只有一条输出，且该输出是函数自身定义行/声明附近的伪 caller

则不能视为存在实际调用方，应按“无直接调用方”处理，并继续执行：

```bash
cscope -dL -0 函数名
```

`-0` 结果判定规则：
- 只包含 `extern` 声明和函数定义 → 死代码候选
- 唯一取地址/注册点在 `//`、`/* */`、`#if 0`、未启用 `#ifdef` 中 → 死代码候选
- 找到有效 callback 表、函数指针表、section 表注册点 → 继续追踪该注册点是否被有效使用，不能直接判死代码

**典型模式**：某个诊断服务回调、通信回调、定时器通知或其他 callback 函数虽然仍有源码定义，但它唯一的 callback/DCM/函数指针配置表注册点被 `//`、`/* */` 注释掉，或被 `#if 0` / 未启用 `#ifdef` 屏蔽，则该函数没有有效运行路径，应按不可达函数处理。

**⚠️ 调用方有效性验证（极其重要！）：**
- cscope 找到调用方后，**必须检查调用方所在的上下文是否有效**：
  - 调用方在 `#if 0` 块内 → 无效（如 `ADESC_u8GetDvLinGroup` 唯一调用在 LinIf.c 的 `#if 0` 块内）
  - 调用方在 `#ifdef MACRO` 块内且宏未定义 → 无效
  - 调用方被 `//` 或 `/* */` 注释掉 → 无效
  - 只有调用方在正常编译路径中才算有效调用
- **验证方法**：cscope 输出中已附带文件路径和行号（格式 `<文件> <函数> <行号> <源码>`），用 Read 工具打开对应位置前后 5~10 行，人工确认不在条件编译/注释块内。cscope 本身不理解 `#if 0` 等非启用分支。

**注意**：
- 始终编译的函数（`#ifdef` 块外面的）且有调用方的正常写入
- RTE 宏链（DRTE→HRTE→SRTE→SMIC）必须追踪到底，不能只看直接调用
- **间接调用路径**（函数指针数组、地址存入 `section` 段被硬件读取、callback 注册表等）同样要求**全链路在有效编译路径中**：cscope 找到的取地址点（`-0` 查所有引用）必须逐一追踪到最终激活点（寄存器写入/硬件段配置/注册函数调用），任一环节被 `#if 0` / 注释 / 未定义宏打断，该路径作废；所有路径均作废 ⇒ 死代码。`section(...)` + linker `KEEP` 只保证 bytes 留在 flash，不代表运行时可达。

### 静态图必须展开所有函数，禁止通配符分组（重要！）

**规则**：2.4.1 Static Diagram 中必须列出**每一个**函数的独立节点，禁止使用通配符（`*`）或分组简写。

**禁止的简写模式：**

| 禁止模式 | 示例（错误） | 正确写法 |
|---------|------------|---------|
| 通配符分组 | `ADESC_vidReadDid_*` | 逐个列出每个 ReadDid 函数节点 |
| 斜杠分组 | `ADESC_vid/u16 SupplierID/FunctionID` | 分别列出 vidSetSupplierID, u16GetSupplierID, vidSetFunctionID, u16GetFunctionID |
| 范围分组 | `ADESC_bolLinDrv*Flg` | 逐个列出每个 LinDrv 标志函数 |

**正确做法**：
- 静态图节点数量必须与 2.4.2 Component Overview Table 的函数数量一致
- 用 `subgraph` 按功能分组保持可读性（如 "DID Read (FD00-FD09)"、"LIN Driver Flags" 等）
- 外部调用方应精确标注（如 `Rte.c`、`LinIf`、`SMIC` 等），不要用模糊的 "DCM" 或 "LIN Driver"
- 通过 SRTE 宏映射的调用应标注 `(via SRTE)`

**验证命令**：
```bash
# 检查静态图是否有通配符
grep '\*\|\.\.\./' swdd/{模块名}/img/*Static_Diagram*.mmd
# 应该无输出
# 对比函数数量
grep -c '^\|' swdd/{模块名}/{文档前缀}_*_EN.md | head -5  # 表格行数
grep -c '"\w' swdd/{模块名}/img/*Static_Diagram*.mmd  # 节点数
```

### 删除函数后必须全局重编号（重要！）

**规则**：从 SWDD 中移除一个函数后，必须同步更新文档中**所有**编号，不能只改紧邻的一个。

**必须更新的编号清单：**

| 项目 | 格式 | 示例 |
|------|------|------|
| 1. 章节标题 | `#### 2.7.X 函数名` / `#### 2.8.X 函数名` | 2.7.4→2.7.3, 2.7.5→2.7.4, ... |
| 2. Figure 引用 | `**Figure 2-7-X: 函数名 Flowchart**` | Figure 2-7-4→2-7-3, ... |
| 3. Unit ID | `ADESC_unit_XX` | unit_04→unit_03, unit_05→unit_04, ... |

**⚠️ 禁止手动逐个替换** — 必须使用脚本批量处理，避免遗漏：

```python
import re
# 重编号章节标题
ext_counter = 0
for i, line in enumerate(lines):
    m = re.match(r'^(#### 2\.(7|8))\.\d+ (.+)$', line)
    if m:
        section = m.group(2)
        if section == '7':
            ext_counter += 1
            lines[i] = f'{m.group(1)}.{ext_counter} {m.group(3)}'

# 重编号 Figure 引用
ext_fig = 0
def fix_figure(match):
    global ext_fig
    ext_fig += 1
    return f'**Figure 2-7-{ext_fig}: {match.group(2)}'
content = re.sub(r'\*\*Figure 2-(7)-\d+: (.+)', fix_figure, content)
```

**验证命令**：
```bash
# 检查章节编号是否连续
grep -n "^#### 2.7" swdd/{模块名}/*.md | awk -F'.' '{print $NF}' | awk '{print $1}' | sort -n | uniq -d
# 有输出说明有重复编号
```

### 经验教训：赋值语句不重复原则 ⚠️

**问题描述**：在状态机流程图中，entry/during阶段的赋值语句（如设置LIN信号）只在状态开始时执行一次。Stay节点表示"所有条件都不满足后break"，不应该再包含已执行过的赋值语句。

**错误示例**：
```
源码:
case IS_ARMING:
    strBbsLpc7LinFr02.SoundrSnsrInclnArmSts = AlrmSts_DisarmedArming;  // entry赋值，只执行一次
    if(exit1条件) { ... }
    if(exit2条件) { ... }  // 两个独立if
    break;

错误流程图:
    ArmingSetStatus[...] --> ArmingExit1  (包含赋值语句 ✓)
    ArmingExit2Check -->|"12) N"| ArmingStay["strBbsLpc7LinFr02..."]  (错误！重复赋值)

正确流程图:
    ArmingExit2Check -->|"12) N"| ArmingStay[Remain in IS_ARMING]  (正确！不重复赋值)
```

**验证命令**：
```bash
# 检查Stay节点是否包含赋值语句（应该只有"Remain in XXX"）
grep 'Stay\[' swdd/{模块名}/img/*.mmd
# 正常应该全部是: Stay[Remain in XXX]
```

**验证方法：编写完流程图后，必须执行以下检查：**
```bash
# 检查所有连接到End的节点，确认它们只有一条出边
grep '\-\-> End' swdd/{模块名}/img/*.mmd | sed 's/:[[:space:]]*/ /' | sed 's/[[:space:]]*\-\-> End.*//' | sort -u | while read node; do
  total=$(grep "^    ${node} \-\-> " swdd/{模块名}/img/*.mmd 2>/dev/null | wc -l)
  if [ "$total" -gt 1 ]; then
    echo "ERROR: $node has $total outgoing edges but connects to End!"
  fi
done
```

---

## 函数关系分析工具 — cscope（必用）

**规则**：所有函数定义查找、引用查找、调用关系（caller/callee）分析必须使用 `cscope`，**禁止用 `grep -rn "函数名"` 做调用分析**。grep 仅用于非 C 语义的搜索（markdown/mmd/puml 格式校验、`#ifdef` 宏名扫描等）。

**前置条件**：项目根目录必须存在最新的 cscope 数据库（`cscope.out`）。源码变更后必须 `cscope -bqk` 重建。

**核心命令速查**（全平台一致）：
- `cscope -dL -1 <函数>` 查定义
- `cscope -dL -2 <函数>` 查 callee（本函数调用了谁）
- `cscope -dL -3 <函数>` 查 caller（谁调用了本函数）
- `cscope -dL -0 <符号>` 查所有引用

**必须人工补救的 cscope 限制**：
1. cscope **不理解 `#if 0` / `#ifdef`** 未启用分支 —— 找到 caller 后必须 Read 上下文确认是否在有效编译路径内
2. **宏函数链/适配层链**（如 API alias→RTE wrapper→HAL wrapper→实际调用点）必须手动沿链逐层 `-3` 追踪
3. **函数指针 / 回调**需通过注册点手动关联

**详细使用说明**（数据库构建跨平台脚本、完整命令表、SWDD 用例、跨平台细节）：见 [references/cscope_usage.md](references/cscope_usage.md)。安装步骤见 [SETUP.md](SETUP.md) 第 6 节。

---

## 文档结构

**标题层级与章节清单是唯一权威，见：** [references/SWDD_Mandatory_Requirements.md § 1 总体原则](references/SWDD_Mandatory_Requirements.md#1-总体原则)

下方 "各章节详细要求" 仅说明每一节应填什么内容，**不再重复层级定义**。若层级与 Mandatory Requirements 冲突，以 Mandatory Requirements 为准。

---

## 快速开始

1. 获取模块源代码（.c/.h文件）
2. 分析代码中的函数、变量、调用关系
3. 按照模板结构填写各章节内容
4. 验证所有函数调用关系的正确性

---

## 各章节详细要求

### 1.1 Purpose（目的）

模板格式（`{模块名}` 替换为实际模块名）：
```
The purpose of this document is to explain the results of detailed design of {模块名} software, and provide input for unit construction by defining the internal structure, interface and dynamic behavior of components.
```

### 1.2 Scope（范围）

固定格式：
```
This strategy is applicable to the detailed design of BBS_P519_V436 project software, including the unit design of all software in all stage.
```

### 1.3 Reader（读者）

固定格式，使用编号列表：
```
1) Software developers
2) Software Testers
3) Software architects
4) QA and Assessor
```

### 1.4 Reference（参考文档）

表格格式：
```
| No. | References | Version |
|-----|------------|---------|
| 1 | BBS_P519_V436 project BBS product software requirement specification | Latest version |
| 2 | BBS_P519_V436 project BBS product software architecture design specification | Latest version |
```

### 1.5 Terminology and Abbreviation（术语和缩写）

分两个表格：

**1.5.1 Terms（术语定义）：**
```
| NO. | Terms | Definition |
|-----|-------|------------|
| 1 | BBS | Battery Backed-up System |
| 2 | LIN | Local Interconnect Network |
```

**1.5.2 Abbreviations（缩写说明）：**
```
| Abbreviations | Full spelling | Notes |
|---------------|---------------|-------|
| {模块名} | {全称} | {说明} |
```

---

### 2.1 Component Introduction（组件简介）

简要描述模块的主要职责和在系统中的作用。一段话即可。

### 2.2 Main Function Description（主要功能描述）

列出模块的主要技术要点和实现方法，使用编号列表：
```
Main technical points and implementation methods of the {模块名} module:

1. {功能点1}: {简要描述}
2. {功能点2}: {简要描述}
```

### 2.3 Component Files（组件文件）

**重要：文件清单必须通过遍历 `{模块路径}/*.c` 和 `{模块路径}/*.h` 的实际输出生成，一个文件一行，完全不对文件名做后缀假设！**

**生成步骤：**

1. `ls {模块路径}/*.c {模块路径}/*.h` 得到实际文件列表
2. 对每个文件，打开读前 50 行获取 header comment 中的 `Description:` 字段
3. 若无 header comment，根据**文件内容**描述用途（参考下表），**不以文件名后缀反推角色**

**内容驱动的描述写法（仅作为经验模板，不强制）：**

| 文件内容特征 | 推荐描述 |
|------------|---------|
| 大量函数定义 + 状态机/主循环/处理逻辑 | 主要实现逻辑（The main implementation of the component's function） |
| `extern` 声明 + typedef + 无函数体 + 被 `{模块路径}/` 之外的 `.c` 引用 | 对外接口头文件（The external interface header file） |
| `extern`/`static` 声明 + 只被 `{模块路径}/` 内部引用 | 私有头文件（The private header file, containing declarations used only within this module） |
| 大量 const 数组 / 配置表 / 标定数据 | 配置数据源文件 |
| 大量 `#define` 开关 / 功能配置宏 | 功能配置头文件 |
| 封装其他模块/驱动的适配层调用 | 适配层（子组件）实现 |

**表格格式**：

```
| No. | Filename | Description |
|-----|----------|-------------|
| 1 | <实际文件名> | <根据 header comment 或内容特征填写的描述> |
| 2 | ... | ... |
```

**输出顺序（固定，保证 docx 转换稳定）**：
1. 主实现 `.c`（通常一个；多子组件时按子组件聚类，组内主 `.c` 在前）
2. 其它 `.c`（如 `_cfg.c` 等配置数据源文件）
3. 对外 `.h`（`#include` 扫描确认被跨目录引用的）
4. 私有 `.h`（`_priv.h` / 仅本目录内 include 的）
5. 配置/功能开关 `.h`（`_cfg.h` / `_funcfg.h` 等，仅内部使用但属性是"配置"）

例（DSPI）：`DSPI_prg.c` → `DSPI_cfg.c` → `DSPI_int.h` → `DSPI_priv.h` → `DSPI_cfg.h`。

**示例（AINCU, APP 惯例命名）**：
| No. | Filename | Description |
|-----|----------|-------------|
| 1 | AINCU_prg.c | 主要实现逻辑 |
| 2 | AINCU_int.h | 对外接口头文件 |
| 3 | AINCU_priv.h | 私有头文件 |
| 4 | AINCU_cfg.h | 配置头文件 |
| 5 | AINCU_cfg.c | 配置数据源文件 |

**示例（ADIAP, bl_desc* 命名）**：12 个文件全部列出，每个都根据内容给出描述，不假设任何命名对应关系。

**禁止**：
- 不得跳过目录里实际存在的文件
- 不得把不在目录里的文件（基于惯例想象）填进表
- 不得按文件名后缀机械推断描述（如看到 `_prg.c` 就写"主实现"，而忽略实际内容）

---

### 2.4 Static Diagram（静态图）

#### 2.4.1 Static Diagram Picture

**插入Mermaid源码**（不是PNG图片），包含以下子图：
- **External Modules**：调用本模块的外部模块
- **Module External Functions**：本模块的外部接口函数
- **Module Internal Functions**：本模块的内部函数
- **Lower Modules**：本模块调用的下层模块

**语法要求**：
- 开始/结束节点：使用 `Start([Start])` / `End([End])`

**关键要求：**
- 通过 **cscope**（非 grep）确认每个函数的调用者：`cscope -dL -3 <函数名>` 列出 caller；`cscope -dL -2 <函数名>` 列出 callee。详见 [references/cscope_usage.md](references/cscope_usage.md)
- 移除死代码（空函数、未被调用的函数）
- 外部模块必须与本模块函数有连线
- **双向检查**：外部模块→本模块，本模块→外部模块
- **宏定义函数必须追踪完整调用链（重要！）**：
  - 如果函数是宏定义（如 `#define HPWM_vidPwmInit DRTE_vidPwmInit`），必须沿 RTE 宏链向上追踪到实际调用者
  - 追踪路径：DRTE→HRTE→SRTE→SMIC_cfg.h→SMIC_prg.c（或其他实际调用点）
  - 静态图中必须画出"实际调用者 --> 宏函数"的连线
  - 示例：`SMIC_vidPwmInit()` → `SRTE_vidPwmInit` → `HRTE_vidPwmInit` → `HPWM_vidPwmInit`，静态图中画 `SMIC --> vidPwmInit`
  - **不能因为函数是宏就省略上游调用连线**

#### 2.4.2 Component Overview Table

```
| Component ID | Unit ID | Unit name | External/Internal Function | SW unit description | ASIL level |
|--------------|---------|-----------|---------------------------|-------------------|------------|
| {模块名} | {模块名}_unit_01 | 函数名 | External | 功能描述 | QM |
```

- Unit ID连续（unit_01, unit_02...）
- 与2.4.1和2.7/2.8一致

---

### 2.5 Data Design（数据设计）

#### 2.5.1 Global Data（全局数据）

**只列出本模块定义的全局/静态变量**

表格格式：
```
| Name | Scope | Type | Range | Unit | Accuracy | Error | Offsets | Initial | Description |
|------|-------|------|-------|------|----------|-------|---------|---------|-------------|
```

- Scope：extern（全局）或static（静态）
- Unit列：只有物理单位才填（s/ms/A/V等），计数值填`-`

#### 2.5.2 Data Structure（数据结构）

只列出本模块定义的结构体，**不是本模块使用的**

表格格式：
```
| Data Type | Member | Description |
|-----------|--------|-------------|
| **StructName** | type member1 | Description |
| | type member2 | Description |
```

#### 2.5.3 Enum（枚举）

只列出本模块定义的枚举

表格格式：
```
| Enum Name | Member | Value | Description |
|-----------|--------|-------|-------------|
| **EnumName** | ENUM_A | 0 | Description |
| | ENUM_B | 1 | Description |
```

#### 2.5.4 Constant（常量）

- 宏定义常量（#define数值）
- const变量

表格格式：
```
| Name | Value | Description |
|------|-------|-------------|
| CONST_NAME | 100 | Description |
```

#### 2.5.5 Calibration（标定参数）

固定内容：
```
Reference to "BBS_SPA3 Calibration Parameter Table"
```

---

### 2.6 Dynamic Behavior（动态行为）

**必须插入PlantUML源码**（不是PNG图片）

⚠️ **禁止使用 `![xxx](img/xxx.png)` 格式插入动态图，必须使用代码块嵌入PlantUML源码**

**⚠️ 重要：函数调用完整性要求**
- **必须逐行扫描本模块的所有 `.c` 源文件**（`ls {模块路径}/*.c` 枚举，不限命名；单子组件模块常为一个 `.c`，多子组件模块可能多个 `.c`）
- 确保所有函数调用（对外部模块、内部函数、下层BSW的调用）都要体现在动态图中
- 不能遗漏任何实际被编译执行的函数调用
- **宏定义的External函数也必须在动态图中体现（重要！）**：
  - 如果函数通过宏链被外部模块调用（如 SMIC → SRTE → HRTE → HPWM_vidPwmInit），动态图中必须画出该调用
  - 检查方法：遍历 Component Overview Table 中所有 External 函数，逐一确认每个函数在动态图中都有对应的调用场景
  - 特别注意 Init/DeInit 类宏函数，它们通常在 System Initialization 阶段被调用，容易遗漏

**⚠️ 忽略未被编译的代码**
- 条件编译 `#if`、`#ifdef`、`#ifndef` 等不生效的分支不需要体现
- 只体现实际会被编译执行的代码路径

**Legend（表格格式，放在图上方）：**
```
| Color | Description |
|-------|-------------|
| Blue (#a8d4ff) | 本模块外部函数 |
| Green (#98FB98) | 本模块内部函数 |
| Yellow (#FFEB99) | 外部模块函数 |
```

**节点要求：**
- 本模块所有External + Internal函数（与2.4.2组件表一致）
- 外部模块函数（调用本模块的 + 本模块调用的）

**箭头标签规则：**
- 外部模块→本模块：写**调用者函数名**
- 本模块内部调用：写**调用者的形参**（无形参则不写）
- 本模块→外部模块：写**被调用者函数名**

**状态分隔符：** `== 状态名 ==`

**生命周期（activate/deactivate）要求：**
- 每个被调用函数必须有 `activate` 和 `deactivate` 标记其生命周期
- activate 放在函数被调用后，deactivate 放在函数返回前
- 外部模块调用本模块时，本模块函数需要 activate/deactivate
- 本模块调用内部函数或下层模块时，被调用者需要 activate/deactivate
- ⚠️ **特别注意**：主函数（如 AINCU_vidMainFunction）的生命周期必须贯穿整个状态机，不能在中间某个状态后就结束！deactivate 应该在整个函数执行完毕后才出现
- ⚠️ **不要使用 `return` 关键字**：PlantUML 的 return 会终止整个生命周期，导致后续状态无法显示
- ✅ **void函数返回规则（重要！）**：
  - 如果被调用函数的返回类型是 **void**，**不需要画返回箭头**
  - 例如：`HRTE_vidSetPortHBridge_NSleep()` 是 void 函数，调用时只需 `activate` / `deactivate`，不需要 `--> return`
  - 只有**非void函数**（有返回值）才需要画返回箭头
- ⚠️ **同一状态内的多个条件分支必须使用 `alt/else/end` 结构**，不能使用多个独立的 `alt/end`，否则会导致生命周期线显示不正确
- ⚠️ **不要把数据数组误认为外部模块**：例如 "Calibration" 通常只是从 Calibration_Data_Array 读取数据的内部操作，不是外部模块。必须通过 grep 源代码确认是否有实际的外部模块调用
- 示例：
  ```
  MainFunc -> IntDiag :
  activate IntDiag
  IntDiag -> HRTE : HRTE_vidXxx()
  activate HRTE
  HRTE --> IntDiag : return
  deactivate HRTE
  deactivate IntDiag
  ```

**PlantUML换行符规则（重要！）：**
- PlantUML 序列图中的消息标签换行必须用 `\n`，**禁止使用 `<br/>`**
- `<br/>` 在 PlantUML 中会被当作纯文本渲染出来
- Mermaid flowchart 中换行仍使用 `<br/>`（Mermaid 语法正确支持）
- 示例：`A -> B : funcName(param1,\nparam2,\nparam3)` ✅
- 错误：`A -> B : funcName(param1,<br/>param2,<br/>param3)` ❌

**PlantUML样式设置（必须在图开头添加）：**
```
@startuml
skinparam backgroundColor #FFFFFF
skinparam participantPadding 10
skinparam boxPadding 10
skinparam sequenceArrowThickness 2
skinparam roundcorner 10
skinparam SequenceGroupBodyBackgroundColor transparent
skinparam SequenceGroupBackgroundColor transparent
...
```

**⚠️ alt/opt/group 框必须透明背景**：上面两条 `SequenceGroup*BackgroundColor transparent` 是**强制的**。PlantUML 默认会给 alt/opt/group 框体填白色、给标签头填浅灰（#EEEEEE），这会**遮盖下方的状态色块**（黄 #FFEB99 / 蓝 #A8D4FF / 绿 #98FB98），导致动态图里看不出当前调用属于哪个状态分区。设为 transparent 后，alt 框体只剩边框，状态色块能透过来。**生成新 puml 时必须包含这两条；改老 puml 也要补上。**

**⚠️ 强制检查清单（必须完成所有项才能编写动态图）：**

- [ ] 已完整阅读本模块所有 `.c` 源文件（`ls {模块路径}/*.c`，从第一行到最后一个函数，多子组件时逐个文件完整读一遍）
- [ ] 已识别所有状态机（switch-case语句）的所有case分支
- [ ] 已识别所有if-else if-else条件分支
- [ ] 已对照每个状态/分支的实际代码，列出所有函数调用及位置（行号）
- [ ] 已忽略 `#if`/`#ifdef` 条件编译中不生效的代码
- [ ] 已将所有实际调用的函数添加到动态图中
- [ ] 已确保每个被调用者都有对应的 activate/deactivate 标记
- [ ] 已交叉验证：动态图中的调用与源代码一一对应
- [ ] **已验证函数调用关系**：特别检查内部函数（如bbs_func）是否有错误调用
  - 如果调用链是：MainFunc → SRTE获取参数 → MainFunc → bbs_func(参数)
  - 动态图中应体现为：MainFunc → SRTE → MainFunc → bbs_func
  - **不能错误画成**：MainFunc → bbs_func → SRTE（这样就变成了bbs_func调用SRTE）
  - 检查方法：在源码中确认参数是调用者获取后传入的，还是被调用者内部获取的

**⚠️ 特别注意：**
- **switch-case**：每个case分支都要单独体现，包括所有代码路径
- **if-else if-else**：每个分支都要单独体现，不能遗漏
- **嵌套结构**：嵌套的if/switch内部的所有调用都要体现

**函数调用提取步骤：**
1. 对 `ls {模块路径}/*.c` 列出的每个 `.c` 文件，依次打开阅读（不限命名）
2. **从头到尾完整阅读一遍**，理解整体逻辑
3. 找到所有状态机（switch-case），标记每个case
4. 对每个case，逐一检查内部的if-else if-else分支
5. 对每个if/else分支，记录其中的所有函数调用（包括行号）
6. 将所有函数调用按状态/分支添加到动态图中
7. 确保每个被调用者都有对应的 activate/deactivate 标记
8. **完成后再次对照源代码检查是否有遗漏**

---

### 2.7 External Function（外部函数）

每个External函数一个章节（2.7.1, 2.7.2...）

**函数属性表：**
```
| Attribute | Value |
|-----------|-------|
| Prototype | void func(void) |
| Location | xxx.c |
| Function Description | 功能描述 |
| Complexity | 1-5（见下方复杂度定义表） |
| Importance | 1-5（见下方重要度定义表） |
| Priority | (计算值 = Complexity × Importance) |
| Calls Func | 本函数调用的所有函数（逗号分隔） |
| Calling Func | 调用本函数的所有函数/位置（逗号分隔） |
| Storage alloc | 本函数的变量/数组存储分配说明（类型、大小、作用域） |
| constraint | 本函数运行中所受到的限制条件（调用顺序、前置依赖、中断上下文等） |
| Non-function | 本函数的非功能性需求（执行时间、重入性、中断安全等） |
| Branch No | 分支数量（判断分支总数，0表示无分支的顺序执行） |
| Verification Criteria | Unit Verification |
```

**部分字段填写说明：**

| 字段 | 填写要求 | 示例 |
|------|---------|------|
| **Calls Func** | 列出本函数体内直接调用的所有函数名，用逗号分隔；宏函数写宏名并标注实际映射（如 `SMIC_vidGptInit (macro -> Gpt_Init)`）；无调用写 `None` | `vidBistModeInit, vidNominalModeInit, vidRecoveryModeInit` |
| **Calling Func** | 列出项目中调用本函数的所有位置，用逗号分隔；通过宏链调用需标注（如 `SMIC_vidCallModesManagement (via SMIC_vidASPUInit macro)`）；从 main.c 调用写 `main.c`；从中断调用写 `GPT ISR` | `SMIC_vidCallStdInit` |
| **Storage alloc** | 列出本函数使用的局部变量和修改的全局变量，标注类型和大小；无变量写 `None` | `u8 u8IndexTaskLoc (local, 1 byte loop counter)` |
| **constraint** | 说明调用顺序约束、前置条件、中断上下文限制等 | `Must be called after MCAL init; called from interrupt context` |
| **Non-function** | 说明执行时间、重入性、中断安全性、循环次数等非功能性要求 | `Loop execution time proportional to TASK_NUMBER; interrupt-safe via critical section` |
| **Branch No** | 统计函数中的判断分支数（if/else if/else/switch-case/for/while 条件），0 表示纯顺序执行 |

**单元重要程度定义（Importance）：**

| 重要度 | 描述 |
|--------|------|
| 5 | 如果此单元发生错误将引起程序崩溃、无法启动；或引起重要功能流程无法贯通；或引起数据丢失、或导致错误的数据 |
| 4 | 如果此单元发生错误将导致重要功能不可用；或将导致功能实现不符合需求 |
| 3 | 如果此单元发生错误，影响主要功能不可用；或功能项与需求将产生重大偏差 |
| 2 | 如果此单元发生错误，功能项与需求将产生误差；或造成错误反馈引起用户理解歧义，导致错误操作 |
| 1 | 如果此单元发生错误，将产生提示上的误差 |

**单元复杂程度定义（Complexity）：**

| 复杂度 | 描述 |
|--------|------|
| 5 | 单元分支 >= 5 个；或代码嵌套层次 >= 3 |
| 4 | 单元分支 4 个；或存在 3 层嵌套 |
| 3 | 单元分支 3 个；或存在 2 层嵌套 |
| 2 | 单元分支 2 个 |
| 1 | 单元分支 1 个（含无分支的顺序执行） |

> **注意**：Complexity 应与 Branch No 字段一致。Branch No 是具体分支数，Complexity 是按上表映射后的等级。例如 Branch No = 7 → Complexity = 5。

**Parameters：**
- 无参数：`No input parameters and no return value`
- 有参数：**必须使用参数表**。
- 参数表表头固定为：

```
| Name | Type | Direction | Range | Unit | Accuracy | Error | Offsets | Initial |
|------|------|-----------|-------|------|----------|-------|---------|---------|
```

- 每个函数参数/返回值（若有）单独一行，`Name` 与 `Type` 必须从函数原型逐项拆分：
  - `bl_Buffer_t *buffer` → `Name = buffer`，`Type = bl_Buffer_t *`
  - `const bl_Buffer_t *key` → `Name = key`，`Type = const bl_Buffer_t *`
  - `bl_u32_t delay_value` → `Name = delay_value`，`Type = bl_u32_t`
- 函数返回值行填写规则：
  - 非 `void` 返回值必须单独列一行
  - 返回值行 `Name` 固定填写 `Return`
  - 返回值行 `Type` 填函数原型中的返回类型
  - `void` 返回值不在参数表中单独列行
- `Direction` 填写规则：
  - 函数形参 → `Input`
  - 即使形参是输出指针或输入/输出缓冲区指针（如 `respSize`、`Result`、`buffer`、`pu32flag`），也按函数形参统一填写 `Input`
  - 函数返回值 → `Output`
- `Range`：若源码/宏定义或项目 typedef 有明确范围，填写具体范围；基础类型范围必须按项目编译器/typedef 定义填写（如 `uint8_t`、`bl_u16_t`、`int` 等），不能确认时填 `-`。
- `Unit`：只有物理单位才填写（如 `ms`、`V`），无单位填 `-`。
- `Accuracy`、`Error`、`Offsets`：无明确设计约束时填 `-`。
- `Initial`：若函数原型存在默认实参则填写默认值；C 函数通常没有默认实参，填 `-`。


**Mermaid流程图语法（必须遵守）：**

- **开始/结束节点**：使用圆角矩形 `Start([Start])` / `End([End])`
  - ❌ 错误：`Start((Start))`、`End((End))`
  - ✅ 正确：`Start([Start])`、`End([End])`

- **分支编号格式**：`-->|"1) Y"|`、`-->|"2) N"|`
  - **统一格式**：只使用 `数字+右括号+Y/N` 格式（如 `1) Y`、`2) N`、`3) Y`、`4) N`），禁止使用圆圈数字（如 ①②③）
  - **常量条件例外**：`if(1)`/`while(1)`/`if(0)`/`while(0)` 只有一个固定路径，不标注编号，也不标注 T/F/Y/N
  - **连续编号**：同一流程图内的所有分支必须连续编号（1→2→3→4...），每个判断的Y/N分支接着上一个判断的编号
  - 示例：
    - 第1个判断：Y分支编号 `1) Y`，N分支编号 `2) N`
    - 第2个判断：Y分支编号 `3) Y`，N分支编号 `4) N`
    - 以此类推...

- **代码表达式要求（重要！）**：
  - ✅ 必须使用完整的代码表达式，与源码逐行对应
  - ❌ 禁止使用自然语言或简化描述（如"Get flag"、"Reset timer"、"Check status"）
  - ✅ 使用完整变量名：`bAccelerationChangeFlagLoc`（不是`bFlag`）
  - ✅ 使用完整函数名：`HRTE_bGetAccelerationChangeFlag()`（不是`GetFlag`）
  - ✅ 使用完整赋值表达式：`u16PeriodTime += AINCU_u8TASK_PERIOD_MS`
  - ✅ 使用完整函数调用：`as16InclineAngleNew[MC36XX_AXIS_X] = HRTE_s16GetInclineAngle(MC36XX_AXIS_X)`

- **双引号使用规则（重要！）**：
  - Mermaid节点文本中如果包含方括号 `[]`、圆括号 `()`、花括号 `{}`、大于小于号 `<>` 等特殊字符，**必须用双引号包裹**
  - 示例：
    - ✅ `["bAccelFlag = HRTE_bGetAccelFlag()"]` - 圆括号需要双引号
    - ✅ `["arr[i] = func(x)"]` - 方括号和圆括号需要双引号
    - ✅ `{arr[i] > threshold?}` - 判断框中方括号需要双引号
    - ❌ `[arr[i] = func(x)]` - 没有双引号会导致解析错误
  - **注意**：一旦某个节点使用了双引号，其他有特殊字符的节点也必须用双引号，否则会导致渲染不一致

- **长文本换行规则（重要！）**：
  - **触发条件**：当节点内文本（矩形框 `[]` 或菱形框 `{}`）超过约 **23个字符** 时，需要换行
  - **拆分位置**：在以下逻辑边界处换行
    - `.` (成员访问符)：`obj.member1.member2` → `obj.member1.<br/>member2`
    - `||` / `&&` (逻辑运算符)：`cond1 || cond2` → `cond1 ||<br/>cond2`
    - `==` / `!=` / `>` / `<` (比较运算符)：长条件表达式可在运算符处换行
  - **拆分示例**：
    - 矩形框：`["strBbsLpc7LinFr02.SoundrSnsrInclnArmSts = AlrmSts_Disarmed<br/>INCU_vidExitIsDisarmed()"]`
    - 菱形框：`{AINCU_strRxLpcLpc7LinFr01.<br/>SoundrSnsrInclnArmCmd<br/>== ArmReq_Disarm?}`
  - **注意事项**：
    - 必须与源码一致，不能自行简化变量名、函数名、表达式

- **变量声明**：在Start后添加LocalVar节点，列出所有局部变量
  - 示例：`LocalVar["u16PeriodTime, u8AlarmRetryCnt, bAccelFlagLoc, u8IndexTire"]`

- **判断框**：使用完整的条件表达式
  - 示例：`CheckPeriod{"u16PeriodTime >= AINCU_u16ANGLE_DETECTION_PERIOD_MS?"}`

**Figure编号 + Process Description**

---

### 2.8 Internal Function（内部函数）

格式同2.7

---

### 3 Appendix（附录）

**3.1 Design Methods**
```
It is recommended to use the following tools for static block diagrams, interface information (block definition diagrams and internal block diagrams in SysML), dynamic interactions (sequence diagrams, activity diagrams, state machines in SysML), and Simulink modeling for unit construction.
```

**3.2 Design Guidelines**
```
The coding specification adopts the "Coding Specification for Handwritten Code (C Language)" compiled by Shenzhen H&T Automotive Electronics Technology Co., Ltd.
```

**3.3 Traceability and Consistency Requirements**
```
Establish bidirectional traceability relationships between software architecture elements and software detailed design units through Rectify. The above linking relationships are implemented through model/code names and IDs of software detailed design units.

**Consistency Requirements:**
- Linking relationships: The links described in the above traceability relationships are available and correct
- Version matching: The versions of reviewed software requirements specifications, architecture design specifications, detailed design specifications, models, and code are correct and match
```

**3.4 Unit Verification Criteria**
```
| Verification Method | Verification Description | Success Criteria |
|--------------------|------------------------|------------------|
| Static Analysis | Use Polyspace static analysis tool for static analysis | All issues found by static analysis are fixed, or sufficient justification is provided for unfixed issues |
| Code Review | Organize code review meetings based on code review checklist items | All issues found in review are fixed, review passed |
| Dynamic Testing | Use Tessy tool for unit testing | Statement Coverage 100%, Branch Coverage 100% |
```

**注意：不需要 Document Revision History 部分**

---

## 关键检查清单

### 函数分类检查
- [ ] External函数：被外部模块实际调用
- [ ] Internal函数：仅被本模块函数调用
- [ ] 死代码：未被调用或空函数（需移除）

### 调用关系检查
- [ ] **使用 cscope（非 grep）确认每个函数的实际调用者**：`cscope -dL -3 <函数名>` 查 caller，`cscope -dL -2 <函数名>` 查 callee，详见 [references/cscope_usage.md](references/cscope_usage.md)
- [ ] 数据库已最新构建（`cscope -bqk`）
- [ ] 明确写出具体模块名，不用"其他模块"等模糊表述

### 图表检查
- [ ] **Mermaid语法正确**
- [ ] **Mermaid源码语法检查（必做）**：
  - `flowchart TD` 或 `flowchart TB` 前不能有多余空格（必须是行首）
  - 开始/结束节点必须使用 `Start([Start])` / `End([End])`，不能是 `Start((Start))` / `End((End))`
  - 代码块必须使用 ` ```mermaid` 标记，不能缺少反引号
- [ ] **2.4 静态图必须嵌入Mermaid源码**（禁止使用PNG：`![xxx](img/xxx.png)`）
- [ ] **2.6 动态图必须嵌入PlantUML源码**（禁止使用PNG：`![xxx](img/xxx.png)`）
- [ ] **流程图分支编号（必做）**：所有判断出边必须为 `-->|"1) Y"|` / `-->|"2) N"|` 等形式，且连续编号
- [ ] **流程图代码语言（必做）**：仅使用实际代码表达式，禁止自然语言或简化描述
- [ ] **流程图双引号使用（必做）**：节点文本中包含 `[]` `()` `{}` `<>` 等特殊字符时必须用双引号包裹
- [ ] **流程图完整变量名（必做）**：使用与源码一致的完整变量名和函数名，不能简化
- [ ] **流程图与源码一致（必做）**：判断条件、调用顺序、返回值与本模块 `.c` 源文件完全一致
- [ ] **流程图嵌套结构检查（必做）**：
  - 必须对照源代码逐行检查流程图
  - 特别注意if-else if-else嵌套结构：每个分支都要完整体现
  - 检查else分支是否遗漏：例如 if(A) { if(B) {...} } else { ... } 结构，else分支也要正确连接
  - 检查嵌套if后是否还有后续代码：嵌套if结束后可能还有后续操作
  - **特别注意独立if vs if-else**：
    - 独立if：两个或多个if语句依次执行，每个if都会被检查，可能同时触发（如IS_ARMING状态的exit1和exit2）
    - if-else：互斥结构，只能选择其中一个分支执行（如IS_ARMING_INT_DIAG状态的else-if）
    - 流程图中独立if要体现为多个独立的检查路径，if-else要用互斥结构表示
    - **常见错误**：在独立if的Y分支执行完后，错误地再画一条线连接到下一个判断节点。正确做法是每个if有自己独立的分支输出（如IS_ARMED状态有两个独立的if：第一个if判断结果，第二个if判断命令，两者都会执行）
    - 验证方法：检查从判断节点出来的分支是否都有对应的编号（如 `41) Y` 和 `42) N`），如果某个分支后面多了一条无编号的线连接下一个节点，说明画错了
  - **特别注意每个判断分支的输出数量**：
    - if判断：必须有且只有两个输出（Y和N）
    - **常量条件 if/while**：`if(1)` / `while(1)` 只有一个固定真路径；`if(0)` / `while(0)` 只有一个固定假路径；唯一出边不编号、不标注 T/F/Y/N
    - switch判断：可以有多个输出（case1、case2、default等）
    - 不能遗漏任何一个分支的输出
    - 示例：错误做法 `判断 --> "Y" ...`（缺少N分支）；正确做法 `判断 --> "1) Y" ... 判断 --> "2) N" ...`
  - **特别注意编号连续性**：
    - 每个判断节点的Y和N分支必须使用**连续编号**（如39) Y和39) N）
    - 编号不能重复使用：一个编号只能用于一个判断节点的一对输出
    - 添加新分支时，必须使用下一个可用编号
    - **自检验证命令**：`grep -oE '\|"[0-9]+\) [YN]' file.mmd | sort` 检查是否有重复编号
  - **特别注意判断节点的上游连接**：
    - 判断节点（菱形框）的上游可以是矩形框（处理框）或其他判断节点
    - 独立if场景：两个独立的if语句都可能连接到同一个判断节点（如IS_ARMED状态中，UnauCheck的N分支和ArmedToTriggered都指向ArmedDisarmCheck）
    - 这是正确的，因为两个独立if会依次执行
  - **特别注意矩形框（动作框）不能有两条分支**：
    - 矩形框（动作框 `[]`）表示执行某个动作，只有一条输出
    - **常见错误**：把矩形框画成有两条分支（如 `ArmedToTriggered --> End` 和 `ArmedToTriggered --> ArmedDisarmCheck`）
    - 矩形框如果需要连接到两个不同的后续节点，说明画错了，应该检查源码逻辑
    - **验证方法**：
      - `grep -n '\[.*\] --> ' swdd/{模块名}/img/*.mmd` 查看矩形框的出边数量
      - 正常情况：矩形框只有一条出边连接到下一个节点
      - 如果矩形框有两条出边，需要检查是否错误地将两个独立if画成了if-else
      - 独立if的正确画法：第一个if的Y分支执行完后，需要额外一条线连接到第二个if的入口（如 `ArmedToTriggered --> ArmedDisarmCheck`），但这是**从第一个if的矩形框连接到第二个if的判断框**，而不是矩形框本身有两条分支
- [ ] **ASSERT 必须作为判断分支（必做）**：
  - 源码中的 `ASSERT(条件)` 必须在流程图中体现为判断菱形框
  - 判断框文本格式：`ASSERT:<br/>条件表达式`
  - Y 分支：条件成立，继续正常流程
  - N 分支：连接到 `ASSERT failure` 处理框 → End
  - 验证命令：`grep -n "ASSERT(" *_prg.c` 对照 `grep -i "ASSERT" *_Flowchart.mmd`
- [ ] **switch-case 分支必须全部编号（必做）**：
  - 每个 case 值和 default 都必须有编号，格式 `-->|"N) case值"|`
  - 判断框文本使用 `switch(变量名)` 格式
  - 编号与 if/else 判断分支统一连续递增
  - 验证命令：`grep -E '-->\|"[^0-9]' swdd/{模块名}/img/*_Flowchart.mmd`（应无输出）
- [ ] **禁止任何形式的简写/缩写（必做）**：
  - 禁止 `...` 省略前缀、参数、中间调用
  - 禁止范围简写如 `Nr1..Nr4`、`[0..3]`、`u8Index1..7`
  - 禁止概括性描述如 `Any digit > 0x09?`、`Validate BCD digits`
  - 禁止半条件省略如 `< MIN || > MAX`（两侧都要写完整变量名）
  - 验证命令：`grep -n '\.\.\.' swdd/{模块名}/img/*_Flowchart.mmd`（应无输出）
- [ ] **条件编译函数必须排除（必做）**：
  - 扫描源码中 `#ifdef` / `#ifndef` / `#if 0` 块
  - 检查宏是否在项目中 `#define`，未定义则块内函数不得写入文档
  - 验证命令：`grep -n "#ifdef\|#ifndef\|#if 0" {模块路径}/*.[ch]`
  - 对每个宏：`grep -r "#define 宏名" {项目根}/`（无输出 = 未定义 = 排除）
- [ ] **流程图不得简化或编造（必做）**：
  - 必须对照源代码逐行检查流程图
  - 空函数就是空函数，不能添加虚构步骤
  - 变量名、函数调用、赋值必须与源码完全一致
  - 禁止添加源码中不存在的操作
- [ ] **img 目录完整性**：每个模块的 `img/` 目录下必须包含所有静态图、动态图、以及每个外部/内部函数的流程图文件
- [ ] 图表下方有编号（Figure 2-X-X）
- [ ] 图表下方有Process Description

### 动态图箭头标签验证引擎（重要！）

**⚠️ 生成动态图后，必须执行此验证！**

**规则：PlantUML序列图箭头标注必须与源代码一致：**
- `上游模块 -> 本模块函数 : 上游模块的调用函数名`
- `本模块函数 -> 下游模块 : 下游模块的被调用函数名`
- `本模块函数A -> 本模块函数B : 形参（若无则不标注）`

**自动验证步骤：**

```bash
# 1. 提取PlantUML中的所有箭头标注
grep -E "^[^:]+ -> [^:]+ :" swdd/{模块名}/img/{模块名}_Dynamic_Behavior.puml > /tmp/arrows.txt

# 2. 对每个"上游模块 -> 本模块函数"，验证冒号后的函数名属于上游模块
# 例如：ABBSM -> GetAngle : ABBSM_vidMainFunction()
# 需要验证：ABBSM_prg.c 中确实调用了 AINCU_enuGetAngleDetRes，且是在 ABBSM_vidMainFunction 中
```

**手动验证清单（必须逐项检查）：**

| 箭头类型 | 示例 | 验证方法 |
|---------|------|---------|
| 上游→本模块 | `AMSG -> GetWorkSta : MSG_vidLinSleepThread()` | grep AMSG目录，确认调用了AINCU_enuGetIsWorkSta |
| 本模块→下游 | `MainFunc -> HRTE : HRTE_vidSetPortHBridge_NSleep()` | grep HRTE目录，确认此函数存在 |
| 本模块内部 | `MainFunc -> InitPwr :` | grep 本模块，确认InitPwr被MainFunc调用 |

**常见错误：**
1. ❌ 错误：`ABBSM -> GetAngle : AINCU_enuGetAngleDetRes()`
   - 原因：标注的是本模块的函数名，而不是上游模块的函数名
   - ✅ 正确：`ABBSM -> GetAngle : ABBSM_vidMainFunction()`

2. ❌ 错误：`MainFunc -> HRTE : SetPort`
   - 原因：使用了缩写而非完整函数名
   - ✅ 正确：`MainFunc -> HRTE : HRTE_vidSetPortHBridge_NSleep()`

3. ❌ 错误（内部函数调用外部模块）：`HasFault -> SRTE : SRTE_enuGetBattLowVolErrSta()`
   - 原因：内部函数（如BBSM_bHasVoltageFault、BBSM_bIsInternalTriggerActive）本身不调用任何外部函数
   - 正确做法：**参数由调用者（MainFunc）获取，然后传给内部函数**
   - ✅ 正确：`MainFunc -> SRTE : SRTE_enuGetBattLowVolErrSta()` → 获取参数
   - ✅ 正确：`MainFunc -> HasFault : enuBattLowVolt` → 传入参数给内部函数

4. ❌ 错误（内部函数调用外部模块）：`IsIntTrg -> AMSG : AMSG_enuGetToutFlgLpcLpc7LinFr01()`
   - 原因：BBSM_bIsInternalTriggerActive只是接收参数检查，不调用AMSG
   - ✅ 正确：`MainFunc -> AMSG : AMSG_enuGetToutFlgLpcLpc7LinFr01()` → MainFunc获取enuTimeoutSts
   - ✅ 正确：`MainFunc -> IsIntTrg : enuTimeoutSts` → MainFunc传给IsIntTrg检查

**验证脚本（自动执行）：**

```bash
#!/bin/bash
# verify_arrow_labels.sh - 验证动态图箭头标签

MODULE=$1
PUML_FILE="swdd/${MODULE}/img/${MODULE}_Dynamic_Behavior.puml"
SRC_DIR="BBS_K311_APP/src/Source/APP"

if [ ! -f "$PUML_FILE" ]; then
    echo "Error: $PUML_FILE not found"
    exit 1
fi

echo "=== 验证动态图箭头标签 ==="
echo ""

# 提取所有箭头
arrows=$(grep -E "^[^:]+ -> [^:]+ : .+" "$PUML_FILE")

# 对每一行箭头进行验证
echo "$arrows" | while read line; do
    # 格式: 上游 -> 本模块 : 调用函数
    caller=$(echo "$line" | cut -d':' -f1 | cut -d'>' -f1 | xargs)
    callee=$(echo "$line" | cut -d':' -f1 | cut -d'>' -f2 | xargs)
    func=$(echo "$line" | cut -d':' -f2- | xargs)

    # 检查箭头标注的函数属于哪一方
    # 如果caller是外部模块，func应该是caller的函数
    # 如果caller是本模块，func应该是callee的函数（下游）

    echo "检查: $line"
    # 这里可以添加更详细的验证逻辑
done
```

**快速验证命令（生成文档后必执行）：**

```bash
# 检查 Mermaid 语法问题
grep -n " flowchart" swdd/{模块名}/*.md          # 检查 flowchart 前多余空格
grep -n "Start((Start))" swdd/{模块名}/*.md     # 检查错误的开始节点语法
grep -n "End((End))" swdd/{模块名}/*.md         # 检查错误的结束节点语法

# 检查节点文本是否超过23字符需要换行（重要！）
# 查找没有换行的长条件表达式（>23字符不带<br/>）
grep -nE '\{[^{}]{23,}\}' swdd/{模块名}/img/*.mmd | grep -v '<br/>'
grep -nE '\[.+[^\\]{23,}\]' swdd/{模块名}/img/*.mmd | grep -v '<br/>'

# 检查独立if是否正确画法（重要！）
# 独立if的Y分支执行完后，需要额外一条线连接到下一个判断节点（因为两个if都会执行）
# 例如：UnauCheck的Y分支执行完后，应该还有一条线连接到ArmedDisarmCheck
# 检查方法：查看是否有判断节点的Y或N分支执行完后没有连接到下一个独立if的入口
# 这个需要人工检查，但可以通过以下命令列出所有Y分支的连接情况辅助判断
grep -n '") Y|"' swdd/{模块名}/img/*.mmd | head -20

# 检查矩形框是否有两条分支（重要！）⚠️
# 正常情况下矩形框应该只有一条出边，如果发现某个矩形框有多条出边，需要检查是否画错了
# 例如：Ainbox --> B 和 Ainbox --> C 表示Ainbox有两条分支，这是错误的
# 验证命令1：检查所有连接到End的节点是否有超过1条出边
for file in swdd/{模块名}/img/*.mmd; do
  echo "=== Checking $file ==="
  # 找出所有以 --> End 结尾的行，提取源节点名称
  grep '\-\-> End' "$file" | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*\-\->.*//' | sort -u | while read node; do
    # 查找该节点的所有出边
    echo "Checking node: $node"
    count=$(grep -c "^    ${node} \-\-> " "$file" 2>/dev/null || echo 0)
    if [ "$count" -gt 1 ]; then
      echo "ERROR: $node has $count outgoing edges (should be 1):"
      grep "^    ${node} \-\-> " "$file"
    fi
  done
done

# 验证命令2：更简单直接 - 检查所有出边数量
# 找出所有连接到End的节点，检查它们是否只有一条出边（指向End）
grep '\-\-> End' swdd/{模块名}/img/*.mmd | sed 's/:[[:space:]]*/ /' | sed 's/[[:space:]]*\-\-> End.*//' | sort -u | while read node; do
  total=$(grep "^    ${node} \-\-> " swdd/{模块名}/img/*.mmd 2>/dev/null | wc -l)
  if [ "$total" -gt 1 ]; then
    echo "ERROR: $node has $total outgoing edges (should be 1):"
    grep "^    ${node} \-\-> " swdd/{模块名}/img/*.mmd
  fi
done

# 验证命令3：检查是否所有出边都只连向一个目标（排除指向End的情况）
# 这个命令会列出所有有两条以上出边的节点
for file in swdd/{模块名}/img/*.mmd; do
  echo "=== Detailed check for $file ==="
  # 提取所有节点名称（第一列）
  grep '^\s.*-->' "$file" | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*\-\->.*//' | sort -u | while read node; do
    # 统计该节点的出边数量
    count=$(grep -c "^    ${node} \-\-> " "$file" 2>/dev/null || echo 0)
    if [ "$count" -gt 1 ]; then
      echo "WARNING: $node has $count outgoing edges:"
      grep "^    ${node} \-\-> " "$file"
    fi
  done
done

# 检查动态图函数调用关系（重要！）⚠️
# 常见错误：把调用者的调用画成被调用者的调用
# 例如：MainFunc调用SRTE获取参数后传给内部函数bbs_func，内部函数bbs_func并不调用SRTE
# 检查方法：
# 1. 先在源码中找到被调用函数的定义，确认它是否调用其他函数
# 2. 检查PlantUML中该函数的调用关系，确认箭头方向是否正确
# 3. 特别关注有参数传递的函数，参数是调用者获取后传入的，不是被调用者内部获取的
grep -n "Func -> InternalFunc :" swdd/{模块名}/*.md | head -20

# 检查内部函数是否错误调用外部模块（重要！）⚠️
# 典型错误：HasFault -> SRTE、BBSM_bIsInternalTriggerActive -> AMSG
# 这是错误的！因为内部函数（如BBSM_bHasVoltageFault、BBSM_bIsInternalTriggerActive）本身不调用任何外部函数
# 参数是由MainFunc获取后传给他的
# 检查PlantUML中是否有 "内部函数 -> 外部模块" 的调用
grep -nE "HasFault -> SRTE|HasFault -> AFAULTM|IsIntTrg -> AMSG|IsIntTrg -> SRTE" swdd/{模块名}/img/*.puml
# 如果找到上述错误调用，检查源码确认内部函数是否真的调用了外部模块
# 正确做法应该是：MainFunc -> SRTE/AFAULTM/AMSG 获取参数，然后 MainFunc -> 内部函数 传入参数

# 检查 PlantUML 源码问题（必须使用源码，不能用PNG）
grep -n "!\[.*Dynamic.*\](img/.*.png)" swdd/{模块名}/*.md  # 检查是否错误使用PNG
grep -n "```plantuml" swdd/{模块名}/*.md         # 确认 PlantUML 源码存在

# 检查静态图源码问题
grep -n "!\[.*Static.*\](img/.*.png)" swdd/{模块名}/*.md   # 检查是否错误使用PNG
grep -n "```mermaid" swdd/{模块名}/*.md        # 确认 Mermaid 源码存在

# 检查箭头标签（确保不是自然语言描述）
grep -n "calibration parameter" swdd/{模块名}/*.md  # 检查是否有错误的标签

# 检查 img 目录文件完整性
ls -la swdd/{模块名}/img/*.png | wc -l  # 统计PNG文件数量
ls -la swdd/{模块名}/img/*.mmd | wc -l  # 统计Mermaid文件数量
ls -la swdd/{模块名}/img/*.puml | wc -l  # 统计PlantUML文件数量

# 检查MD文档结构是否符合转换要求
grep -n "Figure.*Flowchart" swdd/{模块名}/*.md        # 确认函数流程图标题格式正确
grep -n "2.4.1\|Static Diagram" swdd/{模块名}/*.md   # 确认静态图位置正确
grep -n "2.6 Dynamic Behavior" swdd/{模块名}/*.md     # 确认动态图位置正确
grep -r $'\r' swdd/{模块名}/*.md                      # 检查是否有CRLF行尾（不应有）
file swdd/{模块名}/*.md                                 # 确认文件为ASCII/UTF-8 text

# 检查表格格式（确保分隔行格式正确）
grep -n "^|.*|$" swdd/{模块名}/*.md | grep -v "|--"   # 检查是否有无效的表格行

# 检查动态图是否有生命周期（activate/deactivate）
grep -c "activate" swdd/{模块名}/*.md                  # 确认有activate标记
grep -c "deactivate" swdd/{模块名}/*.md                # 确认有deactivate标记
```

---

### MD文档更新流程（重要！）

每次更新MD文档后，必须按以下顺序执行：

**1. 更新MD文档**
- 直接编辑MD文件中的mermaid/plantuml代码块

**2. 更新mmd/puml源文件（从MD文档提取）**
- 从MD文档的 ` ```mermaid ` 代码块提取内容，保存为 .mmd 文件
- 从MD文档的 ` ```plantuml ` 代码块提取内容，保存为 .puml 文件

```bash
# 切换到img目录
cd swdd/{模块名}/img

# 从MD文档提取并保存（手动操作）
# 静态图：复制MD中2.4.1章节的mermaid代码 → 保存为 {模块名}_Static_Diagram.mmd
# 动态图：复制MD中2.6章节的plantuml代码 → 保存为 {模块名}_Dynamic_Behavior.puml
# 函数流程图：复制各函数章节的mermaid代码 → 保存为 {模块名}_{函数名}_Flowchart.mmd
```

**3. 重新生成PNG（从mmd/puml渲染）**

```bash
# Mermaid PNG（静态图、函数流程图）
PUPPETEER_EXECUTABLE_PATH=/path/to/chrome-headless-shell \
npx @mermaid-js/mermaid-cli -i {模块名}_Static_Diagram.mmd -o {模块名}_Static_Diagram.png

# PlantUML PNG（动态图）
# ⚠️ 注意：PlantUML直接生成的PNG有大小限制（最大约4000px）
# 必须使用SVG中间格式 + cairosvg转换生成超大PNG，再填充白色背景
plantuml -tsvg -o ./ {模块名}_Dynamic_Behavior.puml
pip3 install cairosvg -q 2>/dev/null || true
python3 -c "
import cairosvg
cairosvg.svg2png(url='{模块名}_Dynamic_Behavior.svg', write_to='{模块名}_Dynamic_Behavior.png')
"
# 填充白色背景（cairosvg转换的PNG可能有透明背景）
python3 -c "
from PIL import Image
img = Image.open('{模块名}_Dynamic_Behavior.png')
if img.mode == 'RGBA':
    background = Image.new('RGB', img.size, (255, 255, 255))
    background.paste(img, mask=img.split()[3])
    background.save('{模块名}_Dynamic_Behavior.png')
    print('Added white background')
"

# 批量更新函数流程图
for func in $(ls *Flowchart.mmd 2>/dev/null); do
    PUPPETEER_EXECUTABLE_PATH=/path/to/chrome-headless-shell \
    npx @mermaid-js/mermaid-cli -i "$func" -o "${func%.mmd}.png"
done
```

**4. 更新Word文档**

```bash
# 切换到scripts目录
cd swdd/scripts

# 转换MD到Word（使用最新的PNG）
python3 md_to_word.py ../{模块名}/BBS_K311_APP_{模块名}_Software_Detailed_Design_Document_EN.md
```

**更新原则：**
- **MD文档是源文件** - 所有图表代码的最新版本必须在MD中
- **mmd/puml是衍生文件** - 从MD文档提取并保存
- **PNG是渲染结果** - 从mmd/puml重新生成
- **Word是最终输出** - 从MD转换，使用最新的PNG

### PNG文件验证流程（重要！）

**⚠️ 动态图PNG必须使用SVG + cairosvg转换生成**
- PlantUML直接生成的PNG有大小限制（最大约4000px）
- 必须使用 `-tsvg` 生成SVG，再用 cairosvg 转换为PNG
- cairosvg转换时会自动处理背景

**如果PNG图片渲染异常，按以下步骤排查和修复：**

1. **检查PNG文件是否存在且有效**
   ```bash
   file swdd/{模块名}/img/{DiagramName}.png
   # 正常输出: PNG image data, xxx x xxx
   # 异常输出: empty 或 cannot open
   ```

2. **检查PNG文件大小**
   ```bash
   ls -la swdd/{模块名}/img/{DiagramName}.png
   # 正常PNG通常 > 1KB
   # 异常PNG可能 = 0 或很小
   ```

3. **如果PNG异常，检查对应的源文件**
   - Mermaid: `swdd/{模块名}/img/{DiagramName}.mmd`
   - PlantUML: `swdd/{模块名}/img/{DiagramName}.puml`

4. **常见的Mermaid语法错误及修复：**
   | 错误 | 原因 | 修复方法 |
   |------|------|---------|
   | `Parse error on line X` | 语法错误 | 检查该行的中文字符、特殊字符 |
   | `Expecting 'TEXT'` | 节点文本包含非法字符 | 简化文本，移除 `()` `{}` `[]` 等 |
   | `Expecting 'PIPE'` | 判断框内有多行条件 | 拆分为多个独立判断 |
   | `flowchart TD` 前有空格 | 格式错误 | 确保 `flowchart` 在行首 |
   | `Start((Start))` 错误 | 应为 `Start([Start])` | 使用正确的括号类型 |

5. **重新生成PNG**
   ```bash
   # Mermaid
   PUPPETEER_EXECUTABLE_PATH=/path/to/chrome-headless-shell \
   npx @mermaid-js/mermaid-cli -i {DiagramName}.mmd -o {DiagramName}.png

   # PlantUML
   plantuml -o ./ {DiagramName}.puml
   ```

6. **如果源文件损坏，从MD文档中提取修复**
   - 从MD文档中的 ` ```mermaid ` 或 ` ```plantuml ` 代码块复制到 .mmd / .puml 文件
   - 修复语法错误
   - 重新生成PNG
   - 确保MD文档中的源码与修复后的源文件一致

### MD转Word文档时的图表识别规则（重要！）

使用 `swdd/scripts/md_to_word.py` 将MD文档转换为Word时，脚本通过以下规则识别图表：

**1. 函数流程图（Mermaid）**
- 匹配模式：`**Figure {编号}: {函数名} Flowchart**`
- PNG文件名：`{模块名}_{函数名}_Flowchart.png`
- 脚本在代码块**之后**查找Figure引用

**2. 静态图（Mermaid）**
- 识别方式：Mermaid代码块之后出现 "2.4.2" 或 "Component Overview Table"
- PNG文件名：`{模块名}_Static_Diagram.png`
- 脚本在代码块**之后**向前查找

**3. 动态图（PlantUML）**
- 识别方式：代码块之前存在 "### 2.6 Dynamic Behavior"
- PNG文件名：`{模块名}_Dynamic_Behavior.png`
- 脚本在代码块**之前**全局搜索

**编写SWDD时的注意事项：**
- **函数流程图**：必须在Mermaid代码块后紧跟或附近有 `**Figure X-Y: 函数名 Flowchart**` 格式的标题
- **静态图**：必须在2.4.1节（Mermaid代码块）之后、2.4.2节（Component Overview Table）之前
- **动态图**：必须在 "### 2.6 Dynamic Behavior" 标题之后的PlantUML代码块中

---

## 参考资源

详细编写规范请参考：
- [references/SWDD_Mandatory_Requirements.md](references/SWDD_Mandatory_Requirements.md) - **强制规范**
- [references/guidelines.md](references/guidelines.md) - 章节编写详细要求

---

## img 目录文件规范（必须遵守）

每个模块的 `img/` 目录下必须包含以下文件（.mmd 源码 + .png 图片）：

**1. 模块级图表：**
| 文件名 | 说明 |
|--------|------|
| `{Module}_Static_Diagram.mmd` + `.png` | 静态图 |
| `{Module}_Dynamic_Behavior.puml` + `.png` | 动态行为时序图 |

**2. 外部函数流程图（2.7 章节）：**
每个外部函数必须有独立的流程图文件：
- `{Module}_{ExternalFuncName}_Flowchart.mmd` + `.png`
- 例如：`ABBSM_vidMainFunction_Flowchart.mmd` + `.png`

**3. 内部函数流程图（2.8 章节）：**
每个内部函数必须有独立的流程图文件：
- `{Module}_{InternalFuncName}_Flowchart.mmd` + `.png`
- 例如：`AINCU_bInclOutRange_Flowchart.mmd` + `.png`

**生成方式：**
- Mermaid (.mmd → .png):
  ```bash
  npx @mermaid-js/mermaid-cli -i input.mmd -o output.png
  ```
  或使用环境变量指定 Chrome 路径：
  ```bash
  PUPPETEER_EXECUTABLE_PATH=/path/to/chrome-headless-shell npx @mermaid-js/mermaid-cli -i input.mmd -o output.png
  ```
- PlantUML (.puml → .png):
  ```bash
  plantuml -o ./ filename.puml
  ```

**重要提醒：**
- 生成 SWDD 时，必须同步生成所有 img 目录文件
- 不得遗漏任何外部函数或内部函数的流程图
- img 目录文件应与 SWDD 文档同步更新
- 转换Word前必须验证所有PNG文件存在且有效

---

## MD转Word工具

### 使用方法

```bash
# 切换到scripts目录
cd swdd/scripts

# 运行转换脚本（输出文件名自动从输入生成）
python3 md_to_word.py <输入MD文件> [可选：img目录]

# 示例
# 示例（AINCU 模块，APP 项目）：
python3 md_to_word.py ../AINCU/BBS_K311_APP_AINCU_Software_Detailed_Design_Document_EN.md
# 自动生成: ../AINCU/BBS_K311_APP_AINCU_Software_Detailed_Design_Document_EN.docx
# 通用模板：python3 md_to_word.py ../{模块名}/{文档前缀}_{模块名}_Software_Detailed_Design_Document_EN.md
```

### 转换规则

- Mermaid代码块 → 替换为对应的PNG图片
- PlantUML代码块 → 替换为对应的PNG图片
- 静态图：识别为 `{模块名}_Static_Diagram.png`
- 动态图：识别为 `{模块名}_Dynamic_Behavior.png`
- 函数流程图：识别为 `{模块名}_{函数名}_Flowchart.png`
- 表格：自动解析MD表格并转换为Word表格，会自动过滤分隔行（`---|---|`）和空行

### 表格格式要求

MD文档中的表格必须符合标准Markdown格式：
- 使用 `|` 分隔列
- 表格前后不能有空行（会变成空表格行）
- 确保没有多余的空行混入表格

### 分隔行格式（重要！）

分隔行用于分隔表头和数据行，Word转换时会自动过滤。

**标准分隔行格式：**
```
|---|---|
|---|---|        # 简洁格式
|:--|           # 左对齐
|:---|          # 居中
|---:|          # 右对齐
|-------------| # 多列
```

**分隔行检测规则：**
- 分隔行每个单元格只能包含 `-`（横线）、`:`（对齐标记）、空格
- 不能包含任何字母、数字或其他字符
- 示例：
  - `|-----|` ✓ 正确
  - `|:----:|` ✓ 正确
  - `|---abc---|` ✗ 错误（包含字母）

### 表格续行格式示例（重要！）

**正确格式：**
```
| Enum Name | Member | Value | Description |
|-----------|--------|-------|-------------|
| **EnumName** | ENUM_A | 0 | Description |
| | ENUM_B | 1 | Description |
| | ENUM_C | 2 | Description |
```

**错误格式（会导致空列）：**
```
| Enum Name | Member | Value | Description |
|-----------|--------|-------|-------------|
| **EnumName** | ENUM_A | 0 | Description |
| ENUM_B | 1 | Description |  # 缺少第一列的 |
| ENUM_C | 2 | Description |  # 缺少第一列的 |
```

**续行规则：**
- 第一行：枚举名/结构体名在第一列
- 续行：**必须以 `|` 开头**（`|` 后面紧跟空格或其他内容）
- 如果续行第一个单元格为空，必须写成 `| |` 而不是只有 `|`
- 确保每行列数一致

---

## 输出文件结构

```
./swdd/{模块名}/
├── img/
│   ├── {模块名}_Static_Diagram.mmd
│   ├── {模块名}_Static_Diagram.png
│   ├── {模块名}_Dynamic_Behavior.puml
│   ├── {模块名}_Dynamic_Behavior.png
│   ├── {模块名}_{ExternalFunc}_Flowchart.mmd
│   ├── {模块名}_{ExternalFunc}_Flowchart.png
│   ├── {模块名}_{InternalFunc}_Flowchart.mmd
│   └── {模块名}_{InternalFunc}_Flowchart.png
├── {项目前缀}_{模块名}_Software_Detailed_Design_Document_EN.md
└── {项目前缀}_{模块名}_Software_Detailed_Design_Document_EN.docx
```

## 工具集成

本 skill 自带两个通用脚本，位于 `~/.claude/skills/swdd-generator/scripts/`，可在任意项目中使用。

### 自带脚本

| 脚本 | 用途 | 命令 |
|------|------|------|
| `md_to_docx.py` | MD → DOCX 转换（自动多级标题编号、嵌入 PNG 图片） | `python ~/.claude/skills/swdd-generator/scripts/md_to_docx.py --swdd-root ./swdd [模块名]` |
| `extract_diagrams.py` | 从 MD 提取 mermaid/plantuml 并渲染 PNG | `python ~/.claude/skills/swdd-generator/scripts/extract_diagrams.py --swdd-root ./swdd --module 模块名` |

### 外部工具依赖

详细安装指南见 [SETUP.md](SETUP.md)。

| 工具 | 用途 | 环境变量 |
|------|------|----------|
| **cscope** | **C 函数定义/引用/调用关系分析（查定义、查引用、caller/callee）** | **-**（需先在项目根目录执行 `cscope -bqk` 构建数据库） |
| Java 11+ | 运行 PlantUML | - |
| PlantUML jar | 渲染 .puml → .png | `PLANTUML_JAR` |
| Graphviz (dot) | PlantUML 渲染非序列图依赖 | `GRAPHVIZ_DOT`（可选） |
| Node.js 18+ / npm | 运行 mermaid-cli | - |
| @mermaid-js/mermaid-cli | 渲染 .mmd → .png | `PUPPETEER_EXECUTABLE_PATH`（可选） |
| Python 3.9+ | 运行脚本 | - |
| python-docx, Pillow | Python 包 | `pip install -r ~/.claude/skills/swdd-generator/requirements.txt` |

### SWDD 生成完整工作流

1. **生成 MD**：Claude 根据源码分析生成 SWDD markdown 文件
2. **提取并渲染图表**：
   ```bash
   python ~/.claude/skills/swdd-generator/scripts/extract_diagrams.py --swdd-root ./swdd --module 模块名
   ```
3. **生成 DOCX**：
   ```bash
   python ~/.claude/skills/swdd-generator/scripts/md_to_docx.py --swdd-root ./swdd 模块名
   ```

### 新项目启动检查清单

在新项目/新电脑使用前，验证以下环境：
```bash
cscope --version                       # cscope（必须）
java -version                          # Java 11+
java -jar $PLANTUML_JAR -version       # PlantUML
dot -V                                 # Graphviz
npx @mermaid-js/mermaid-cli -V         # Mermaid CLI
python -c "import docx; import PIL; print('OK')"  # Python 包
```

**首次使用前必做 — 构建 cscope 数据库**（在项目根目录执行）：
```bash
# Linux / macOS / Git Bash / WSL / MSYS2
find BBS_K311_APP/src BBS_K311_APP/MCAL -type f \( -name "*.c" -o -name "*.h" \) > cscope.files
cscope -bqk
```
Windows PowerShell 版本及完整说明参见 [references/cscope_usage.md](references/cscope_usage.md)。源码变更后必须重建。

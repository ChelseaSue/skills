---
name: std-compliance
description: >
  标准/法规符合性检查：按“标准包”逐条核对汽车电子 ECU 软件的设计与实现是否符合行业标准，输出
  协议符合性矩阵（xlsx）与检查报告（md）。首个标准包 lin-can-comm 覆盖 LIN/CAN 通信与诊断：ISO 17987-2/-3
  （LIN 传输层/协议）、ISO 14229-1/-2/-3/-7（UDS 应用层/会话层/UDSonCAN/UDSonLIN）、ISO 15765-2（DoCAN）、
  ISO 11898-1（CAN 数据链路层）。检查方法四类：配置核对（LDF/ARXML 参数，脚本规则自动判定）、设计评审、
  宿主机行为测试（Ceedling 链接真实协议栈，总线驱动层打桩，按节拍判定）、目标机/HIL（实时与物理层，判 NA 不判符合）。
  无论用户说“检查是否符合 LIN/CAN/UDS 标准”“协议符合性/一致性检查”“ISO 17987/14229/15765/11898 检查”
  “诊断协议合规”“标准条款核对”“法规/标准检查”，还是要“新增一个标准包（如 ISO 21434、UN R155/R156）”或
  “从标准 PDF 建条款清单”，都应使用本 skill。区分：swit 是 SWE.5 集成测试（对标 SAD），swuv 是 SWE.4 单元验证
  （对标 SWDD），本 skill 对标的是外部标准条款，独立出报告，不改动 swit/swuv 的交付物。
---

# 标准符合性检查（标准包 → 适用性 → 检查 → 矩阵/报告）

## 定位

| | 对标 | 交付物 |
|---|---|---|
| swuv（SWE.4） | 详细设计 SWDD | 单元测试用例/报告/追溯 |
| swit（SWE.5） | 架构设计 SAD | 集成测试策略/用例/记录/报告 |
| **本 skill** | **外部标准条款**（ISO/法规） | 符合性矩阵 xlsx + 检查报告 md |

标准条款横跨三个阶段：设计/配置阶段即可核对的参数、需要把协议栈串起来才能验证的行为、必须真实总线才能
测的实时与物理层。本 skill 一次覆盖前两类，第三类列入“转 SWE.6/HIL/一致性测试”清单，不在宿主机上下结论。

## 目录

```
packs/<pack>/pack.json        标准清单（编号、版次、范围、适用条件、原文文件名）
packs/<pack>/checklist.json   检查项（条款号 + 自述要点 + 适用性 + 方法 + 参数 + 原文页码与核对状态）
packs/<pack>/rules/*.py       config 类检查项的自动规则（RULES = {检查项ID: fn(ctx)}）
packs/<pack>/host/            宿主机测试辅助（总线桩等），生成工程时复制到 support/
scripts/stdc.py               统一入口；core.py 模型；parsers/ldf.py、arxml.py；host/、report/、verify.py
references/                   framework / pack-authoring / lin-can-applicability / report-format
```

## 工作流

```bash
S=~/.claude/skills/std-compliance/scripts; P=<项目>/std_project.json
python $S/stdc.py init --project $P            # 生成配置骨架，按项目填写（见下）
python $S/stdc.py static --project $P          # 读 LDF/ARXML：支持的 SID、config 规则结论
python $S/stdc.py applicable --project $P      # 适用性清单（不适用必须有理由）
python $S/stdc.py host gen --project $P        # Ceedling 工程 + 每个 host-test 检查项一个测试骨架
python $S/stdc.py host probe --project $P      # 逐文件语法探测，补 support/ 替身头直到无错；[drift] 列出与编译副本不一致的同名文件
#   Claude：按骨架注释写测试；每个测试函数上方保留 /* STD: <检查项ID> */
python $S/stdc.py run --project $P --test <测试文件名>   # 单文件试跑，读链接错误
python $S/stdc.py host stubs --project $P      # 从链接日志自动生成中性桩（标注项目中有真实定义的符号，需人工确认）
#   链接真实 RTE/胶合层的测试：单独运行后 host stubs --stubs-out std_autostubs_<名>.c 生成专属桩文件
python $S/stdc.py run --project $P             # 执行全部 Ceedling 测试，按标记归集结论
#   Claude：design 类检查项读 SAD/配置后，把评审结论写进 std_project.json 的 reviews（附证据、评审人、日期）
#   Claude：每条测试/规则判出的“不符合”写 notes（根因模块 + 整改）；不针对条款的观察写 findings（报告第 6 章）
python $S/stdc.py report --project $P          # xlsx 矩阵 + md 报告（<ws>/report/）
python $S/stdc.py verify --project $P          # 发布门禁
```

### 第 0 步：项目配置 `std_project.json`
- `node`：总线（LIN/CAN）、LIN 角色（commander/responder，兼容 master/slave）、UDS 角色（client/server）、
  功能标签（diag/tp/sleep/node-config/functional-addressing/reprogramming/can-fd…）、`ldf_name`（本节点在 LDF 中的名字）、
  `supported_sids`（`auto` = 从 Dcm ARXML 读取）。这些决定哪些条款适用——**问清再填，不要猜**。
- `inputs`：LDF/DBC/ARXML 文件清单（只列本产品的文件；同目录常混有其他项目的配置）、SAD、源码根、标准 PDF 目录。
- `expected`：需求层面的期望值（如诊断 NAD），供规则做“设计与需求一致”的核对。
- `host`：参与编译的协议栈与回调源码、include、替身目录、宏。
- 示例：`assets/std_project.example.json`（某 LIN 冷暖箱项目，仅示例，不得照抄取值）。

### 适用性
条款同时受标准级 `applies_to` 与检查项级 `applicability` 约束；`sid` 标注的服务类条款只对支持该服务的节点适用。
项目特殊情况用 `applicability_overrides` 声明（必须写理由，报告中原样呈现）。
OEM 规范明确偏离标准时（如额外的功能 NAD）按 OEM 处理，作为偏差登记在这里；**拿不到 OEM 规范时按标准判**，
并在 `notes` 中注明“若 OEM 规范另有规定可登记偏差”。

### 结论规则
| 方法 | 结论来源 |
|---|---|
| config | `rules/` 自动规则：符合 / 不符合 / 未检查（输入缺失） |
| host-test | 标记到该检查项的测试全部通过 → 符合；任一失败 → 不符合；忽略/无测试 → 未检查 |
| design | `reviews` 中的评审记录（证据 + 评审人 + 日期）；没有记录即未检查 |
| target | 固定“转SWE.6/HIL”，**不得判符合** |

`notes`（检查项 ID → 文字）把根因、整改建议、待确认事项附加到证据后面，不改变结论。每条“不符合”都应有 note：
测试失败消息只说明“现象”，读报告的人还需要“原因在哪个模块、怎么改”。
宿主机测试中可保留一个无标记的“对照测试”，用 `TEST_MESSAGE` 记录栈对各请求的实际应答字节，
既证明测试通路正常（排除环境原因），又给 note 提供原始证据。

## 硬性规则
- **不复制标准原文**。检查项只写条款号、标题和自述要点；`extract` 产出的原文候选只放项目工作区（自带 `.gitignore`），不进 skill、不进报告。
- **结论只来自证据**：规则输出、测试结果、评审记录。不凭读代码判“不符合”；测试失败要能复现，并先按
  `references/host-testing.md` 排除环境原因（如工具函数被自动桩替换导致的假失败）。
- **宿主机不判实时**：时序以 MainFunction 调用次数（节拍）判定；真实时间、位时序、物理层一律 target。
- **不伪造**：未检查就是未检查，计入符合率分母；不适用与 target 不计入分母。
- **只读交互**：读 SAD、源码、配置；不修改 swit/swuv 的工作区和交付物，也不修改被测源码（发现问题写进报告）。
- **通用性**：项目差异进 `std_project.json`；标准差异进标准包；脚本里不写任何项目或标准的具体取值。

## 新增或更新标准包
读 `references/pack-authoring.md`：放入解密的标准 PDF → `stdc.py extract` → 按条款候选写检查项（自述）→
标 `source.page` 与 `verified` → 为 config 类写规则 → 用 evals 验证。标准换版时按新版重做 extract，逐条复核差异。

## 参考资料
| 文件 | 内容 |
|---|---|
| `references/framework.md` | 检查项 schema、结论取值、规则 API、Ctx 可用输入、标记约定 |
| `references/pack-authoring.md` | 从 PDF 建清单的流程、版权规则、条款筛选原则、自检 |
| `references/lin-can-applicability.md` | LIN responder / CAN 节点 / UDS server 的适用子集、常见坑、哪些条款是 target |
| `references/report-format.md` | 矩阵列定义、报告章节、计数口径 |
| `references/host-testing.md` | 宿主机集成搭建循环、LIN 总线仿真用法、**下“不符合”结论前必须排除的环境坑** |

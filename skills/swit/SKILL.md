---
name: swit
description: >
  汽车电子软件集成测试（SWE.5 / Software Integration and Integration Test）：输入**软件架构设计文档（SAD，
  .docx/.md，含 CodeBeamer 导出）+ 组件源码**，按公司模板输出 SWE.5 全套工作产品——测试策略（AU-QR-R&D-050，
  含集成对象）、测试指南（AU-QW-R&D-56）、测试用例（052）、追溯矩阵（022）、测试记录（236）、回归测试记录（237）、
  测试报告（238）。自动判定场景：项目首次测试或 SAD 有变更时输出全套（增量更新，用例 ID SWIT-XXXXX 稳定不复用）；
  SAD 未变时只输出记录+报告；用户要求回归时以上一轮测试记录为输入，只输出 237+238、不输出 236。
  执行方案：宿主机 Ceedling+Unity+CMock 真实链接组件、只在边界打桩，gcc -fcallgraph-info×gcov 算函数/调用覆盖率；
  目标机构建产物（链接 map）静态核算 ROM/RAM；需开发板的执行时间/CPU 负载/中断延迟转 SWE.6（判 NA，不判 Pass）。
  无论用户说"做集成测试""SWE.5""软件集成测试用例/记录/报告""集成测试追溯矩阵""集成测试策略/指南""回归测试"
  "测组件接口/时序/状态机""调用覆盖率""software integration test from architecture"，还是问"做集成测试还缺什么输入"，
  都应使用本 skill。区分：sad-generator 产 SAD（本 skill 的输入）；swuv 是 SWE.4 单元验证（对标 SWDD）。
---

# 软件集成测试 SWE.5（SAD + 源码 → 策略/指南/用例/追溯/记录/报告）

## V 模型定位

```
SWE.2 软件架构设计 SAD  ←→  SWE.5 软件集成测试   ← 本 skill（对标 SAD，不对标 SRS/SWDD）
SWE.3 详细设计 SWDD     ←→  SWE.4 单元验证（swuv）
```
被测对象是**组件之间的接口与交互**：接口参数/返回值跨组件传递是否与架构一致、时序图/状态机定义的动态行为集成后是否按图发生、资源与时序约束是否满足。需求 ID 只是 SAD 带下来的继承属性。

## 模式（先跑 `swit.py status`，不要凭感觉选）

| 模式 | 触发 | 必需输入 | 输出 |
|---|---|---|---|
| `full` | 工作区无基线（项目首次） | SAD、源码、`swit_project.json` | 050 策略（含集成对象）、056 指南、052 用例、022 追溯、236 记录、238 报告 |
| `sad-change` | SAD 锚点内容与基线不同（ingest 后 diff） | 同上 + 基线 | 增量更新 050/056/052/022（保留 ID；新增续号；修改标 stale 需复核；删除标 Obsolete）+ 236 + 238，各文档修订记录自动写变更摘要 |
| `execute` | SAD 未变（或仅格式变化） | 源码 + 用例库 | 236 + 238 |
| `regression` | **用户明确要求回归** | **上一轮 236/237 xlsx** + 可选代码变更范围/缺陷清单 | 237 + 238，**不输出 236**；检测到 SAD 锚点变化时提示改走 sad-change |

不单独输出 test objects 文档——集成对象（组件/接口/动态行为/性能/资源四类清单）写进 050 策略的「集成对象」章节。

## 第 0 步 — 输入确认（缺什么就停下来问，不静默降级）

1. **SAD**：`.docx`（CodeBeamer 导出或 Word 编写）或 sad-generator 的 `.md`；`.doc` 自动转换。没有 SAD → 用 AskUserQuestion：先跑 sad-generator（推荐）或停止。不得从源码反推架构锚点冒充 SAD。
2. **项目配置** `swit_project.json`（`swit.py init` 生成骨架；完整示例 `assets/examples/bbs_p519_v436.swit_project.json`）：项目名/版本/作者、SAD 路径、模板目录、组件↔源码目录、include、目标机 map、环境差异说明、KPI。
3. **模板目录**：按文档编号通配定位（`AU-QR-R&D-052*` 等），同目录多版本取最高版本；`.doc/.xls` 经 Word/WPS COM 或 LibreOffice 自动转换。
4. **回归**：必须拿到上一轮测试记录 xlsx；可选 `--svn r1:r2` / `--git a..b` / `--changed-files` 与缺陷清单。
5. **语言**：`content_language` en / zh / bilingual，按公司实例惯例（BBS 实例为英文）。

## 工作流

```bash
S=~/.claude/skills/swit/scripts; P=<项目>/swit/swit_project.json
python $S/swit.py status  --project $P            # 判定模式与应出交付物
python $S/swit.py ingest  --project $P            # SAD -> ws/sad/arch_model.json（+ 与基线 diff）
python $S/swit.py design  --project $P            # 锚点 -> 用例注册表 ws/cases/cases.json
#   Claude：写 ws/cases/case_text.json -> python $S/cases/apply_text.py --project $P
python $S/swit.py docs    --project $P            # 起草 050/056 内容 JSON（Claude 复核措辞、补项目理由）
python $S/swit.py host    --project $P yml        # 以及 standins / boundary / probe / skeleton
#   Claude：probe 无错 -> 写测试（每个测试函数上方 /* SWIT: SWIT-xxxxx */）
python $S/swit.py run     --project $P --round 1 --ceedling
python $S/swit.py build   --project $P --mode full --round 1
python $S/swit.py check   --project $P --mode full --round 1
```
回归：`regress --previous <上一轮记录.xlsx> --round R1 [--svn ...]` → `run --round R1 --selection --ceedling` → `build --mode regression --rounds 1 R1` → `check --mode regression --rounds 1 R1`。

### 1. ingest（SAD 解析）
`--summary` 看五类锚点计数与告警。规则按**双语章节标题**匹配（不按章节号），默认规则 `assets/sad_profiles/aspice_sad.json`，项目差异放 `sad.extra_anchors` / `sad.profile_overrides`（BBS 的 BSW、SW Design Limitations、Watchdog、Memory 即为示例）。
- 架构 ID 原样取自 SAD；没有 ID 的条目报 `NO-ID`，**绝不编造**。
- RTE/胶水头里的 `#define 别名 真名` 自动解析，否则跨组件调用会被误判为外部调用。
- **图优先读源码**：PlantUML/Mermaid 源码直接解析；只有图片时（`IMAGE-ONLY`）由 Claude 读 `ws/sad/images/*.png` 与 `diagram_hints`（Visio 形状文字）转写到 `ws/sad/arch_supplement.json`（格式见 assets），`verified:false` 直到人工确认；并建议上游 SAD 附带图源码。
详见 `references/sad-ingest.md`。

### 2. design（用例派生）+ 用例文本
每接口 ≥1 接口测试；每条时序/模式 1 条、每条状态转移 1 条功能测试；资源/性能按处置规则：宿主机节拍用例 / 目标机静态核算 / 集成检查 / 转 SWE.6。
脚本给的是骨架；**具体输入数值、观察点、期望值是 Claude 的工作**：从 SAD 约束表与源码常量取真实数字，等价类与边界写进步骤，`design_method` 只写方法名。`apply_text.py --list-pending` 列出 draft/stale。草稿用例不进交付物（`build` 拒绝，`--allow-drafts` 只出 `_DRAFT` 版式预览）。

### 3. host（宿主机集成环境）
`yml` 生成 project.yml（真实组件进 `:source`）；`standins` 为范围外组件生成**同名替身头**（只含 SAD 原型，support/ 在包含路径最前，遮蔽真实头，由 CMock 打桩）；`probe` 逐文件 `gcc -fsyntax-only` 找缺头/缺类型——循环到无错；`boundary` 列出范围外调用及 SAD 签名；`skeleton` 生成带标记的占位测试。
判据是"使用方拿到的 == 提供方给出的"，不在测试里重算转换公式之外的东西；数值期望取自 SAD/配置。详见 `references/host-integration.md`。

### 4. run（执行与采集）
`check_resources.py` 用被测版本的目标机 map 核算各组件 ROM/RAM 对比 SAD 预算；`collect.py` 按标记把测试结果归到用例（全部测试通过才算通过；TEST_IGNORE/无测试 = 未执行），算函数覆盖、跨组件调用覆盖，列出边界调用与**SAD 未定义的公开函数**（架构漂移）。

### 5. build / check
`build` 按模式出交付物：xlsx 克隆模板（按表头文字定位列、下拉值取模板数据验证）、docx 按标题替换章节正文并复用模板表格；活文档（050/056/052/022）在上一版上更新并追加修订记录。`check` 是发布门禁：草稿、【TBD】/人工填写残留、锚点无用例、NA 误用、SWE.6 用例判 Pass、回归轮输出了 236 等都会 FAIL。full/sad-change 正式构建成功后自动冻结基线。

## 硬性规则

- **ID**：架构锚点 ID 只取自 SAD；用例 ID 固定 `SWIT-` + 5 位数字，由注册表分配，永不复用。
- **不伪造结果**：未执行就是"未执行"，不填 0/100%；执行率/通过率分母如实。
- **转 SWE.6 的用例判「用例不适用NA」**并写依据与 SWE.6 引用，不计入执行率/通过率分母，022 中视为已追溯；**绝不判 Pass**。
- **缺陷只由失败的测试或可复现证据确认**，不凭读代码下结论（读代码时注意：过滤注释行的命令会把以 `*` 开头的指针赋值行一起删掉——本 skill 开发时就因此误判过两次"缺陷"，测试一跑即被推翻）。
- 宿主机墙钟时间不作判据：时序以调度节拍计数判定；执行时间/CPU 负载/中断延迟转 SWE.6。
- ROM/RAM 核算必须用**被测软件版本**的目标机构建 map（Debug 与 Release 差异大；map 比源码旧会告警）。
- 人工决策项（组织、进度、样件阶段、ASIL 理由、235 集成记录结论）写【TBD】交给用户，不替人决定。
- 通用性：任何只对某个项目成立的内容进 `swit_project.json` 或 profile，不写进脚本。

## 常见坑（摘要，详见 references）

- MinGW 自带 `adc.h`（ADSI）在大小写不敏感的 Windows 上与 MCAL `Adc.h` 撞名 → 报 `CLSID/GUID` 未知类型：support/ 放 `Adc.h` 替身。
- LIB/驱动头直接 include MCAL/寄存器头（如 `LBTY_int.h`→`Tspc_Port_Ip.h`）：替身只给类型，并记为架构发现。
- 只有头文件的宏组件（如 HSYS/HMEM）在 map 中没有目标文件，按 0 字节计，不是失败。
- 模板数据行的合并单元格可能吞掉一列（238 第 4 节 F:G）：构建器会拆分跨越多个表头列的合并。
- SAD 签名笔误（`Void`、`HSYS_ vidX`）由替身生成器自动修正，修不了的注释掉并列为 SAD 发现。
- 状态转移名来自 `TRANS_A_TO_B` 标签时按首个 `_TO_` 切分，名字可能与图中写法略不同，写用例文本时以图为准。

## 参考资料（按需读）

| 文件 | 内容 |
|---|---|
| `references/sad-ingest.md` | SAD 格式/规则 profile、CodeBeamer 条目结构、读图转写流程、图源码约定 |
| `references/host-integration.md` | Ceedling 集成工程、替身头、标记注释、probe 循环、覆盖率算法、坑 |
| `references/deliverables.md` | 七份交付物的数据来源、计数口径、模板定位、docx 内容 JSON 格式 |
| `references/regression.md` | 回归选择规则、输入记录格式、轮次命名 |
| `references/review-checklist.md` | 发布前自检项与过程规范对应 |
| `assets/` | 配置默认值/骨架/BBS 示例、case_text / arch_supplement / defects 示例、host 头 |

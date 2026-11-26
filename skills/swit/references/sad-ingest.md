# SAD 解析（scripts/sad/）

## 流程

`extract.py`（docx/md → `sad_ir.json`：标题/段落/表格/代码块/图片顺序块）→ `model.py`（IR + profile 规则 → `arch_model.json`）→ `diff.py`（与基线比对）。

## 两种条目识别方式（profile `item_detection.mode`，默认 auto）

| 方式 | 适用 | 规则 |
|---|---|---|
| `id_table` | CodeBeamer 导出的 docx | 标题后紧跟 2 列表，首格 `XXX_ID:`（如 `SWAD_ID: SWAD-47660`）；`Upstream/Downstream References (n)` 段落后的表是上下游引用 |
| `heading` | sad-generator md、手写 Word | ID 从标题文字里按 `id_regex` 找；没有就是 `NO-ID`（不编造） |

CodeBeamer 导出的特点（BBS 实例）：Heading 3–8 为条目，标题号是文字（`9.1.1.4.1 1 DADC_vidInit`，多出的序号会被剥掉）；同一层级的接口有的挂在「Components APIs」下（H7），有的直接挂在组件下（H6）——所以**接口按「Syntax:」行识别，不按层级**。

## 锚点分类（全部按双语标题正则，见 `assets/sad_profiles/aspice_sad.json`）

- 模块 = 「软件组件 / Software Components」章的子标题；组件 = 模块的子标题（排除 Standard/COTS/Reused）
- 接口 = 组件子树里带 `Syntax:`/`原型` 行的表（纵向），或表头含「原型/签名」的横向 API 表
- 使用方 = 各组件「外部接口(依赖) / External Interface(Dependencies)」表第一列里的函数名，经 RTE 别名解析后对到提供方
- 动态行为 = 软件运行模式、软件功能模式（状态机）+ 「时序管理」下的叶子标题（时序）
- 资源消耗 = 共享资源、共享资源保护、内存消耗 + 各组件「资源约束」按模块聚合（`Component Resource Constraint - <模块>`，ID 取模块 ID）
- 性能需求 = 进程识别、时基识别、实时架构下的中断、循环任务、最坏 CPU 负载、内存大小

项目差异：`sad.extra_anchors` 追加规则（`title_regex` / `within_regex` / `in_components` / `aggregate` / `leaf` / `kind`），`sad.profile_overrides` 覆盖任意键。

## 图：源码优先，图片兜底

1. PlantUML（`@startuml…@enduml`，md 代码块或 docx 中连续段落）与 Mermaid（```` ```mermaid ```` 或以 `sequenceDiagram`/`stateDiagram` 开头的段落）直接解析为消息序列/状态转移。
2. 状态转移表：表头含「起始/跳转/条件」或 `[TRANS_A_TO_B] | 条件` 形式的两列表。
3. 只有图片（含 Visio OLE 对象的 EMF/PNG 预览，EMF 自动转 PNG）→ `IMAGE-ONLY`：
   - Claude 读 `ws/sad/images/img_xxx.png`，参考 `arch_model.json` 里该锚点的 `diagram_hints`（嵌入 Visio 的形状文字：生命线、调用名）
   - 按 `assets/arch_supplement.example.json` 写 `ws/sad/arch_supplement.json`（键 = 锚点 ID），`verified: false`
   - 重新 `swit.py ingest`；人工核对后改 `verified: true`
   - 在报告/沟通中建议上游 SAD 附带 PlantUML/Mermaid 源码（推荐写法：图下方放源码代码块，或附录）

## 告警含义

| 代码 | 处理 |
|---|---|
| `NO-ID` | SAD 条目没有 ID：反馈 SAD 作者补；矩阵里显示 NO-ID |
| `DUP-INTERFACE` / `NAME-CASE` | 同一接口出现多次 / 大小写不同写法：先修 SAD |
| `IMAGE-ONLY` / `UNVERIFIED` | 读图转写 / 人工确认 |
| `NO-DIAGRAM` | 动态行为无图无表：只能按文字派生，用例文本要特别说明依据 |
| `NO-COMPONENT-CHAPTER` | 找不到组件章：调整 `components_chapter_regex` |

## 变更比对

`diff.py` 按锚点 key 比较内容哈希（接口：名称/签名/描述/参数/返回/使用方；其余：名称/正文/图/转移）。只改格式不改内容时 status 判 execute。

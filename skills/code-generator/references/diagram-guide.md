# 分层架构图绘制要求

代码生成过程里要产出一张**分层架构图**，作用有两个：① 把第 3 步建好的"分层 + 模块"计划可视化，**在写代码前
肉眼校验**它和 SAD 分层图是否对得上（层序、横切、每层模块）；② 作为交付物，让维护者一眼看懂工程结构。

图**必须与代码同源**：数据来自 `layers.json` + `module_spec.json`（第 3 步的产物），不另起炉灶手编——否则图和
代码会漂移。脚本 `scripts/render_layer_diagram.py` 据此自动出图。

## 绘制要求（硬性）

1. **纵向逐层堆叠**：`layers.json` 里**非横切**的层，按高→低纵向排列。每层包含：
   - 左侧**彩色竖标签**（层名，中文项目用中文）；
   - 顶部**层标题条**（层名 + `（前缀 xxx_）`，前缀取自 `file_prefix`）；
   - 层内**模块卡片块**（渐变圆角块）；模块若带 `group` 字段则按组画虚线分组框（如 System/Connectivity）。

2. **横切层必须画成竖条，不占层序**：`layers.json` 的 `cross_cutting`（如 `Bus`/`Types`/`Cfg`）一律画成
   **右侧竖条**，竖向**只跨它的使用者层**，并用虚线箭头连到这些层。**严禁**把横切层塞成一个横向的普通层——
   那样既不符合"横切=任意层可用"的语义，也会误导依赖方向。
   - **使用者层怎么定**：脚本扫 `module_spec` 里各模块的 `deps`，凡依赖了该横切层模块/头的层即为使用者，
     竖条跨[最高使用者层, 最低使用者层]；也可在 `layers.json` 用 `cross_spans:{"Bus":["App","Hal"]}` 显式指定；
     都没有则默认跨全部纵向层。
   - 竖条底部可标注它**向下依赖**谁（如 Bus 依赖 `Service/OSIF` 做互斥/队列），方向仍向下，不破坏分层。

3. **配色与字体**：层色用 `layers.json` 的 `colors:{层:{fill,accent}}`；没给就用脚本内置调色板循环。中文字体
   默认 `SimHei`（缺失时换 `Noto Sans CJK SC`），可用 `--font` 覆盖。

4. **不硬编码任何项目**：层数/层名/模块/颜色/前缀全部来自配置。换项目只换 `layers.json` + `module_spec.json`。

## 命令

```bash
python3 scripts/render_layer_diagram.py \
    --layers <layers.json> --spec <module_spec.json> \
    --out <输出基名> --title "<项目名> 软件分层架构"
# 产出 <基名>.svg（始终）+ <基名>.png（装了 cairosvg 时）
```
- **依赖**：SVG 永远能出；PNG 需 `cairosvg`（`pip install cairosvg`）。环境没有时用浏览器/工具打开 `.svg`。
- 渲染引擎也可换 PlantUML（见下"备选"），但**横切层竖条 + 卡片风格优先用本脚本**，PlantUML 不易做出该风格。

## 校验用途（出图后必做一次人工核对）
对照 SAD 的分层架构图逐项核：**层数与层序一致？横切层是否都画成了竖条且跨对了使用者层？每层模块齐全、归层正确？**
不一致就回第 3 步修 `layers.json` / `module_spec.json`（而不是改图），保证"图 = 配置 = 代码"三者同源。

## 备选：PlantUML
若项目要求用 PlantUML（与 `sad-generator` 同源管理图源码），可用 `package`/`component` 画分层，横切层用一个独立
`package` 并在依赖箭头上注明"任意层可用"。但 PlantUML 难复刻竖标签 + 渐变卡片 + 竖条横切的观感，**默认用本脚本**。

# cscope 使用参考

本文件是 SWDD 生成中 cscope 的工具使用手册。**规则**（"必须用 cscope 而非 grep 做函数关系分析"）写在 [SKILL.md](../SKILL.md)；安装步骤写在 [SETUP.md](../SETUP.md) 第 6 节；本文件只讲**怎么用**。

## 为什么是 cscope，不是 grep

- cscope 理解 C 语法，能正确区分函数定义、调用点、变量引用、字符串字面量、注释，避免 grep 的假阳性
- cscope 是预建索引级别的查询速度，对全项目（数千文件）秒级返回
- cscope 命令跨平台一致（Linux / macOS / Windows-WSL / Windows-MSYS2 / Windows 原生），无需为不同平台写不同脚本

> **例外**：`grep` 仍可用于非 C 语义的搜索 —— markdown/mmd/puml 文件内的格式校验、`#ifdef` 宏名扫描、注释模式匹配等。

## 构建数据库（首次使用或源码变更后必做）

跨平台通用流程，在项目根目录执行：

```bash
# Linux / macOS / Git Bash / WSL / MSYS2
find BBS_K311_APP/src BBS_K311_APP/MCAL -type f \( -name "*.c" -o -name "*.h" \) > cscope.files
cscope -bqk
```

```powershell
# Windows PowerShell（无 find 命令时）
Get-ChildItem -Path BBS_K311_APP\src, BBS_K311_APP\MCAL -Recurse -Include *.c, *.h |
    ForEach-Object { $_.FullName } | Out-File -Encoding ASCII cscope.files
cscope -bqk
```

命令说明：
- `-b` 只建库不进入交互界面
- `-q` 生成快速反向索引（`cscope.in.out` / `cscope.po.out`）
- `-k` kernel mode，不搜索 `/usr/include`（嵌入式项目必须加此项）
- 构建完成后生成 `cscope.out` / `cscope.in.out` / `cscope.po.out` 三个文件，建议加入 `.gitignore`

## 常用查询命令

所有查询统一使用 `-d`（use existing DB，不重建）+ `-L`（line-oriented output，脚本友好）：

| 用途 | 命令 | 等价 vim cscope 快捷 |
|------|------|---------------------|
| 查符号所有引用 | `cscope -dL -0 <符号>` | `:cs f s` |
| 查函数定义 | `cscope -dL -1 <函数名>` | `:cs f g` |
| 查函数调用的函数（callee） | `cscope -dL -2 <函数名>` | `:cs f d` |
| 查函数被谁调用（caller） | `cscope -dL -3 <函数名>` | `:cs f c` |
| 查文本字符串 | `cscope -dL -4 "<文本>"` | `:cs f t` |
| 查 egrep 正则模式 | `cscope -dL -6 "<pattern>"` | `:cs f e` |
| 查文件名 | `cscope -dL -7 <文件名>` | `:cs f f` |
| 查 #include 关系 | `cscope -dL -8 <头文件名>` | `:cs f i` |

**输出格式**（空格分隔四列）：
```
<文件路径> <所在函数名> <行号> <该行源码>
```
可用 `awk '{print $1":"$3}'` 提取文件:行号用于下一步分析。

## SWDD 生成中的典型用例

**用例 1 — 死代码判定（Component Overview Table / 静态图）：**
```bash
# 对模块每个对外接口函数，查是否有调用者
cscope -dL -3 HPWM_vidPwmInit
# 无输出 → 候选死代码；有输出 → 沿宏链继续向上追踪
cscope -dL -3 DRTE_vidPwmInit
cscope -dL -3 HRTE_vidPwmInit
cscope -dL -3 SRTE_vidPwmInit
# 直到找到真正的 .c 文件调用点（如 SMIC_prg.c）
```

**用例 2 — 函数内部调用提取（动态图 2.6 / 流程图）：**
```bash
# 列出 ABBSM_vidMainFunction 内部调用的所有函数，用于构造 PlantUML 动态图
cscope -dL -2 ABBSM_vidMainFunction
```

**用例 3 — 函数定义定位（2.7/2.8 Location 字段）：**
```bash
cscope -dL -1 AINCU_vidMainFunction
# 输出：BBS_K311_APP/src/Source/APP/AINCU/AINCU_prg.c AINCU_vidMainFunction 123 void AINCU_vidMainFunction(void)
```

**用例 4 — 全局变量 / 枚举 / 宏的使用点（2.5 Data Design）：**
```bash
cscope -dL -0 AINCU_u16PeriodTime
cscope -dL -0 MC36XX_AXIS_X
```

**用例 5 — External / Internal 函数分类：**
```bash
# 外部调用方来自本模块之外 → External
# 外部调用方只在本模块内 → Internal
cscope -dL -3 AINCU_bInclOutRange | awk '{print $1}' | sort -u
# 若所有调用者文件都在 swdd/AINCU/ 对应目录下 → Internal，否则 External
```

## 跨平台注意事项

| 平台 | 推荐方式 | 命令前缀 |
|------|---------|---------|
| Linux | 原生 apt/dnf 安装 | `cscope -dL -N` |
| macOS | Homebrew 安装 | `cscope -dL -N` |
| Windows + WSL | 在 WSL 中安装并运行 | `wsl cscope -dL -N`（从 PowerShell 调用）或直接进入 WSL |
| Windows + MSYS2/Git Bash | `pacman -S cscope` | `cscope -dL -N` |
| Windows 原生 | Chocolatey 或 sourceforge 二进制 | `cscope.exe -dL -N` |

**路径空格**：Windows 项目路径若含空格，必须将 `cscope.files` 中的路径用双引号包裹。

**数据库时效性**：每次源码变更后必须重新 `cscope -bqk`，否则查询返回过时结果。建议在 SWDD 生成开始前强制重建一次。

## cscope 的限制（必须人工补救）

1. **不理解 `#if 0` / `#ifdef MACRO` 未启用分支** —— cscope 会把这些分支中的调用也算进结果。找到 caller 后必须用 Read 工具查看上下文确认是否在有效编译路径内。
2. **宏函数链** —— `#define FOO BAR` 这种宏函数 cscope 只能定位到 `#define`/`#undef`。宏链追踪必须手动沿链逐层 `-3` 查询。
3. **函数指针 / 回调** —— 跨模块的函数指针调用 cscope 无法自动关联，需要通过回调注册点（通常是 Init 函数中 `*fp = myCallback`）手动追踪。

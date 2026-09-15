# Ceedling 工程搭建（宿主机单元验证）

以下配置在 Ceedling 1.1.7 + Ruby 3.3 + MinGW gcc 14 上实测通过。
路径与模块名按项目改写，结构不变。

## 目录

```
unit_test/<模块>/
  project.yml
  support/            # 只放 MCAL 基础类型替身与 OS 替身
    Platform_Types.h
    Std_Types.h
    Compiler.h
    OsService.h
    OsService_stub.c
  test/
    test_<模块>.c
  build/              # Ceedling 产物
```

## project.yml 的四条关键约定

**1. 被测模块目录放 `:paths :include`，不要放 `:paths :source`。**
整 TU 测法（`#include "<模块>_Prg.c"`）下该文件已被测试文件包含，
再让 Ceedling 单独编译一次，链接期会重复符号。

```yaml
:paths:
  :test:    [test]
  :source:  [support]                       # 只有 OS 替身的 .c
  :include:
    - support
    - ../../<源码目录>                       # 被测模块
    - ../../<配置目录>
    - ../../<类型目录>
    - ../../<各服务层目录>                    # CMock 从这些头文件生成桩
  :support: [support]
```

**2. Ceedling 1.x 的 `:use_test_preprocessor` 取值是符号，不是布尔。**
`:none` / `:all` / `:tests` / `:mocks`。写 `TRUE` 会直接校验失败：
`ERROR: :project >> :use_test_preprocessor is ':true' but must be one of {...}`

**3. CMock：`:treat_externs: :include`、六个插件、项目 typedef 全进 `:treat_as`。**

- `:treat_externs: :include` 必配。项目头文件里的原型几乎都写成 `extern void X(void);`，
  CMock 默认**跳过** extern 原型，生成的 `mock_X.c` 是空的。CMock 本身不报错，
  症状出现在链接期：一串 `undefined reference to 'X_ExpectAndReturn'`。
- 通过指针返回值的服务接口（`DEV_GetPressure(ch, &val)`）必须靠 `:return_thru_ptr` 打桩；
  带缓冲区入参的（`Eeprom_Write(addr, buf, len)`）要 `:array` 才有 `_ExpectWithArrayAndReturn`；
  不关心入参的场景要 `:expect_any_args`，否则只能用 `_ExpectAndReturn` 精确匹配。
- `:treat_as` 里除了 AutoSAR 的 `uint8/uint16/...`，还要列项目自己的别名（`u8`/`u16`/`u32`/`bool`），
  否则 CMock 把它们当结构体做 memcmp，断言信息只有一串十六进制。

```yaml
:cmock:
  :mock_prefix: mock_
  :treat_externs: :include
  :plugins:
    - :ignore
    - :array
    - :expect_any_args
    - :ignore_arg
    - :callback
    - :return_thru_ptr
  :treat_as:
    uint8: HEX8
    uint16: HEX16
    uint32: UINT32
    boolean: UINT8
    u8: HEX8            # 项目别名，来自 ut_spec.json 的 cmock_treat_as
    u16: HEX16
    u32: UINT32
    bool: UINT8
```

`scripts/gen_project_yml.py --spec ut_spec.json` 会按上面的形状生成 `project.yml`，
include 列表、宏、`cmock_treat_as` 都来自 `ut_spec.json`，不存在的目录自动丢弃
（Ceedling 遇到不存在的 include 目录直接拒绝启动）。已有的 `project.yml` 不会被覆盖，
要重新生成加 `--force`。

**4. 把 gcov 插件的报告整个关掉**，覆盖率由 `scripts/collect_coverage.py` 与
`scripts/build_evidence.py` 负责。

插件按 `:paths :source` 过滤，而整 TU 测法下被测文件**故意不在**那条路径上，
于是它产出的 `HtmlDetailed` / `Cobertura` 是空的——实测：

```
GcovCoverageResults.html   ->  Lines: 0.0%  0 / 0 / 0     （文件列表为空）
GcovCoverageCobertura.xml  ->  <packages/>
```

**空报告比没有报告更危险**：它会被当成证据写进测试报告的"证据"列，评审员点开是一片空白。
所以 `:gcov:` 段下不要写 `:reports:`：

```yaml
:gcov:
  :utilities:
    - gcovr
  # 不配 :reports:，见上
```

## support/ 的边界

**只替换两样东西**：MCAL 基础类型、RTOS。业务头文件（类型定义、配置宏、服务层接口）
一律用真身——它们本来就没有硬件依赖，替换反而会让测试脱离真实定义。

`Platform_Types.h` 的宽度必须与目标机一致，从项目真实的 MCAL 头拷贝 typedef，不要凭印象写。

OS 替身把时基做成普通变量，测试可以确定性地推进时间，而不是真的等：

```c
extern TickType_t OSIF_TestTick;
TickType_t xTaskGetTickCount(void);
void vTaskDelayUntil(TickType_t *pxPrev, TickType_t xInc);
```

任务注册宏（`APP_CFG_START` / `APP_CFG_END` 之类）保留形状、丢掉 RTOS 对象即可，
目的只是让 `.c` 里的注册代码能编译过去。

## 测试文件骨架

```c
#include "unity.h"
#include <string.h>          /* setUp 里 memset 上下文要用 */

#include "mock_SVC_XXX.h"    /* 每个被打桩的服务层头文件 */
...
#include "<模块>_Prg.c"      /* 整 TU：static 函数与文件级状态都可直接访问 */

void setUp(void)
{
    memset(&s_ctx, 0, sizeof(s_ctx));   /* 逐个复位文件级状态，避免用例间串扰 */
    ...
}
void tearDown(void) {}

/* <单元名>.001 - covers branch N: <这条用例为什么存在> */
void test_<单元名>_001_<行为>(void)
{
    ...
}
```

## 标记注释：测试与用例之间唯一的权威

测试函数的序号和用例号**互不相干**——`test_O2_UpdatePressGate_001` 实现的可能是
`O2_UpdatePressGate.004`。所以两者的对应只能由注释声明，工具也只认注释。
每个测试上方必须有下面两种形态之一：

```c
/* <单元>.<用例号> - covers branches a/b/c: <这条用例为什么存在> */
void test_<单元>_<序号>_<行为>(void)

/* supplementary - adds branches x/y: <为什么要多这一条> */
void test_<单元>_<序号>_<行为>(void)
```

- **covers** 写的是这个测试走完的**完整路径**，不是"本测试新增的分支"。
  它必须等于、或包含该用例声明的分支集（包含是合法的：测试驱动循环跑多个元素时，
  循环内判定的两侧都会走到）。
- **supplementary** 用于用例集之外的补充测试。声明它新增了哪些分支；
  若一条分支都不新增（只是换数据再验一遍行为），写 `supplementary - 不新增分支：<理由>` 即可。

### 怎么判断一个测试该标用例号还是标 supplementary（最容易搞错的一条）

**判据只有一条：把这个测试实走的分支集算出来，看它是否恰好等于某条用例的分支集。**

| 情况 | 标法 |
|---|---|
| 实走分支集 **等于** 某条用例 | 标那条用例号。**换了输入取值也仍然是那条用例** |
| 实走分支集是某条用例的**超集** | 标那条用例号（测试驱动循环跑多个元素时会走到循环内判定的两侧） |
| 实走的路径**用例集里没有** | `supplementary` |
| 断言了用例期望输出之外的行为 | `supplementary` |

**别把"换个取值"当成补充测试。** 等价类与边界值天然会让同一条用例有多个测试：

```c
/* SUT-00011 SCN_SanitizeGear.001 - covers branch 1: 刚超出范围 */
void test_SCN_SanitizeGear_001_above_range_is_off(void)   { ...SCN_SanitizeGear(2u)... }

/* SUT-00011 SCN_SanitizeGear.001 - covers branch 1: 同一条用例，取类型上边界 */
void test_SCN_SanitizeGear_002_max_uint8_is_off(void)     { ...SCN_SanitizeGear(255u)... }
```

`255 > 1` 和 `2 > 1` 走的是**同一条分支 1**，所以两个测试实现的是同一条用例，
第二个不是"用例集之外"的东西。**一条用例有多个测试是正常的**，单元验证报告（HTML）会把它们归到一组。

真正的 supplementary 长这样——它跨两个周期先走分支 1 再走分支 2，
没有任何单条用例是这个路径：

```c
/* supplementary - 不新增分支：欠压恢复后请求自动续跑，无需重新下命令 */
void test_SCN_ManagementPeriod_003_resumes_after_undervoltage(void)
```

判不准时不要凭感觉：用 `covers` 标上你认为的用例号跑一次
`scripts/reconcile_cases.py`，它会告诉你实走分支与该用例是否一致。

### 标记必须紧贴函数

`supplementary` 与 `adds branches` **只在紧邻函数的那一个注释块内生效**。
文件头里解释约定时写到 "supplementary" 这个词，不会波及下方第一个测试——
工具按注释块判定，块与块之间不继承。
（用例号是例外：一条注释可以按顺序分给随后的多个测试，见下条。）
- 一条注释可以带多个用例：`/* O2_GearToDuty.001..005 - covers branches 1..5 */`
  会按顺序分给紧随其后的 5 个测试函数。这种写法下**分支号属于整组**，
  工具不会把它当成每个测试各自的路径。
- 用例 ID（`SUT-00042`）可以写在前面，但不是必需的——它会随重新编号变动，
  用例名才是稳定的键。

`scripts/self_check.py --root <项目根>` 会机械校验这两项（评审检查单第 19/20 项）；
声明与用例表不一致时用 `scripts/reconcile_cases.py` 修。

## 环境准备

```bash
winget install --id RubyInstallerTeam.Ruby.3.3 --silent \
    --accept-package-agreements --accept-source-agreements
gem install ceedling --no-document
pip install gcovr
```

Ruby 装完后 `C:\Ruby33-x64\bin` 需要在 PATH 里。gcovr 走 pip 而非 gem。

## 宿主机编不过的目标机代码

`gen_host_shim.py` 只为一种情况存在：文件里某个**不执行**的构造让 64 位 gcc 拒绝整个文件。
实例 `DMCU_cfg.c`：

```c
uint32 const FastWkupBootVectorTable[] = {
    (const uint32)Standby_Stack_StartAddr,
    (const uint32)((uint32 *)&MCU_vidFastWkupBootAddress),   /* 64 位上：not constant */
    (const uint32)((uint32 *)&undefined_handler),
};
```

`-m32` 在 MinGW64 上没有运行库，`#define uint32 uintptr_t` 会把整个 TU 的 ABI 改掉——都不行。
于是在 `ut_spec.json` 里声明两处逐字替换（`old`→`0u`，附理由），脚本生成
`support/DMCU_cfg_host.c`，测试文件 `#include "DMCU_cfg_host.c"` 而不是原文件。
副本首行 `#line 1 "<原文件绝对路径>"`：gcovr 把覆盖率记到原文件、逐行标注读的也是原文件。

副本放在 `support/` 下并**沿用原文件名**（`support/DMCU_cfg.c`）时，Ceedling 会因为测试文件
`#include "DMCU_cfg.h"` 自动把它编成独立目标文件链接进来——于是它不再是整 TU 的一部分，
测试文件里可以定义同名函数把它的内部函数顶掉（`link_flags: -Wl,--allow-multiple-definition`，
测试目标文件在链接顺序里排第一）。这就是"一条用例只验证一个单元"在跨文件内部调用上的做法。
整 TU 包含（`#include "X_host.c"`）只在需要摸文件内 static 量时用。

寄存器块另有办法，不需要副本：

```c
/* support/ut_host_regs.h — 通过 compile_flags: ["--include=ut_host_regs.h"] 强制包含进每个编译单元 */
#if __has_include("S32K311_DCM_GPR.h")      /* unity.c / cmock.c 没有工程 include 路径 */
#include "S32K311_DCM_GPR.h"                /* 先让厂商头定义 IP_DCM_GPR */
#undef IP_DCM_GPR
extern DCM_GPR_Type ut_dcm_gpr;             /* 定义放在 support/<模块>_test_globals.c */
#define IP_DCM_GPR (&ut_dcm_gpr)
#endif
```

强制包含而不是写在测试文件里，是因为被测 `.c` 若被单独编译（见上），测试文件里的
`#define` 根本影响不到它。

## 三个必踩的坑

### `*_ReturnThruPtr_*` 的存储必须活到调用发生

CMock 保存的是**指针**，在被打桩的调用真正发生时才解引用。下面这种写法是错的：

```c
static void expect_pressure(uint16 abs_kpa, OXY_Status_t st)   /* 错误 */
{
    DEV_GetPressure_ExpectAndReturn(CH, NULL, st);
    DEV_GetPressure_IgnoreArg_pu16Kpa();
    DEV_GetPressure_ReturnThruPtr_pu16Kpa(&abs_kpa);   /* 函数返回后悬空 */
}
```

症状很具迷惑性：有时通过（栈上残值恰好还在），有时给出毫不相干的失败值。
正确做法是用**静态环形缓冲**，让一次排队的多个期望各占一个槽位：

```c
#define RING 8
static uint16 s_absRing[RING];
static uint8  s_absIdx;

static void expect_pressure(uint16 abs_kpa, OXY_Status_t st)
{
    s_absRing[s_absIdx] = abs_kpa;
    DEV_GetPressure_ExpectAndReturn(CH, NULL, st);
    DEV_GetPressure_IgnoreArg_pu16Kpa();
    DEV_GetPressure_ReturnThruPtr_pu16Kpa(&s_absRing[s_absIdx]);
    s_absIdx = (uint8)((s_absIdx + 1u) % RING);
}
```

`setUp()` 里把索引清零。

### 函数内 static 状态只能靠测试顺序

文件级静态量在 `setUp()` 里 memset 就能复位；**函数内**的 `static u8 u8DelayCnt;`
从测试文件里摸不到——它没有名字可引用。要测"计数到 N 后触发"的分支，只能靠前一个测试
把它推到 N-1，本测试再跑一个周期。做法：

```c
/* ABBSM.015 - covers branches 2/4/9: 21 个周期内 u8DelayEnterIntTrg 累加到 21 */
void test_ABBSM_vidMainFunction_015_delay_counting(void) { ... 21 cycles ... }

/* ABBSM.016 - covers branches 2/4/10: 依赖 test_015 留下的 u8DelayEnterIntTrg == 21，
   Unity 按文件内定义顺序执行，不要移动这两个函数的相对位置 */
void test_ABBSM_vidMainFunction_016_delay_expired(void) { ... 1 cycle ... }
```

两个测试必须在**同一个测试文件**里（Ceedling 每个测试文件一个可执行程序，静态量不跨文件），
用例的预置条件要写上"在 xxx 用例之后执行"。这是源码的可测性缺陷，报告里记一笔；
不要为了解耦在测试里加 `#define static` 之类的花招——那样测的就不是交付代码了。

### 无限循环的任务入口是可测的

`for(;;)` 的任务体不必标成"不可测"。在 OS 替身里放一个逃逸钩子：

```c
/* OsService.h */
extern jmp_buf OSIF_TestEscape;
extern int     OSIF_TestLoopBudget;   /* <0 关闭逃逸 */
extern int     OSIF_TestLoopCount;

/* OsService_stub.c: vTaskDelayUntil 末尾 */
OSIF_TestLoopCount++;
if ((OSIF_TestLoopBudget >= 0) && (OSIF_TestLoopCount >= OSIF_TestLoopBudget))
{
    longjmp(OSIF_TestEscape, 1);
}
```

测试里设预算并 `setjmp`，就能真跑若干周期再跳出，验证周期计数、步进与节拍：

```c
OSIF_TestLoopCount = 0;
OSIF_TestLoopBudget = 3;
if (setjmp(OSIF_TestEscape) == 0)
{
    TaskEntry(NULL_PTR);
    TEST_FAIL_MESSAGE("task entry returned; it must loop forever");
}
OSIF_TestLoopBudget = -1;
```

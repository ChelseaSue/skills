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

**3. CMock 插件至少启用这四个。**
通过指针返回值的服务接口（`DEV_GetPressure(ch, &val)`）必须靠 `:return_thru_ptr` 打桩；
不关心入参的场景要 `:expect_any_args`，否则只能用 `_ExpectAndReturn` 精确匹配。

```yaml
:cmock:
  :mock_prefix: mock_
  :plugins:
    - :ignore
    - :expect_any_args
    - :ignore_arg
    - :callback
    - :return_thru_ptr
  :treat_as:
    uint8: HEX8
    uint16: HEX16
    uint32: UINT32
    boolean: UINT8
```

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

## 两个必踩的坑

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

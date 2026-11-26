# 宿主机集成测试（Ceedling 1.x + Unity + CMock）

## 与单元测试的区别

| | SWE.4（swuv） | SWE.5（本 skill） |
|---|---|---|
| 被测对象 | 函数单元 | 组件之间的接口与交互 |
| 被测源码 | 测试里 include .c | `:paths :source` 真实编译链接 |
| 打桩 | 单元之外一切 | **只桩边界**：MCAL/BSW/OS 与本轮范围外组件 |
| 覆盖率 | 语句/分支 | 函数覆盖 + **跨组件调用覆盖** |

## 搭建循环

1. `swit.py host yml`：本轮 `scope.components` 的目录进 `:source`；所有组件目录 + `include_dirs` 进 `:include`；support/ 排第一。
2. `swit.py host standins`：为每个范围外组件生成**同名替身头**（找到声明其接口最多的头文件，如 `DWDG_int.h`），内容 = `standin_includes` + SAD 原型（签名笔误自动修正，修不了的注释并报告）。手改过的替身不会被覆盖（`--force` 才重写）。
3. `swit.py host probe`：逐个 .c `gcc -fsyntax-only`，汇总缺失头与错误。按提示在 `ws/host/support/` 加替身（MCAL 类型头、寄存器头、被替身遗漏的宏/类型），重复到无错。
4. `swit.py host boundary`：列出本轮组件调用的范围外函数及 SAD 签名——写 MCAL 边界替身时照抄。
5. `swit.py host skeleton`：按组件/行为分组生成占位测试（TEST_IGNORE），已有标记的用例跳过；同名文件存在时写 `_todo.c`。
6. 写测试 → `swit.py run --round N --ceedling`。

项目可把 support 放到受控目录（`sources.support_dir`），与工作区分离、纳入配置管理。

## 测试文件约定

```c
#include "unity.h"
#include "swit_host.h"          /* SWIT_RUN_CYCLES / SWIT_RUN_UNTIL：以节拍驱动周期任务 */
#include "HADC_int.h"           /* 本轮真实组件头 */
#include "mock_Adc.h"           /* 边界：必须在测试文件本身 include，Ceedling 才会生成并链接 */
TEST_SOURCE_FILE("HADC_prg.c")  /* .c 与头不同名时必须写（清单见 test/swit_sources.txt） */

/* SWIT: SWIT-00039, SWIT-00038 */
void test_hadc_get_vlt_returns_filtered_battery_voltage_from_dadc_samples(void) { ... }
```
- 标记管到下一个标记之前的所有测试函数；一个测试可实现多条用例，一条用例可有多个测试；用例通过 = 其全部测试通过。
- 没有标记的测试、标记引用不存在用例都会被 check 报出；**不按函数名猜**。
- 边界默认返回取失败/中性值，测试显式打开需要的路径（`_Stub` 回调写出参、记录参数）。
- MCAL 中断/DMA 填充的缓冲：用 `Adc_SetupResultBuffer_Stub` 拿到组件注册的缓冲指针，测试直接写入模拟转换结果。
- 有状态组件（滤波器、计数器）跨测试共享静态量：跑到收敛（如 10 点滤波跑 12 拍）再断言，或在预置条件写明顺序依赖。

## 覆盖率口径

- 函数覆盖：gcov JSON `functions[].execution_count`，只统计本轮组件目录下的文件，多个测试可执行文件取并集。
- 调用覆盖：gcc `-fcallgraph-info=su,da` 生成的 `.ci` 给出调用点（调用方文件:行）；被调方定义所在文件归组件；**两个本轮组件之间**的调用点才计入；执行与否看 gcov 该行 `calls[].returned`。同一行多个调用 = ambiguous，全部返回才算执行。到桩的调用单列为边界调用（信息）。
- 架构漂移：`.ci` 中外部链接（裸名）且 SAD 未定义的函数列为「SAD 未定义的公开函数」。

## 常见坑

1. MinGW `adc.h` 与 MCAL `Adc.h` 大小写冲突 → `CLSID/GUID/IID` 未知类型：support/ 放 `Adc.h` 替身。
2. Ceedling 只按测试文件里直接 include 的头链接源文件 / 生成 mock；把 mock include 藏进公共头不会生效。
3. `:treat_externs: :include` 必配（原型带 extern 时否则 mock 为空）。
4. Ceedling runner 会重排 include：公共头里不要写调用 `*_Ignore()` 的内联函数，用宏。
5. 源文件 include 另一个 .c：测试里别再 include 它的头，否则重复符号。
6. 未定义宏在 `#if` 中为 0，分支静默选错——按实际编译结果写测试，并记录发现。
7. `#if 1` 块中的 `/*` 嵌套注释会改变代码结构，读代码时以编译结果为准。
8. 删除测试文件后旧结果残留：改动大时 `ceedling clobber`。
9. 读源码判断缺陷前先跑测试；`grep -v '^\s*\*'` 之类的注释过滤会删掉 `*ptr = x;` 行。

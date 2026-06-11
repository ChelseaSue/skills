# 模块骨架模板（.h / _Cfg.h / .c）

脚手架与逐模块都用这套模板。要点：**头文件是契约**（公开接口 + 语义注释 + 追溯标注），`.c` 是实现，
`_Cfg.h` 是编译期配置。所有写法都对齐 `misra-c2012.md` 与 `layering-rules.md`。

> 下面的 `<Module>`、`IF_`、`<需求ID>`、层目录名都是占位符——**按真实 SAD/项目命名替换**，不要照抄。

## 1. 接口头 `<Module>.h`
```c
/*!
** @file    <Module>.h
** @brief   <一句话职责>。所属层：<层名>。
** @implements <需求ID>, <需求ID>     // ← 本模块覆盖的 SRS 需求，追溯用
** @version V0.1
** @date    <日期>
*/
#ifndef <MODULE>_H_          /* include guard：MISRA 必需 */
#define <MODULE>_H_

#include "IF_Types.h"        /* 横切层：统一返回码/类型 */
#include "<Module>_Cfg.h"    /* 同模块编译期配置 */
/* 只可再 #include：相邻下层接口 + 同层公开接口 + 横切层。绝不含上层、不跳层。 */

#ifdef __cplusplus
extern "C" {
#endif

#define <MODULE>_API_VERSION  1u

/* 公共数据结构属于头文件契约：本模块对上层暴露的 typedef / enum / struct 在此定义，
 * 让上层既拿到"公共函数"也拿到"公共数据结构"。复杂数据按指针在接口间传递（入参 const T*）。 */
typedef enum { <MODULE>_STATE_IDLE = 0, <MODULE>_STATE_RUN = 1 } <Module>State_t;
typedef struct {
    uint16_t field_a;   /* <含义/单位/范围> */
    uint8_t  field_b;
} <Module>Status_t;

/** @brief 初始化模块（建立内部状态、注册回调等）。@thread_safe @isr_unsafe */
void <Module>_Init(void);

/** @brief 周期任务（如 10ms/100ms 调度）。@thread_safe @isr_unsafe
 *  @implements <需求ID> */
void <Module>_Tick(void);

/** @brief <功能说明>。@thread_safe @isr_unsafe @blocking <时长/否>
 *  @param  <in/out 说明、范围>
 *  @return IF_OK / IF_ERR_PARAM / IF_ERR_<...>
 *  @implements <需求ID> */
IF_Status_t <Module>_DoSomething(uint16_t arg);

#ifdef __cplusplus
}
#endif

#endif /* <MODULE>_H_ */
```

## 2. 配置头 `<Module>_Cfg.h`
```c
/*!
** @file    <Module>_Cfg.h
** @brief   <Module> 编译期配置（尺寸/阈值/实例号占位）。值缺失处标 TBD。
*/
#ifndef <MODULE>_CFG_H_
#define <MODULE>_CFG_H_

#include "IF_Types.h"

/* 编译期常量替代魔法数字（MISRA 友好）。值来自 SRS/SAD/HSI；缺则 TBD。 */
#define <MODULE>_TICK_PERIOD_MS   (10u)      /* TBD: 确认调度周期 */
#define <MODULE>_BUF_SIZE         (32u)      /* TBD: 确认缓冲尺寸 */

#endif /* <MODULE>_CFG_H_ */
```

## 3. 实现 `<Module>.c`
```c
/*!
** @file    <Module>.c
** @brief   <Module> 实现。所属层：<层名>。
*/
#include "<Module>.h"
/* 仅 #include 相邻下层接口（如 HAL 的 IF_*.h）、横切层（IF_Types.h / SignalBus.h）。 */
#include "IF_Gpio.h"          /* 例：本模块经 HAL GPIO 接口操作硬件——不直够 MCAL */
#include "SignalBus.h"        /* 例：同层解耦——读写信号而非互调他模块 */

/* 文件内私有状态：static，单一职责，无动态内存。 */
static uint16_t s_counter = 0u;

void <Module>_Init(void)
{
    s_counter = 0u;
    /* TBD: 初始化下层接口、注册回调、清状态 */
}

void <Module>_Tick(void)
{
    /* TBD: 周期逻辑——严格对齐 SAD 状态机/时序 */
}

IF_Status_t <Module>_DoSomething(uint16_t arg)
{
    IF_Status_t status = IF_OK;

    if (arg > <MODULE>_BUF_SIZE) {      /* 入参范围校验（MISRA + 健壮性） */
        status = IF_ERR_PARAM;
    } else {
        uint32_t v = 0u;
        (void)SignalBus_Read(SIG_SOMETHING, &v, sizeof(v));  /* 丢弃返回值显式 (void) */
        /* TBD: 调下层接口完成功能；单一退出 */
    }
    return status;
}
```

## 模板使用要点
- **追溯标注**：每个模块头与关键函数用 `@implements <需求ID>` 标出覆盖的 SRS 需求——`conformance_check.py`
  靠扫这些标注与 SRS 需求集求差，判断追溯是否 100%。
- **脚手架模式**：函数体留 `/* TBD: ... */`，但**头文件契约要尽量完整**（从 SAD 组件 API 表抄）——契约是后续
  逐模块实现的合同。
- **逐模块模式**：把 `TBD` 换成真实逻辑；状态机/时序严格对齐 SAD；同层协作只经总线/公开接口；硬件只经相邻下层接口。
- **HAL 接口模块**额外遵循 `layering-rules.md` 的 If/Impl 拆分：`If/IF_*.h` 放契约，`Impl/IF_*.c` 调 MCAL/CDD 落地，
  便于换实现/打桩注入。
- **公共数据结构进头文件**：模块对上层暴露的 `typedef`/`enum`/`struct` 写在 `.h`（契约的一部分）；模块**私有**的
  类型/状态留在 `.c` 里。数据传递守 `layering-rules.md §6`：优先参数/返回值，复杂数据 `const T*` 入参 / `T*` 出参，
  不用裸 `extern` 全局，跨模块共享走总线或访问函数。

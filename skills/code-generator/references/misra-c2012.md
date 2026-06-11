# MISRA C:2012 —— 代码生成时的合规要点

权威是项目里的 `MISRA C 2012 Guidelines for the use of.pdf`（185 条规则 + 指令）。本 skill 不照搬全文，而是
**按构造写出本就合规的代码**，再用 `cppcheck --addon=misra` 当自动门禁兜底。把精力放在"生成器能主动遵守、且
违反后果严重"的规则上；纯靠工具的复杂数据流规则交给 cppcheck。

> 规则分级：**Mandatory**（强制，绝不可违反）、**Required**（必需，违反需正式 deviation）、**Advisory**（建议）。
> 生成代码默认满足全部 Mandatory + Required；Advisory 尽量满足。

---

## 1. 按构造遵守的高频规则（写代码时直接照做）

**类型与表示**
- 用 `<stdint.h>` 定长类型（`uint8_t/int16_t/uint32_t`…），不用裸 `int/short/long` 表达有宽度含义的量。(Dir 4.6)
- 整数常量带后缀表明类型/符号：无符号加 `u/U`（`0xFFu`、`100u`、`1uL`）。(R7.2)
- 不做隐式有损/改符号转换；跨类型赋值/运算显式 `(cast)`，且确保不丢位、不改符号。(R10.x “essential type”)
- 有符号与无符号不混算；位运算只用于无符号类型。(R10.1/10.4)

**控制流与结构**
- 每个 `if/else if/for/while` 体都用 `{}`，即使单语句。(R15.6)
- `switch` 必须有 `default`，每个 `case` 以 `break`（或注释标明的有意贯穿）结束；`switch` 条件不是布尔。(R16.x)
- 单一退出更稳；如用多 `return`，保持简单、可读、无资源泄漏。(Advisory 15.5——可控)
- 不用 `goto`（或仅向后跳的受限用法）、不用递归。(R15.1/Dir——避免)
- 循环计数器、控制变量类型一致，边界用同型常量。

**函数与接口**
- 每个函数有原型；参数与返回类型完整；无 `()` 空参（用 `(void)`）。(R8.2)
- 指针入参先判 `NULL`；数组/缓冲操作先校验长度/范围，再访问。
- 丢弃有返回值函数的结果要显式 `(void)func(...);` 表明有意忽略。(R17.7 对 Required 的非 void 返回)
- 不修改 `const`；只读入参标 `const`。
- 不用可变参数 `...`（除非项目明确允许并 deviation）。(R17.1)

**内存与生命周期（嵌入式关键）**
- **禁用动态内存** `malloc/free/calloc/realloc`：用静态分配 + 编译期定尺缓冲。(Dir 4.12 / R21.3)
- 不返回局部对象地址；共享数据生命周期清晰。
- 缓冲区尺寸来自 `_Cfg.h` 的编译期常量，不魔法数字。

**预处理与文件**
- 头文件加 include guard（`#ifndef X_H_ / #define / #endif`）。(Dir——header 防重包)
- 宏尽量用 `static inline` 或带括号的"函数式宏全参数加括号"；避免易错宏。(R20.7)
- 不用 `#undef`；条件编译完整配对。(R20.5)
- 每个源文件单一职责；不在头里定义有外部链接的对象/函数（只声明）。

**杂项常见坑**
- 不用 `//` 之外的注释嵌套问题；不留可达死代码。(R2.x)
- 表达式不依赖求值顺序、无副作用重复（`a[i] = i++` 之类禁止）。(R13.x)
- 浮点不做相等比较；定点优先（如 Q15）。
- 所有 `enum` 显式可控；不依赖隐式枚举值算术。

---

## 2. Deviation（无法避免的偏离）登记格式
某些规则在底层驱动/SDK 对接处无法 100% 满足（如必须读写寄存器做 `volatile` 指针转换）。这时**就地标注**：
```c
/* MISRA deviation R11.4 (int<->pointer): 访问内存映射寄存器，硬件要求；范围受 BSP 限定。 */
volatile uint32_t * const reg = (volatile uint32_t *)REG_ADDR;
```
并在模块或工程的 `deviations.md`（可选）登记：规则号、位置、理由、批准人。`run_misra.py` 报告里这类违规应能
和注释对应上。**没有理由的违规不算 deviation，必须修。**

---

## 3. 自动门禁：cppcheck --addon=misra
```bash
# 安装（本环境若未装）：Debian/Ubuntu
sudo apt-get install -y cppcheck        # 自带 addons/misra.py

# 由 run_misra.py 统一调用；等价的手动命令大致是：
cppcheck --enable=style --addon=misra \
         --suppress=missingIncludeSystem \
         --inline-suppr \
         -I <每个层的 Inc 目录> \
         <代码根>/Source 2>misra_report.txt
```
- `--inline-suppr` 让代码里的 `/* cppcheck-suppress misraViolation */` 行内抑制生效（与 deviation 注释配合）。
- cppcheck 的 misra addon 只给规则**编号**（如 `[misra-c2012-10.4]`），文字描述以 PDF 为准。
- **门禁判据**：Mandatory/Required 违规清零或全部对应到带理由的 deviation；Advisory 违规汇总给用户决定。
- cppcheck 装不上时：退化为**人工按第 1 节逐条核查** + `gcc -Wall -Wextra -Wconversion -std=c11 -fsyntax-only`
  抓一部分类型/转换问题，并在 conformance 报告里注明"MISRA 为人工核查，未过自动门禁"。

---

## 4. 给生成器的速记清单（写每个文件时自检）
- [ ] 定长类型 + 常量后缀 `u`；无隐式窄化/改符号转换
- [ ] 所有分支/循环带 `{}`；`switch` 有 `default` 且 `case` 收尾
- [ ] 函数有原型、`(void)` 空参、指针入参判 NULL、丢弃返回值显式 `(void)`
- [ ] 无动态内存、无递归、无 `goto`、无可变参数
- [ ] 头文件 include guard；宏参数全括号；条件编译配对
- [ ] 浮点不比相等；位运算仅无符号；无求值顺序依赖
- [ ] 无法满足处有 `/* MISRA deviation Rx.y: 理由 */`

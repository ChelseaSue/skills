# lin-can-comm 标准包：适用性与常见坑

## 按节点类型的适用子集（由 node 配置自动过滤）

| 节点 | 适用标准 | 不适用 |
|---|---|---|
| LIN 响应方 + UDS 服务端（典型 LIN 从节点 ECU） | 17987-3（responder 项）、17987-2（网络管理/传输层/诊断）、14229-7、14229-1（按支持的 SID）、14229-2（server 项） | 15765-2、14229-3、11898-1；commander/client 项 |
| LIN 主节点（网关） | 17987-3/-2 的 commander 项（调度表、零星帧、诊断调度）、14229-7 的主节点路由项 | responder 专有项 |
| CAN 节点 + UDS 服务端 | 15765-2、14229-3、11898-1（软件可配部分）、14229-1/-2 | 全部 LIN 项 |

`features` 决定细分：`tp`（多帧传输）、`sleep`（休眠唤醒）、`node-config`（LIN 节点配置服务）、
`functional-addressing`、`reprogramming`、`event-frame`、`sporadic-frame`、`local-wakeup`（会主动唤醒总线）、`can-fd`。
14229-1 的服务类检查项带 `sid`，由 Dcm 服务表（`supported_sids: auto`）决定。

## 本包刻意划为 target 的内容
位级与物理层（间隔场检测门限、同步与位速率容差、回读不一致检测、唤醒脉冲检测）、真实时间窗（P4、唤醒后 100 ms 就绪、
零开销帧接收）、CAN 错误界定计数与振荡器容差。宿主机按节拍测的是“计时逻辑”，不是这些实时/电气特性。

## 判定时的常见坑

| 现象 | 说明 |
|---|---|
| LDF 与 ARXML 的 NAD 不一致 | 主节点按 LDF 寻址，节点按 ARXML 应答，诊断不通；同时核对需求中的 NAD（UDS7-NAD-01、LIN3-NC-11） |
| OEM 要求功能寻址 NAD 0x7E | ISO 14229-7 要求诊断类别 II/III 响应方忽略 0x7E；ISO 17987-2 要求处理功能请求但不回应答。OEM 需求与标准冲突时，用 `applicability_overrides` 记录偏差与理由，不要静默判“符合” |
| LDF 未声明 response_error | LIN 2.x 起响应方必须发布该状态位（LIN3-STA-01），常被遗漏 |
| N_Cr/N_As 实现值小于 LDF 声明值 | 不超上限即符合，但主节点按声明值调度时本节点会提前超时，报告中提示统一 |
| LinTp 的 P2Max 很大 | 不同厂商语义不同（主节点等待时间或响应挂起上限），按 Dcm 的 P2/P2* 判定，LinTp 值作提示 |
| ARXML 目录混有其他项目 | `inputs.arxml` 只列本产品文件；汇总文件与分模块文件同时列会重复 |
| LDF 声明 LIN 2.1、实现按 ISO 17987 | 版本差异点（节点配置服务、ReadByIdentifier 标识符 3 等）走 LIN3-VER-01 评审 |

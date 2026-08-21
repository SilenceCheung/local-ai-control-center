# P0–P2 Production Readiness

更新：2026-08-21。本文区分“代码已实现”和“27B 真机已验收”，不把单次可调用当作生产可用。

## 1. 生产目标

网关服务 Grok Build、Claude Code/CodeG、Codex、OpenCode 等 Agent。完成标准不是聊天返回 200，而是：长上下文、工具循环、取消、重试、缓存、单槽调度和长时间运行都可解释、可恢复、可验收。

默认 `production` 配方：

- 单次输出最多 4096 tokens；请求更大时在网关收敛，并返回 `X-LocalAI-Max-Tokens`。
- 工具任务关闭隐藏 thinking，优先快速产出工具调用。
- 单 MLX 槽、最多 2 个等待、等待 60 秒；过载快速返回本地结构化错误。
- 完全相同的活动请求返回 HTTP 409 `duplicate_inflight`，不会因客户端 retry 再排一份。
- 300 秒 deadline；活动请求可从 App 或 API 取消。

深度分析必须显式发送 `X-LocalAI-Profile: deep`，上限 16384、deadline 900 秒。它不是 Agent 日常默认值。

## 2. 根因对应

| 根因 | 动作 | 可观察证据 |
|---|---|---|
| 配方没有真正激活 | Runtime launch snapshot 与保存配置分离；DFlash 页显示已加载 Target/Draft/quant/cache 与待重启差异 | runtime state `launch_config`；DFlash 当前运行卡片 |
| 20K 冷 prefill | 不承诺首次前缀瞬时完成；默认生产预算和工具 thinking 策略减少无价值 decode；同前缀依赖 L1/L2 warm restore | `prefill_tokens_physical/restored`、`cache_status`、TTFT |
| 缓存与网关调度不可观测 | `/gateway/stats` 和 App 显示 queue、profile、effective budget、deadline、cache、实时请求与取消 | API 页“正在处理的请求”；请求响应头 |

## 3. P0–P2 状态

| 项 | 状态 | 说明 |
|---|---|---|
| 下载误删止血 | 代码完成、自动测试通过 | 下载页无整目录删除；残片清理保留完成文件；完整删除需 scope + 精确模型名 |
| 请求预算 / tool thinking | 代码完成、自动测试通过 | 32000 类请求在 production 实际为 4096；tool thinking=false |
| 去重 / 有界排队 | 代码完成、自动测试通过 | 两个相同并发仅一个进引擎；另一个 409；不同请求仍串行 |
| Claude reasoning / usage / stop reason | 代码完成、自动测试通过 | thinking block、非零输入估算、引擎输出 usage、`max_tokens` stop |
| App 活动请求观测与取消 | 代码完成、Swift build 通过 | 每 2 秒刷新；显示 Agent、输入、工具、预算、elapsed、cache |
| 硬取消 Metal generation | 待真机门禁 | 当前通过关闭 upstream best effort；上游无公开 interrupt API |
| 27B Agent soak | 阻塞于 Target 重下载 | 下载完成后执行以下矩阵，不得沿用删除前的结果当新版本证据 |

## 4. 下载完成后的强制验收矩阵

1. 配方启动证据：Target、Draft、`w4:gs64`、`mode_used=dflash`、接受率均来自本次进程和本次请求。
2. 冷/热 20K：同一固定前缀各跑一次；记录 TTFT、physical/restored prefill、cache status、decode tok/s。热请求必须命中恢复，不能只看总 tok/s。
3. Claude Code：真实仓库完成 read → edit → test → fix → test；验证 thinking/tool_use/tool_result、usage、stop reason，连续 20 回合无 429 retry storm。
4. Grok Build：覆盖辅助请求 + 主任务并发；重复主请求只能有一个运行；工具循环完成。
5. OpenCode 与 Codex：各完成同一 fixture 的读写和测试闭环；不得只做 `hi`。
6. 取消：prefill、decode、queued 三阶段分别取消；10 秒内请求从 inflight 消失且下一任务能进入引擎。若 Metal 仍持续，P1 判失败并实现 pinned runtime interrupt。
7. Soak：至少 2 小时、100 个混合请求；无 runtime crash、无永久占槽、无队列计数泄漏。P95 queue wait 和 TTFT 分冷/热报告。
8. 缓存压力：记录 L1/L2 占用、命中、淘汰与磁盘余量；50GB L2 接近满时仍能回收，不得让下载目录或系统盘失控。

## 5. 发布判定

只有以上 1–8 全部形成同一 build、同一 runtime commit、同一模型文件的证据，才标记“生产力级通过”。当前结论是：P0–P2 代码与非 27B 门禁通过；真机硬取消和新版 Agent soak 待 Target 下载完成，尚不能宣称最终生产验收完成。

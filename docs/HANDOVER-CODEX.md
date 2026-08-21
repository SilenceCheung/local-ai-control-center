# HANDOVER — Local AI Control Center

> 接手者只读本文即可继续工作，无需翻聊天记录。

## 当前版本速查

| 项 | 值 |
|---|---|
| 版本 | v0.4.3-dev · P0–P2 production hardening（2026-08-21） |
| 项目真实路径 | `~/AI/local-ai-control-center`（工作区 `Dflsh/local-ai-control-center` 是符号链接） |
| Web 后台 | http://127.0.0.1:8787（**随 Local AI.app 会话**；默认 Quit 后释放，非登录常驻） |
| 模型 API | http://127.0.0.1:8080/v1 · key `local` · 当前 model `Qwen3.8-27B-4bit`（`api.alias`；`alias_auto` 时随 Target 变） |
| Runtime 内部口 | 127.0.0.1:18080（不对外） |
| macOS App | `dist/Local AI.app` v0.4.0 · bundle `com.localai.controlcenter.app` · `en`+`zh-Hans` · Hardened Runtime。双轨已定：Developer ID 为当前主版本；Mac App Store 为独立架构支线，详见 `docs/DISTRIBUTION-STRATEGY.md` |
| Target | 当前官方配方：`lmstudio-community/Qwen3.8-27B-MLX-4bit`；Heretic 为可切换配方 |
| Draft | 当前官方 DFlash2：`z-lab/Qwen3.8-27B-DFlash2`（`w4:gs64`） |
| Fast 引擎 | `dflash serve`（**dflash-mlx 0.1.10**，固定上游 commit `60803233`；不是 z-lab PyPI `dflash`） · Safe 引擎 `mlx_lm server`（0.31.3） |
| 模型库 | 默认 `~/.lmstudio/models/{org}/{name}`（与 LM Studio 对齐）。换目录必须手动选取或拖放文件夹，不会自动改。HF hub 缓存只扫描不安装 |
| venv | `.venv`（Python 3.12.13，重建于 ~/AI 迁移后） |
| 前端 | React+Vite+TS，构建产物 `frontend/dist`，由 Backend 静态托管 |
| 配置唯一来源 | `config/config.yaml` |
| 跨进程状态 | `data/runtime_state.json` · `data/gateway_stats.json` · `data/lacc.db`(SQLite) |
| launchd | `com.localai.controlcenter.{backend,gateway}`（`RunAtLoad=false`；KeepAlive 仅在 job 已 load 时崩溃拉起。默认 Quit 会 `bootout`） |
| CLI | `~/.local/bin/local-ai {start,stop,restart,status,benchmark,logs,open,app}` |
| 必检 | `.venv/bin/python -m pytest backend/tests -q`（当前 Target 重下、Runtime 未加载：75 passed / 17 live skipped）· `cd frontend && npx vitest run` · `pnpm build` · `swift build` 或 App：`bash scripts/build_app.sh` |

## 接手必读（5 分钟）

1. **三平面隔离**是本项目的命脉：Control(8787) / Gateway(8080) / Runtime(18080) 三个独立进程，靠 `data/runtime_state.json`（原子写）共享状态。改任何生命周期逻辑前先看 `backend/core/state.py` + `backend/runtime/mlx_provider.py`。
2. Agent 使用 `config.yaml` 的 `api.alias`（默认随 Target 自动生成，如 `Qwen3.8-27B-Heretic-8bit`）。手动改过则 `alias_auto: false`，切换主模型不再覆盖。Gateway 仍把请求里的任意 model 名重写成已加载 Target，所以旧的 `qwen3.8-27b-local` 还能调通。生成规则见 `backend/core/alias.py`。
3. **不造假原则**贯穿全部：Safe 模式无 /metrics 就显示 `—`；GPU 不可得就不显示；协议缺口写在 Agents 页。禁止 mock 数据。
4. 项目**必须**在 `~/AI/`：macOS TCC 拦截 launchd 访问 Desktop（实测 exit 78，`ls` 都会 Operation not permitted）。
5. **菜单栏 App 消费 `/api`，同时拥有会话生命周期**：打开 App 拉起 8787/8080（不自动加载 27B）；Start 加载模型；Stop 只卸载；**默认 Quit 卸载模型并 bootout 控制面**（Settings 可「退出后保持 API」）。Swift 模型字段必须跟 `backend/api/routes.py` 的 snake_case JSON 对齐（`convertFromSnakeCase`）。构建只能走 `scripts/build_app.sh`。UI 字符串走 `Support/{en,zh-Hans}.lproj/Localizable.strings` + `L10n.t`；**必须显式加载 `.lproj` 包**（`system` 下任意 `zh*` 系统语言 → 简体），禁止只依赖 `Bundle.main` 自动匹配。Web 走 `frontend/src/i18n/`。可选覆盖写入 `config.yaml` 的 `ui.language`（App 在 **Settings** 改语言，菜单栏 Popover 不再放语言选择）。禁止写死 `/Users/<username>/...` 作为项目根。登录项启动的是 **App**，不是无界面 8787。**禁止** `pip install dflash` 覆盖 `dflash-mlx` 的 `dflash serve`。Fast 配方在 Settings：`heretic`（默认）与 `official_dflash2`。模型下载落到 `model_dirs` 里第一个非 HF hub 目录（默认 `~/.lmstudio/models/{org}/{name}`）；换库必须手动选文件夹或把文件夹拖到 Models / Settings General，禁止静默改路径。菜单栏状态图标必须是 **template SF Symbol**。Console 侧栏用 `HStack`+`List`，Models 检查器用页内 `HStack` 分栏，**禁止** `NavigationSplitView` / `HSplitView` / `.inspector` / `.searchable`（macOS 上会在后台线程建 `NSSplitViewController` 并 SIGABRT）。分发目标 Developer ID 公证（`scripts/notarize.sh`，profile `local-ai-notary` 或 `$NOTARY_PROFILE`），**不加 App Sandbox**。多层图标要 Icon Composer + Xcode，当前是单层 icns。
6. **模型下载删除边界**：下载页不再提供整目录删除。「从列表移除」只删账本；「清理下载残片」只删 `.part` 与 `.download-incomplete`，保留 config、safetensors 和目录。完整模型整目录删除只允许从「已安装」发起，API 还要求 `scope=installed_model` + 精确 `confirm_model_id`，旧请求直接 422。账本 `data/downloads.json`。旧 `/models/pull/cancel` 等于暂停。
7. **8080 是 Agent 协议网关**，不是聊天转发。Grok/Codex 的 `/v1/responses`、Chat `tool_choice`、Claude Code 的 `/v1/messages` 在 `backend/compat/` 译成引擎 Chat Completions。默认 production 配方：输出上限 4096、工具任务关闭隐藏思考、最多 2 个等待、排队 60 秒；显式 `X-LocalAI-Profile: deep` 才放到 16384。相同请求不会重复入队。改网关后必须重启 **gateway 进程**。

> **分发决策（2026-08-21）**：Developer ID + 公证继续作为 Track A 主版本，且保持无 Sandbox；Mac App Store 是 Track B 独立架构支线，必须独立 target、bundle id、entitlements、helper、文件权限与发布门禁。不得给 Track A 直接打开 Sandbox。完整边界见 `docs/DISTRIBUTION-STRATEGY.md`。

## §0 变更日志（倒序）

### 0.0 · 2026-08-21 — P0–P2 生产加固 + 下载误删止血

| 优先级 | 已完成 | 关键文件 |
|---|---|---|
| 安全 P0 | 下载记录、残片、完整模型三种删除范围拆开；残片清理永不 `rmtree`；完整模型删除增加双字段后端确认；磁盘事实不再只信旧账本状态 | `backend/models/{pull,registry}.py` `backend/api/routes.py` `PagesCore.swift` |
| 网关 P0 | 默认 4096 token 生产预算；tool request 禁用 thinking；deep 显式 opt-in；队列改为 2/60s；完全相同的活动请求 409 `duplicate_inflight`，不再排成第二个 10 分钟任务 | `backend/gateway.py` |
| 协议 P1 | Claude SSE 映射 reasoning → thinking block；`length` → `max_tokens`；usage 从估算输入和引擎最终 metrics 回填；finish reason 不再提前结束 Anthropic 流 | `backend/compat/anthropic.py` `backend/gateway.py` |
| 恢复 P1 | 活动/排队请求提供 cancel endpoint；队列轮询取消；流在取消或 300s production deadline 后关闭上游连接并释放 lease | `POST /gateway/requests/{id}/cancel` |
| 观测 P2 | `/gateway/stats` 展示 effective budget、profile、deadline、queue、duplicate/cancel/budget totals、活动请求与实时 cache；原生 App API 页每 2s 展示请求并可取消 | `backend/gateway.py` `Models.swift` `PagesDFlash.swift` |

**当前事实**：用户误删的 `lmstudio-community/Qwen3.8-27B-MLX-4bit` 正在 LM Studio 重新下载；最后检查约 6.0GB，三个权重仍为 `.part`。本轮未停止下载、未重启 Runtime、未做 27B live soak。代码门禁：Python 75 passed / 17 live skipped；Web 9 passed；Vite production、Swift debug/release、ad-hoc Hardened Runtime App 与 codesign 均通过。完整生产验收与未完成边界见 `docs/P0-P2-PRODUCTION-READINESS.md`。

> 取消的已知边界：网关能停止排队和关闭客户端/上游连接，但 `dflash-mlx 0.1.10` 没有公开 interrupt API。必须在模型下载完成后验证断连是否能在 10 秒内真正停止 Metal generation；不满足则只能通过固定 commit 的 runtime fork 增加 request-id interrupt，不能把当前 best-effort cancel 宣称为硬取消。

### 0.0 · 2026-08-21 — DFlash 配置真相层 + 等待重启交互

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 三态分离 | DFlash 页明确区分保存配置、当前运行启动快照、等待重启差异；切配方和参数后不再伪装成即时生效 | `backend/core/state.py` `backend/runtime/mlx_provider.py` `PagesDFlash.swift` |
| 启动实证 | 新启动将 privacy-safe `launch_config` 写入 runtime state；旧进程兼容读取真实 command，按模型 + quant + reasoning 完整签名识别配方 | `backend/runtime/mlx_provider.py` |
| 参数诚实 | 页面直接显示运行中 Target、Draft、`w4:gs64`、block 来源和 L1/L2 cache；当前引擎不支持的 `draft_bits` / `--block-size` 不再显示为可生效旋钮 | `Models.swift` `PagesDFlash.swift` |
| 原生闭环 | 顶部配方 segmented control；状态为“配置已生效 / 等待重启 / 下次启动”；有差异时提供“应用并重启”主动作 | `AppStore.swift` `Localizable.strings` |

真机复核：正式 App 显示 `official_dflash2`、Target `lmstudio-community/Qwen3.8-27B-MLX-4bit`、Draft `z-lab/Qwen3.8-27B-DFlash2`、Draft quant `w4:gs64`、Checkpoint block、L1+L2 cache，状态“配置已生效”。无中断换版期间 8787/8080/18080 均保持监听。验证：Python **84 passed / 1 skipped**、Swift debug/release build、plist/strings、`git diff --check`、App codesign 全通过。

### 0.0 · 2026-08-21 — DFlash2 生产 Agent 验收 + 可观测调度

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 配方实证 | 当前 `official_dflash2` 已真机加载；进程参数和请求指标确认 `mode_used=dflash`、Draft/量化/接受率均生效 | `config/config.yaml` `backend/gateway.py` |
| 三 Agent 闭环 | Grok Build 1.0.5、Claude Code 2.1.232、OpenCode 1.18.18 均完成真实读文件、改代码、跑测试，外部复核 4/4 通过 | `backend/tests/fixtures/agent_productivity/` `docs/PRODUCTION-AGENT-VALIDATION.md` |
| Grok 调度 | 识别 Grok 同时发出的 100-token 辅助流与 20K/24-tool 主任务；辅助流短暂让行，避免单槽跨层死锁 | `backend/gateway.py` `_EngineLease` |
| 流生命周期 | 识别缺失 `[DONE]` 的 terminal finish；在发送终止事件前释放 MLX 槽；引擎完成 watchdog 清理客户端消失后的占槽 | `backend/gateway.py` `_iter_heartbeat` `_engine_completion_watchdog` |
| 缓存/队列观测 | `/gateway/stats` 增加 request id、agent、协议、输入形状、工具 schema、队列/TTFT/总耗时、physical/restored prefill、cache、DFlash 接受率/速度；不记录正文；历史跨 gateway restart 保留 | `backend/gateway.py` |
| 有界过载 | 单推理槽 + 最多 3 个等待；第五个并发请求快速 HTTP 429 + `Retry-After`，不把 runtime 打崩 | `backend/gateway.py` |
| 推理策略 | reasoning/thinking 统一映射；极短无工具请求关闭 thinking；工具请求强制 temperature 0，避免成功 200 但正文为空及不稳定工具路径 | `backend/compat/{sanitize,responses,anthropic}.py` |

真机结果：18,053-token cold prefill 32.36s；同前缀 warm 仅计算 7 token、恢复 18,046 token，0.198–0.205s。30 次跨协议 soak 30/30，P50 334ms、P95 342ms。Grok 首轮约 19K/49KB tools，25.61s；后续 warm prefill 0.36–0.66s，decode 52.9–66.5 tok/s。完整报告见 `docs/PRODUCTION-AGENT-VALIDATION.md`。

必检：`.venv/bin/python -m pytest -q`；`backend/tests/test_gateway_http.py backend/tests/test_compat.py` 当前 30 passed。修改网关后只重启 8080，保持 18080 已加载模型。

### 0.0 · 2026-08-21 — Phase 2 P0/P1 首批：双轨发布门禁 + 原生交互修正

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 双轨 | 确认 Developer ID 主版本 + 独立 Mac App Store 架构支线；两条线不得共享 entitlements、进程监管或发布门禁 | `docs/DISTRIBUTION-STRATEGY.md` |
| 生产门禁 | `RELEASE_BUILD=1` 在缺少 Developer ID 时构建前失败；签名、公证、staple 成功后自动执行 production release check | `scripts/build_app.sh` `scripts/release_check.sh` |
| 破坏性动作 | 删除已下载模型改为 SwiftUI destructive confirmation，不再用同步 AppKit 模态框 | `AppStore.swift` `ConsoleView.swift` |
| 状态语义 | DFlash 配方切换后的“需重启”改为信息提示，不再伪装成错误；Stop 只卸载模型，不再标记 destructive | `AppStore.swift` `StatusPopover.swift` `PagesDFlash.swift` |
| 导航与可达性 | 增加 Navigate 菜单与 ⌘1…⌘9；侧栏切换、下载行子按钮、DFlash 请求行、日志行的辅助功能语义修正；窄窗口 Models 检查器可折叠 | `LocalAIApp.swift` `PagesCore.swift` `PagesMore.swift` `PagesDFlash.swift` |
| 稳定性修复 | 禁止 SwiftUI 主菜单订阅整个高频 `AppStore`；否则每次 gateway 刷新都会并发重建 `NSMenu` 并触发 SIGABRT | `LocalAIApp.swift` |

验证：Python **69 passed / 10 skipped**；Web Vitest **9 passed**；Vite production build、Swift release build、App bundle、`codesign --verify --deep --strict`、plist/strings/bash 语法与 `git diff --check` 全部通过。当前包为 `adhoc,runtime`，production gate 正确拒绝（缺 Developer ID，不得宣称已发布）。未加载 27B，18080 未监听。自动化服务读取完整 Console 辅助功能树仍超时，未产生新崩溃；Light/Dark、最小窗口截图与签名后 clean-launch 仍是发布前待验收项。

### 0.0 · 2026-08-21 — DFlash2 staging（引擎完成，模型与真机 A/B 进行中）

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 引擎 | 安装器固定 `dflash-mlx` 上游 commit `60803233af4589e18588b9bacbb03880801c828a`，包版本 0.1.10；PyPI 最新仍停在 0.1.8，禁止浮动安装 | `scripts/install.sh` |
| 能力门禁 | DFlash2 必须同时满足 CLI 模型表含 Qwen3.8/DFlash2、且 `DFlash2DraftModel` 可导入；不再拿 `--block-size` 猜能力 | `backend/runtime/recipes.py` |
| Runtime | 仅在 CLI 声明支持时下发 prefill、draft sink/window、L1/L2 prefix cache 与 MLX cache budget；旧 0.1.8 可回滚 | `backend/runtime/mlx_provider.py` `backend/core/config.py` |
| 调优 | DFlash2 Auto Tune 比较 adaptive/full-5、fixed/full-5、fixed/cap-4，不再套用 DFlash1 的 8/16；监控透传 tokens/cycle、cycles 与 adaptive block | `backend/benchmark/engine.py` `backend/monitoring/sampler.py` |
| UI | DFlash2 block size 改成 checkpoint 决定的只读信息；隐藏 DFlash2 不支持的 DDTree；增加 prefill 与缓存预算 | `frontend/src/pages/DFlash.tsx` |
| 当前状态 | `doctor` 全绿，Qwen3.8-DFlash2 注册与导入探针通过；官方 `z-lab` Draft 与等价 Target `lmstudio-community/Qwen3.8-27B-MLX-4bit` 均已文件级验收为 available，本机配方已绑定该 Target；真机 A/B 待用户授权加载 27B 后执行 | 模型库 `config/config.yaml` |
| 回滚 | `.venv/bin/pip install dflash-mlx==0.1.8`；Heretic Target/Draft 未删除，配方默认仍为 Heretic | `.venv` `config/config.yaml` |

验证：Python 61 passed / 17 skipped；Web Vitest 9 passed；Vite production build 通过；Swift debug build 通过（仅既有警告）。

### 0.0 · 2026-08-20 — v0.4.2 CodeG 完整路径：流式锁覆盖整段 SSE + 后置 system 合并

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 现象 | CodeG 选 `Qwen3.8-27B-Heretic-8bit` 发 `hi` 一直 HTTP 503 / Retrying Claude 3/10。小请求 curl 是 200 | 用户 CodeG 窗口 |
| 根因 1 | `_chat_lock` 只包住上游 POST 头。CodeG 并行第二路在第一路还在 prefill 时打进来，dflash/mlx_lm 把 generate 异常映射成 **404** | `backend/gateway.py` `_EngineLease` |
| 根因 2 | Claude Code ACP 的消息是 `system → user → system`。Qwen chat template 要求 system 只能在开头，抛 `System message must be at the beginning.`，同样变 404/503 | `backend/compat/sanitize.py` `coalesce_system_messages` |
| 验收 | 用 CodeG 同款 `@agentclientprotocol/claude-agent-acp` 0.69.0 走 `initialize → session/new → session/prompt`，隔离 `CLAUDE_CONFIG_DIR`，模型 `Qwen3.8-27B-Heretic-8bit`，回 `pong`，网关 200、errors_total=0 | `scripts/codeg_acp_e2e.py` |
| `--bare` | 默认工具、无 ACP 包装时 3.9s 回 `pong` | Claude 2.1.232 bundled in claude-agent-acp |

**验收重点**

1. CodeG **新建会话**（不要接着卡在 503 的旧回合），模型 `Qwen3.8-27B-Heretic-8bit`，发 `hi`：应出回复，底栏不再 503 连打。
2. 双路并发 `POST /v1/messages?beta=true` stream 均为 200。
3. 改网关后只重启 **8080**，不要 Stop 27B。

**必检（本轮）**

- `.venv/bin/python -m pytest backend/tests/test_gateway_http.py backend/tests/test_compat.py -q` → **26 passed**
- 真机 ACP e2e → `ok: true`，`text: pong`，35.2s
- `POST /v1/chat/completions` 成功回合为 200，不再被后置 system 打成 404

### 0.0 · 2026-08-20 — v0.4.1 CodeG/Claude CLI 把 `?beta=true` 写进路径导致「模型不存在」

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 根因 | CodeG 连 Claude CLI 后，请求打到 `POST /v1/messages?beta=true`。部分客户端把 `?` 放进 path，网关 404。Claude/CodeG 把 404 显示成 “selected model may not exist”。报错里的 `[1m` 是粗体 ANSI，不是模型 id 的一部分 | `logs/gateway.log` |
| 路径规范化 | 把 path 里的 query 拆出来；`http://127.0.0.1:8080/` 造成的 `//v1/messages` 收成单斜杠；`%3F` 也拆 | `backend/gateway.py` `normalize_asgi_scope` |
| 探针 | Claude Code 还会 `POST /v1/messages/count_tokens` 和 `HEAD /api/hello`，以前 404 | 同上 |
| 模型列表 | `/v1/models` 额外列出 `sonnet`/`haiku`/`opus` 别名，请求仍重写成已加载 Target | `backend/gateway.py` |
| 引擎 404 | dflash 在 httpd 刚起来、权重未就绪时会对 `/v1/chat/completions` 回 404。Claude Code 把 **任何 404** 显示成 “selected model may not exist”。网关现改为重试 3 次，仍失败则改 **503** | `backend/gateway.py` `_upstream_chat` `_anthropic_error_from_upstream` |
| 配置 | `ANTHROPIC_BASE_URL=http://127.0.0.1:8080`（不要 `/v1`，不要末尾 `/`）。CodeG provider `local-dflsh` 已是这个 origin | `~/.claude/settings.json` CodeG `model_provider` |

**验收重点**

1. `POST /v1/messages?beta=true` 与 path 内嵌 `?beta=true` 均为 200。
2. `POST /v1/messages/count_tokens`、`HEAD /api/hello` 为 200。
3. CodeG 选 `Qwen3.8-27B-Heretic-8bit` 发 `hi` 不再出现 model may not exist。
4. 改网关后必须重启 **8080**（不需要 Stop 27B）。本轮是杀掉 8080 上的 uvicorn 再拉起项目 venv 里的新进程。

**必检（本轮）**

- `.venv/bin/python -m pytest backend/tests/test_gateway_http.py backend/tests/test_compat.py -q` → **24 passed**
- 已 `launchctl kickstart` 重启 8080；18080 runtime 仍 running。`?beta=true` / `count_tokens` 200

### 0.0 · 2026-08-20 — v0.4.0 真机 Agent 闭环（工具→回传→用到结果）

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 口径 | 秘密只在工具返回值 `TOKEN-ALPHA-7` 里。模型必须先 `lookup_code(name=alpha)`，再在终答里写出该 token，才算闭环 | `backend/tests/test_agent_loop.py` |
| Cursor | Chat Completions：`tool_calls` → `role=tool` → 终答含 token | 真机 27B |
| Codex | Responses 非流式 `previous_response_id` + `function_call_output` 通过 | 真机 |
| Codex 流式 | 第一轮 `stream=true` 必须把 `tool_calls` 写入进程内记忆，否则第二轮孤儿 `role=tool` | `gateway.py` `_stream_mapped` |
| Grok | 同一请求里回放 `function_call` + `function_call_output` | 真机 |
| Claude | `/v1/messages`：`tool_use` → `tool_result` → 终答含 token | 真机 |
| bug | 流式 Responses 的 `remember_turn` 原先只存正文、丢掉 tool_calls。已改为 `assistant_chat_message()` | `backend/compat/stream.py` |

**验收重点**

1. `pytest backend/tests/test_agent_loop.py` 五条在 runtime=running 时全绿。
2. 终答必须出现 `TOKEN-ALPHA-7`，不能只是「已调用工具」。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → **65 passed, 1 skipped**
- `test_agent_loop.py` 5 passed（含流式 previous_response_id）
- 未重跑 App 构建（网关由项目 venv uvicorn 热起；本轮已重启 8080，18080 未卸）

### 0.0 · 2026-08-20 — v0.4.0 真机验收 + SSE 心跳不得取消上游读

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 对照 | 同一 Grok 体打 18080：`/v1/responses` 400「streaming is not implemented」、function `tool_choice` 400、`/v1/messages` 404。打 8080：全部 200 | 实测 Fast dflash-mlx |
| Responses | 8080 非流式返回 `object=response` 且 `output` 含 `function_call`；流式含 `response.created` / `output_text.delta` / `completed` | `backend/gateway.py` |
| Chat 工具 | 8080 `tool_choice: {type:function,name:get_time}` → HTTP 200、`finish_reason=tool_calls`、`tool_calls=['get_time']` | 真机 27B |
| Anthropic | 8080 `POST /v1/messages` → `type=message`。`max_tokens` 过小时思考占用配额，正文可能为空，Claude Code 一般会给更大值 | `backend/compat/anthropic.py` |
| 心跳 bug | `asyncio.wait_for(anext)` 超时会取消上游读，预填充 >15s 会丢后续 chunk。改为 `shield` 后超时只发 `: keepalive` | `backend/gateway.py` `_iter_heartbeat` |
| 测试 | HTTP 假上游：`backend/tests/test_gateway_http.py`。真机：`test_api.py` `test_live_*` | |

**验收重点**

1. 18080 仍拒绝 Grok/Claude 方言；8080 翻译后引擎能跑。
2. 心跳测试：预填充延迟时先收到 `: keepalive`，随后仍有正文（不会只心跳就结束）。
3. 真机套件在 runtime=running 时不再 skip。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → **58 passed, 1 skipped**（skip=`test_stopped_runtime_gives_structured_error`，因为 runtime 正在跑）
- 真机 8080：Responses / Chat function `tool_choice` / Responses SSE / `/v1/messages` 均为 HTTP 200
- 未重跑 `pnpm build` / `build_app.sh`（本轮无前端与 Swift 变更；网关由项目 venv uvicorn 加载）

### 0.0 · 2026-08-20 — v0.4.0 Agent 协议网关（Responses / 工具 / Anthropic）

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 产品 | 8080 给 Agent 用，不给聊天框用。外来协议在网关翻译，Runtime 仍只跑 Chat Completions | `backend/gateway.py` `backend/compat/` |
| Responses | Grok/Codex `/v1/responses`（含 stream、tool_choice、reasoning）不再 400；译成 Chat 再译回 SSE | `backend/compat/responses.py` `stream.py` |
| Chat 工具 | `tool_choice: {type:function,name}` → `auto` + 提示句。预填充期间 SSE 心跳，减少客户端掐线 | `backend/compat/sanitize.py` |
| Claude Code | 原生 `POST /v1/messages`。`ANTHROPIC_BASE_URL=http://127.0.0.1:8080`（不要 `/v1`） | `backend/compat/anthropic.py` |
| 目录 | Agents 增加 Grok.app；Claude 不再标「需 LiteLLM」 | `backend/integrations/agents.py` |

**验收重点**

1. pytest `test_compat.py`：Grok Responses 体不 400；function tool_choice → auto；Chat SSE 含 `output_text.delta` + `completed`。
2. Grok.app 选 Responses 或 Chat Completions 都能过工具轮，不再因 `function-specific tool_choice` 中断。
3. Claude Code 打 `/v1/messages` 得到 `tool_use` 或文本块。
4. 改网关后必须重启 8080（Quit Local AI.app 再开）。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → **58 passed, 1 skipped**（runtime 在跑时 skip 停机 503 用例）
- `cd frontend && npx vitest run` → **9 passed** · `pnpm build` → ok
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.4.0（ad-hoc Hardened Runtime，未公证）

### 0.0 · 2026-08-20 — v0.3.16 模型下载列表：排队、暂停续传、删除

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 列表 | Models 增加「下载」页。同时只跑一个传输，其余排队。半成品会从磁盘 `.part` / `.download-incomplete` 回填进列表 | `backend/models/pull.py` `data/downloads.json` |
| 暂停 / 继续 | 暂停 = 停传输并保留 `.part`（HTTP Range 续传）。继续 = 从断点接着下，或在忙时改排队 | `POST /api/models/pull/pause` `resume` |
| 删除 | 确认后删除库里的 `org/name` 文件夹。正在加载的 Target/Draft 必须先 Stop | `POST /api/models/delete` |
| 产品口径 | 旧「取消」等于暂停（保留文件）。从列表移除完成项不删文件。发现页下载中途再点会进队列，不再 409 | App `DownloadsPane` · Web `DownloadsTable` |

**验收重点**

1. 发现页对 A 下载中再点 B，B 出现在下载列表「排队」。
2. 暂停 A 后 `.part` 仍在，点继续从断点接着走。
3. 删除未完成项，文件夹从 `~/.lmstudio/models` 消失。
4. Runtime 正在跑的 Target 删除返回错误，提示先 Stop。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → 32 passed, 8 skipped
- `cd frontend && npx vitest run` → 9 passed；`pnpm build` → 通过
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.16 build 19

### 0.0 · 2026-08-20 — v0.3.15 API 模型名随主模型自动命名并可手改

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 自动名 | 设为 Target / 切换 Fast 配方 / 下载并指定 Target 时，若 `api.alias_auto`（默认 true）则把公开模型名写成规范短名：`Qwen3.8-27B-Heretic-8bit`、`Qwen3.8-27B-4bit` | `backend/core/alias.py` |
| 手动锁 | 总览 / API / Settings 的「模型」可编辑。保存后 `alias_auto: false`。点「恢复自动命名」解锁 | App `EditableAliasRow` · Web `AliasField` |
| 兼容 | Gateway 仍把任意请求 model 重写成已加载路径。Cursor 里还填着 `qwen3.8-27b-local` 也能用 | `backend/gateway.py` |

**验收重点**

1. 当前 Heretic Target 打开控制面后，API「模型」为 `Qwen3.8-27B-Heretic-8bit`，不是 `qwen3.8-27b-local`。
2. Models → 设为 Target（或切官方配方）后，未锁定时名称跟着变。
3. 改成自定义名并回车后，再切 Target 名称不变；点「恢复自动命名」后又跟着走。
4. `/v1/models` 的 id 等于当前 alias。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → 30 passed, 8 skipped
- `cd frontend && npx vitest run` → 9 passed；`pnpm build` 通过
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.15

### 0.0 · 2026-08-20 — v0.3.14 总览推理指标不再全是 —

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 现象 | Runtime / DFlash 显示运行中，但生成 tok/s、TTFT、接受率、预填充、RSS 全是 `—`。模型调用正常。内存 90GB 是本机 RAM，不是引擎 RSS | 总览卡 |
| 根因 | dflash-mlx 0.1.8 `/metrics`：推理中 `rates.average_decode_tok_s` 为 null、`recent_requests` 为空；真实值在 `current_request.decode_tok_s` / `acceptance_rate` / `ttft_s`、`rates.active_decode_tok_s`、`memory.rss_gb` | 实测 `GET :18080/metrics` |
| 修复 | 采样器按 0.1.8 字段回退；兼容旧 `average_decode_tok_s` + `recent_requests`。不造假：Safe 模式仍无 `/metrics` 则继续 `—` | `backend/monitoring/sampler.py` |
| Agent 未知 | 与指标无关。Gateway 只在 User-Agent / Referer 匹配 Cursor、Codex 等时标「已连接」。通用 OpenAI SDK 调用会一直「未知」 | `backend/gateway.py` `backend/integrations/agents.py` |

**验收重点**

1. Fast 模式正在生成时，总览「生成」为约 20 tok/s 量级数字，不是 `—`；TTFT / 接受率 / DFlash RSS 有值。
2. 生成结束后仍保留上一请求的 tok/s / 接受率 / TTFT（来自 `last_request` 或 `recent_requests`）。
3. 无需重装 App；重启控制面 8787 即可（不要 Stop 模型）。
4. Safe 模式仍显示 `—`。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → 28 passed, 8 skipped（runtime 8787/18080 当时未监听，集成项 skip）
- `test_dflash_metrics_inflight_uses_current_request` / `test_dflash_metrics_legacy_recent_requests` → 2 passed
- 未重装 App（采样器在 Python 控制面；下次拉起 8787 即生效）

### 0.0 · 2026-08-20 — v0.3.13 打开控制台 SIGABRT 修复

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 崩溃 | v0.3.12 右键开控制台：`EXC_CRASH (SIGABRT)`。线程 11 `user-initiated-qos.cooperative` 在 `NSSplitViewController _setupSplitView` / Auto Layout；主线程卡在 `NSHostingView.cancelAsyncRendering` | DiagnosticReports `LocalAI-2026-08-20-164033.ips` |
| 根因 | `NavigationSplitView`（以及 Models 的 `HSplitView`）在 SwiftUI 异步布局里于后台线程创建 AppKit SplitView，和主线程 layout 互锁 | `ConsoleView.swift` `PagesCore.swift` |
| 修复 | 控制台改为 `NavigationStack` + `HStack` 侧栏；Models / Discover 分栏同样改为 `HStack`+`Divider`。窗口在下一拍 `makeKeyAndOrderFront` | `LocalAIApp.openConsole` |

**验收重点**

1. 右键「控制台」打开窗口，不再闪退。
2. 左键 Popover → 控制台同样不崩。
3. Models 已安装 / 发现仍是表+右侧详情，只是分割条不可拖。
4. 侧栏隐藏（⌘⌃S）仍然有效。

**必检（本轮已跑）**

- `swift build` debug → Build complete
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.13

### 0.0 · 2026-08-20 — v0.3.12 状态栏右键菜单不再往下跳

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 根因 1 | `NSMenu.popUp` 锚在按钮上沿（`y = height+2`），菜单叠进系统菜单栏。高亮第一条「控制台」时 AppKit 把整块菜单往下推 | `LocalAIApp.swift` `showStatusMenu` |
| 根因 2 | 点「控制台」立刻 `AppActivation.enter()`（accessory→regular），菜单还在屏幕上，状态栏布局一变菜单就掉下来 | 同上 |
| 修复 | 锚在按钮下沿；菜单关掉后再执行打开控制台 / 拷贝 / 仪表盘 / 退出 | `pendingStatusAction` |

**验收重点**

1. 右键状态图标，菜单贴在图标正下方，高亮「控制台」位置不变。
2. 点「控制台」打开窗口，菜单先消失，不会整块挪到屏幕中间。
3. 左键仍是 Popover，不受影响。
4. 快捷键仍在 App 菜单（控制台开着时 ⌘L 等），右键菜单不再重复画 ⌘L。

**必检（本轮已跑）**

- `swift build` debug → Build complete
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.12

### 0.0 · 2026-08-20 — v0.3.11 模型下载断点续传

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 根因 | `huggingface_hub` 1.28 的 `snapshot_download(local_dir=)` 把半成品写成随机 `.incomplete`，失败还会删掉。断网、取消、Quit 后只能从头下 | `backend/models/pull.py` |
| 做法 | 按文件落到 `{name}.part`，用 HTTP `Range` 续传；已下完的文件按大小跳过。取消/报错/杀进程都保留 `.part` 与 `.download-incomplete` | `download_file_resumable` |
| UI | 未下完显示「继续下载」，已完成才灰掉下载按钮 | `Models.tsx` `PagesCore.swift` |

**验收重点**

1. 下载中途取消或断网，库目录里留下 `*.part`；再点「继续下载」从已有字节接着写，不重下已完成文件。
2. 完全退出 App 再打开，未完成条目仍可续传。
3. 下完后 `.part` 与 `.download-incomplete` 消失，模型可扫描到。
4. 不改 recipe、别名、库目录。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → 33 passed, 1 skipped
- `npx vitest run` → 9 pass；`pnpm build` 通过（`index-JAmodCtR.js`）
- `swift build` debug → Build complete
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.11

### 0.0 · 2026-08-20 — v0.3.10 Discover 下载误禁 + 推荐列表

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 下载变灰 | HF 把 Qwen3.6-27B-MLX 标成 `image-text-to-text`，`classify()` 当成视觉模型禁下。现只拦真正的 VL：`mmproj`/`model-vision`、仓库名含 `-vl-`/`vision`、硬视觉 pipeline。统一 LLM 可下，文案提示「只跑文本」 | `backend/models/hub.py` `Models.tsx` `PagesCore.swift` |
| 空 Discover | 空查询立即拉推荐（无 320ms debounce），列表上方「本机推荐」 | `Models.tsx` `AppStore.swift` |
| 真 VL 仍禁 | `Qwen3-VL` + `model-vision.safetensors` 仍 `unusable/vision` | `backend/tests/test_core.py` |

**验收重点**

1. 搜 `Qwen3.6-27B-MLX-4bit`，「下载」可点，不再「此处不能运行」。
2. 搜 `Qwen3-VL` 仍灰、仍提示视觉不支持。
3. Discover 不输入时出现配方 Target/Draft + 热门 MLX（不是空白）。
4. **必须完全退出 Local AI.app 再打开**（加载新 `hub.py`），浏览器 Models 页强制刷新（新 `frontend/dist`）。
5. 不改 recipe、别名、库目录。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → 28 passed, 1 skipped
- `npx vitest run` → 9 pass；`pnpm build` 通过（`index-5nc9xlUP.js`）
- `swift build` debug → Build complete
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.10

### 0.0 · 2026-08-20 — v0.3.9 Discover 搜索修复（huggingface_hub 1.x）

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 根因 | `huggingface_hub` 1.28 的 `list_models` **不再接受 `direction=`**。Discover 每次搜索 502，「模型操作失败」，列表空 | `backend/models/hub.py` |
| 推荐 | 空查询先列出配方 Target/Draft（Heretic + 官方），再补热门 MLX | `Models.tsx` `AppStore.swift` `hub.recommended_repo_ids` |
| 文案 | 空列表说明改为「热门 MLX」，有结果时不再盖「没有匹配」 | i18n / `Localizable.strings` |

**验收重点**

1. Discover 不输入时出现热门 MLX 列表（不是空白）。
2. 搜 `qwen` 有结果，红条「模型操作失败」消失。
3. 搜精确 id `mlx-community/Qwen3.8-27B-4bit` 仍可点进详情。
4. 必须重启控制面（Quit App 再打开，或重启 8787）才会加载新 `hub.py`。
5. 不改 recipe、别名、库目录。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → 21 passed, 8 skipped
- `npx vitest run` → 9 pass；`pnpm build` 通过
- `swift build` debug → Build complete
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.9
- 本机直连：`search_hub("qwen")` 有结果；空查询第一条是 Heretic Target

### 0.0 · 2026-08-20 — v0.3.8 无障碍 + 公证脚本（Phase 6–7）

| 主题 | 说明 | 关键文件 |
|---|---|---|
| Reduce Transparency / 对比度 | 横幅与代码底在「降低透明度」或增强对比时改用不透明填充 + 描边，不用淡透明度 | `Theme.swift` `ToneBackdrop` `CodeBackdrop` |
| VoiceOver | 菜单栏 extra：名称是 Local AI，值是状态。Start/Stop/Copy 有 hint。EmptyState 有按钮时不 combine（按钮可单独聚焦）。Logs 行读出 Error/Warning 前缀，不只靠颜色 | `LocalAIApp.swift` `StatusPopover.swift` `PagesMore.swift` |
| 键盘 | 打开 Popover 时 `NSApp.activate()` 以便 Return/Tab。降低动态效果时 Popover 不动画。辅助文字尺寸下 Popover 加宽到 380 | `LocalAIApp.swift` `StatusPopover.swift` |
| 公证 | 独立 `scripts/notarize.sh`；`build_app.sh` 在有 Developer ID 时调用。无证书仍 ad-hoc，不假装已公证 | `scripts/notarize.sh` `scripts/build_app.sh` |
| 图标 | 仍为单层 icns。有 Xcode + `Support/AppIcon.icon` 时才提示编译 Tahoe 分层图标 | `scripts/build_app.sh` |

**验收重点**

1. VoiceOver：菜单栏 extra 报「Local AI，Running/Stopped…」；点开后能听到 Start 的 hint，能单独落到 First Run 的按钮。
2. 系统设置打开「降低透明度」后，错误横幅和日志底是实底+描边，不是淡色玻璃。
3. 全键盘：Popover 打开后 Return 能 Start（控制面已通且未运行时）。
4. `bash scripts/notarize.sh` 在无 Developer ID 时退出码 2，不把 ad-hoc 包说成已公证。
5. 不改 `/api`、recipe、别名、库目录契约。不加 App Sandbox。

**必检（本轮已跑）**

- `swift build` debug → Build complete
- `bash scripts/notarize.sh` → exit 2（无 Developer ID，不假装公证）
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.8 build 12，`adhoc,runtime`，未公证

### 0.0 · 2026-08-20 — v0.3.7 Models 检查器 + 拖放换库 + Help 三件事（Phase 4–5）

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 已安装表 | 可选择、可排序。右侧页内检查器（不是 `.inspector`，避免撑窗）。Return 在格式允许时设 Target/Draft。VoiceOver 行操作：设角色 / 显示文件夹 / 拷贝 id | `PagesCore.swift` `AppStore.swift` |
| Discover | Hugging Face 搜索与排序进 Console 工具栏，左栏只剩列表 | `ConsoleView.swift` |
| 拖放 | 文件夹拖到 Models 页或 Settings General 的库行 → 与选文件夹同一 API。不会因为 HF 缓存自动换库 | `Theme.swift` `LibraryDropCatcher` |
| Settings | 库目录从 Advanced 挪到 General；Settings 窗口关掉缩放按钮 | `PagesMore.swift` `LocalAIApp.swift` |
| Help | 三件事：Start、拷贝 API、打开控制台。README 仍是次要按钮 | `Theme.swift` HelpView |
| 菜单 | File → 在 Finder 中显示模型库 | `LocalAIApp.swift` |

**验收重点**

1. Console → Models：点一行右侧出现详情；Return 设角色；窗口外框尺寸不变。
2. Discover 搜索框在工具栏，不在内容顶栏。
3. 把本机文件夹拖到 Models 或 Settings General 才换库；不拖不点选则路径不变。
4. Help（⌘?）只有三件事 + README，不是整篇 README 正文。
5. 不改 `/api`、recipe、别名、默认库路径契约。

**必检（本轮已跑）**

- `swift build` debug → Build complete
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.7 build 11，`adhoc,runtime`，未公证

### 0.0 · 2026-08-20 — v0.3.6 菜单栏 HIG Phase 1–3（template 图标 / 瘦 Popover / Console 工具栏）

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 分发 | 目标仍是 **公证的 Developer ID**，不加 App Sandbox（与 launchd / venv / HF 下载冲突） | `scripts/build_app.sh` `Info.plist` |
| 状态项 | 菜单栏改为 **template SF Symbol**（idle `cpu` / starting `clock.arrow.circlepath` / running `cpu.fill` / warn 三角 / error 八角）。状态靠字形，不是色点。Combine 订阅 `$runtime`+`$backendReachable`，去掉 2s 盲刷 | `StatusIcon.swift` `LocalAIApp.swift` |
| About | App 菜单 About 走系统 `orderFrontStandardAboutPanel`；Settings 仍保留 About 页 | `LocalAIApp.swift` |
| 窗口标题 | Console `NSWindow.title` = 当前页（Overview/Models/…），不再写死「Local AI」 | `LocalAIApp.swift` `ConsoleView.swift` |
| Popover | 保留状态、指标、Start **或** Stop、Safe⇄Fast、Copy/Console。去掉语言切换、生命周期长文、Restart（Restart 在 Console 工具栏与 Runtime 菜单） | `StatusPopover.swift` |
| Console | 工具栏用 SF Symbol Label（Start/Stop/Restart）；Models 筛选/Rescan 与 Logs 搜索进工具栏（**不用** `.searchable`，避免撑窗）。File 打开控制台/仪表盘；Edit 拷贝 API；Runtime 只留启停重启 | `ConsoleView.swift` `PagesCore.swift` `PagesMore.swift` |
| Theme | 补 `Radius`/`Stroke`；`KVRow` 竖向 padding 改 `Space.sm`；状态行用 `StatusGlyph` 而不是纯色点 | `Theme.swift` |

**验收重点**

1. 浅色/深色菜单栏下状态图标随系统着色；停/启/跑/不健康/控制面掉线是 **不同符号**，不是只靠颜色。
2. 点 About 出现系统关于面板（版本 0.3.6 / build 10），不是跳进 Settings。
3. Console 切到 Models / Logs 时窗口标题跟着变；窗口外框尺寸不变。
4. Popover 没有语言选择和 Restart；Settings 仍可改语言。Start / Stop / Copy API / Models 流程不变。
5. 不改 `/api`、recipe、别名 `qwen3.8-27b-local`、库目录契约。

**必检（本轮已跑）**

- `swift build` debug → Build complete（1.91s；仅既有 LoginItem DEBUG warning）
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.6 build 10，`adhoc,runtime`，未公证（本机无 Developer ID）

### 0.0 · 2026-08-20 — v0.3.5 Hugging Face 发现 + 下载到 LM Studio 目录

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 产品 | Models 分「已安装 / 发现」。发现页左搜右详，只把 MLX 标成可跑；GGUF/Vision 可见但不可下 | `frontend/src/pages/Models.tsx` `PagesCore.swift` |
| 落盘 | 下载写入库目录 `{library}/{org}/{name}`，与 LM Studio 命名对齐。默认 `~/.lmstudio/models`。**不**把安装位置设成 `~/.cache/huggingface/hub` | `backend/models/pull.py` `backend/models/registry.py` |
| 换目录 | 手动：App 用系统文件夹对话框；Web 粘贴路径。只替换主库，HF hub 仍作额外扫描 | `POST /api/models/library` |
| API | `GET /api/models/search` · `GET /api/models/hub?id=` · `POST/GET /api/models/pull` · `POST /api/models/pull/{pause,resume,dismiss,cancel}` · `POST /api/models/delete` · `GET/POST /api/models/library` | `backend/api/routes.py` `backend/models/hub.py` |
| 配方缺口 | DFlash/Settings missing 可跳到 Discover 并预填 repo id | `DFlash.tsx` `PagesDFlash.swift` |

**验收重点**

1. Discover 搜 `mlx-community/Qwen3.8-27B-4bit` 显示 Target 候选；GGUF 显示不可运行且 Download 禁用。
2. 点下载后文件出现在 `~/.lmstudio/models/{org}/{name}`，Rescan 后出现在已安装。
3. 换库必须点「选择文件夹」或粘贴路径；不会因为 HF 缓存里有模型就改主库。
4. 官方配方 missing → 「去发现页下载」打开 Discover 并带上该 id。
5. 别名 `qwen3.8-27b-local` 与 8080 不变。禁止 `pip install dflash`。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → 26 passed, 1 skipped
- `npx vitest run` → 9 pass；`pnpm build` 通过
- `swift build` debug → Build complete
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.5

### 0.0 · 2026-08-20 — v0.3.4 双配方 Heretic / 官方 DFlash 2

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 产品 | Settings 可切换 Fast 配方，默认 Heretic。官方 DFlash 2 = `mlx-community/Qwen3.8-27B-4bit` + `z-lab/Qwen3.8-27B-DFlash2`。Agent 别名不变 | `backend/runtime/recipes.py` |
| 引擎真相 | 本机 Fast 是 **dflash-mlx 0.1.8**，不是上游 z-lab 源码。官方 PyPI `dflash` 0.1.0 会抢走 `dflash` 命令且没有 `serve` | `mlx_provider.py` |
| CLI 旗标 | `--block-size` / `--draft-bits` 仅当 `dflash serve --help` 声明才传入。否则写入配方意图并在 UI 标明 | `recipes.serve_flags` |
| API | `GET /api/recipes` · `POST /api/recipes/activate` · `GET /api/dflash` 带 `recipe_id`/`generation`/`missing`/`engine` | `backend/api/routes.py` |
| UI | Web Settings + DFlash；App Settings Runtime + DFlash 页同步 | `Settings.tsx` `DFlash.tsx` `PagesMore.swift` `PagesDFlash.swift` |

**验收重点**

1. 新开 Settings，Fast 配方默认 Heretic；切到官方后 Target/Draft 变成官方 ID，再切回 Heretic 恢复。
2. 官方模型未下载时出现 missing 提示，不假装已经能跑。
3. `dflash serve` 命令行不含未声明的 `--block-size`。
4. **不要** `pip install dflash`。
5. `pytest -q` 22 pass 1 skip；`npx vitest run` 9 pass；`pnpm build`；`swift build` 通过。

**必检（本轮已跑）**

- `.venv/bin/python -m pytest -q` → 22 passed, 1 skipped
- `npx vitest run` → 9 pass；`pnpm build` 通过
- `swift build` debug → Build complete
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.4

### 0.0 · 2026-08-20 — v0.3.3 App 与 Web 中英界面真正可用

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 产品契约 | 跟随系统（macOS / 浏览器语言含 `zh*` → 简体中文）；可在 Popover / Settings / Web 侧栏手动选 简体中文 或 English。选过的写入 `ui.language`，App 与 Web 对齐 | `L10n.swift` `frontend/src/i18n/` |
| App 根因 | 词条早已有中文，但 `system` 走 `Bundle.main`，development region 是 en，中文 Mac 仍可能整页英文。且切语言后 Console hosting 不刷新 | `L10n.swift` `LocalAIApp.swift` |
| App 修复 | 显式加载 `zh-Hans.lproj` / `en.lproj`；语言变更通知刷新 Popover + Console/Help `rootView` | `AppStore.setLanguage` `HostedWindow` |
| Web | 原先全部写死英文。现 `en`+`zh-Hans` 词表 + `I18nProvider`；十页 chrome 走 `t()`；侧栏与设置可选语言 | `frontend/src/i18n/catalog.ts` `App.tsx` `pages/*` |
| API | `PUT /api/settings` 允许 `ui` 段（`language`: `system`/`en`/`zh-Hans`） | `backend/api/routes.py` |

**验收重点**

1. 系统语言为简体中文时，新装/默认「跟随系统」的 App 与 Web 应为中文，不必先翻设置。
2. Popover 或 Settings 切到 English / 简体中文，菜单栏、Console、Web 侧栏立即跟着变（Web 需控制面已启动以便写入 yaml）。
3. `npx vitest run` 9 pass；`pnpm build` 通过；`bash scripts/build_app.sh` 通过。
4. 模型别名、curl、日志原文、API 错误详情保持原样，不翻译用户数据。

**必检（本轮已跑）**

- `swift build` debug → Build complete
- `npx vitest run` → 9 pass；`pnpm build` 通过
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.3，含 `en.lproj` 与 `zh-Hans.lproj`

### 0.0 · 2026-08-20 — v0.3.2 Console 切页不再把窗口上下撑开

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 根因 | `NSHostingController` 默认 `sizingOptions` 跟随 SwiftUI 固有高度；Models 的 `Table`、Logs 的长列表会把 `NSWindow` 顶高。Models/Logs 上的 `.searchable` 切页时突然插入工具栏，窗口再被撑一截 | `LocalAIApp.swift` `HostedWindow` |
| 窗口所有权 | Console/Help 的 hosting `sizingOptions = []`，垂直 hugging 用 `windowSizeStayPut`，最小尺寸只走 `contentMinSize` | `LocalAIApp.swift` |
| 页内滚动 | Table / Logs `ScrollView` 吃剩余高度，不再按行数报告理想高度。去掉与页内搜索框重复的 `.searchable` | `PagesCore.swift` `PagesMore.swift` `PagesDFlash.swift` `ConsoleView.swift` |
| 旧窗体 | autosave 改为 `LocalAIConsole.v2`，避免沿用被 bug 撑过的巨大 frame | `LocalAIApp.swift` |

**验收重点**

1. 打开 Console，记下窗口高度 → 点 Models / Logs / Benchmark / Agents，窗口外框高度不变，内容在窗内滚动。
2. 用户拖过的尺寸仍可拖；关掉再开走新 autosave 默认 980×680（或用户新拖的尺寸）。
3. `bash scripts/build_app.sh` 通过；API/生命周期契约未改。

**必检（本轮已跑）**

- `swift build` debug → Build complete
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.2，`adhoc,runtime`

### 0.0 · 2026-08-20 — v0.3.1 会话生命周期：Quit 默认释放 8787/8080

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 产品契约 | 打开 App = 会话开始；Start/Stop 只管模型；默认 Quit = 停模型 + 控制面 + 网关。可选「退出后保持 API」给 Agent 常驻场景 | `LocalAIApp.swift` `PagesMore.swift` |
| 根因 | 旧 LaunchAgent `RunAtLoad=true` + KeepAlive，Quit 只关菜单栏，8787 被 launchd 继续拉起 | `backend/services/launchd.py` `ServiceSupervisor.swift` |
| 退出路径 | `applicationShouldTerminate` → 有模型则确认 → `bootout` 双 label → SIGTERM/KILL 18080/8787/8080。关闭 Console 窗口不退出 App | `LocalAIApp.swift` |
| Force Quit | 会话看门狗（`~/Library/Application Support/Local AI/session-watch.sh`）在 App PID 消失且无 keep 标记时同样清理 | `ServiceSupervisor.startSessionWatchdog` |
| 旧安装 | 启动时把已装 plist 的 `RunAtLoad` 改成 false，避免下次登录无界面占端口 | `neutralizeLoginOrphans` |
| 文案 | Popover 区分 Stop vs Quit；Web Settings 不再写「登录后常驻 dashboard」 | `Localizable.strings` `frontend/src/pages/Settings.tsx` |

**验收重点**

1. 默认设置下：打开 `dist/Local AI.app` → 右键 Quit → `lsof -iTCP:8787 -sTCP:LISTEN` 与 8080 / 18080 均无 LISTEN。
2. Settings 打开「退出后保持 API」再 Quit → 8787 仍在；再打开 App 后关掉该开关再 Quit → 端口释放。
3. 模型正在跑时 Quit 出现三按钮：退出并停止 / 退出但保持 API（一次性，不写进偏好）/ 取消。
4. 登录项只启动菜单栏 App；`RunAtLoad` 为 false。`swift build` 与 `bash scripts/build_app.sh` 通过。
5. Python `/api` 与 Runtime 契约未改。

**必检（本轮已跑）**

- `swift build` debug → Build complete
- `bash scripts/build_app.sh` → `dist/Local AI.app` v0.3.1，`codesign` flags `adhoc,runtime`，未公证
- 打开 App（模型 `stopped`）后 `kill -TERM` 模拟 Quit → 1s 内进程退出；`lsof` 8787/8080/18080 无 LISTEN；`launchctl print gui/501/com.localai.controlcenter.{backend,gateway}` 均 not found；2s 后端口仍空
- `pnpm build`（frontend Settings 文案：launchd 不再声称登录常驻）

### 0.0 · 2026-08-20 — v0.3.0 菜单栏 App 产品体验升级（非业务重写）

| 主题 | 说明 | 关键文件 |
|---|---|---|
| Design tokens | 系统语义色 + 4/8/12/16/24 间距；禁止自定义蓝紫与 Card 堆叠 | `Theme.swift` `L10n.swift` |
| 中英界面 | `en` / `zh-Hans` strings；Settings 可跟随系统或强制语言 | `Support/en.lproj/` `Support/zh-Hans.lproj/` |
| 命令模型 | App / Runtime / View / Help 菜单；⌘⇧R Start、⌘⇧K Stop（不占用 ⌘.） | `LocalAIApp.swift` |
| Settings 单入口 | 侧栏去掉 Settings；⌘, TabView：General / Runtime / Services / Advanced / About | `PagesMore.swift` `SettingsRoot` |
| Popover IA | 一眼状态+三指标+单一主按钮；Quit 仅右键/App 菜单；fittingSize | `StatusPopover.swift` |
| Console IA | 分组 sidebar（Control/Decode/Integrate/Observe）；Form vs 满宽 Table | `ConsoleView.swift` `PagesCore.swift` |
| Empty/Error/A11y | First Run、空表、错误 What/Why/Retry；状态不只靠颜色；Reduce Motion 关掉 sparkline | `Theme.swift` `MonitoringPage` |
| 项目路径 | 从 .app 向上搜 `backend/main.py` + Locate…；删除硬编码用户目录 | `ServiceSupervisor.swift` |
| 发布门禁 | Hardened Runtime、`PrivacyInfo.xcprivacy`、entitlements、版本从 Bundle 读；无 Developer ID 则 ad-hoc **未公证** | `Support/LocalAI.entitlements` `scripts/build_app.sh` |

**验收重点**

1. `bash scripts/build_app.sh` 通过；`codesign` flags 含 `runtime`；无 Developer ID → ad-hoc，文档禁止写「已公证」。
2. 进程冒烟存活；Popover 不再把 Quit 与 Start 并列。
3. Console 侧栏 4 组、无 Settings 项；设置只在 ⌘,。
4. 系统/设置语言切中英后菜单、Popover、侧栏走 strings（`L10n.bundle`）。
5. Python API / Runtime / `config.yaml` 契约未改。

### 0.1 · 2026-08-20 — v0.2.0 原生菜单栏 Local AI.app

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 菜单栏客户端 | oMLX 式 NSStatusItem + NSPopover；LSUIElement；彩色状态灯（非 template） | `apps/LocalAIApp/Sources/LocalAI/LocalAIApp.swift` `StatusPopover.swift` `StatusIcon.swift` |
| Console 10 页 | Overview / Models / Runtime / DFlash / API / Benchmark / Agents / Monitoring / Logs / Settings | `ConsoleView.swift` `PagesCore.swift` `PagesDFlash.swift` `PagesMore.swift` |
| API 客户端 | 直连 8787；超时 330s 覆盖模型加载；Reachable 探测 `/api/health` | `APIClient.swift` `Models.swift` `AppStore.swift` |
| 监督与通知 | 8787 宕机 kickstart；回退 Safe / 就绪 / 内存 / 低接受率通知 | `ServiceSupervisor.swift` `Notifier.swift` |
| 登录项 | `SMAppService.mainApp`（Debug 构建故意不注册） | `LoginItem.swift` |
| 打包 | SwiftPM release + 生成 icns + ad-hoc 签名；`dist/` gitignore | `scripts/build_app.sh` `apps/LocalAIApp/Package.swift` |
| CLI | 新增 `local-ai app` 打开已构建的 `.app` | `cli/local_ai.py` |

**验收重点**

1. `bash scripts/build_app.sh` → `dist/Local AI.app`；`codesign --verify` 通过（ad-hoc）。
2. `open "dist/Local AI.app"` 后进程存活；菜单栏出现 Local AI（无 Dock 图标）。
3. 控制面 `GET /api/health` = 200 时 popover 能显示 runtime 状态（本轮实测 backend 200、App pid 存活；未加载 27B 以免占内存）。
4. App 不替代三平面：停 App ≠ 停 Gateway。
5. 仅 Command Line Tools 时禁止 `@State`/`@AppStorage`（缺 `SwiftUIMacros.dylib`），UI 状态放 `AppStore` 的 `@Published`。

### 0.2 · 2026-08-20 — v0.1.0 首版完整交付

| 主题 | 说明 | 关键文件 |
|---|---|---|
| 环境审计 | M5 Max/128GB、工具链、模型资产、端口占用全記錄 | `docs/ENVIRONMENT-AUDIT.md` |
| 配置/状态核心 | YAML 单源配置 + 原子写跨进程状态 | `backend/core/config.py` `backend/core/state.py` |
| 模型注册表 | 扫描 LM Studio/HF 缓存，识别 DFlash draft，8 模型入库 | `backend/models/registry.py` |
| MLX Runtime | fast=dflash serve / safe=mlx_lm server，分离进程+300s 启动等待+日志轮转 | `backend/runtime/mlx_provider.py` |
| 看门狗/回退 | fast 崩溃自动回退 safe；接受率<25%持续 2min 提示 | `backend/runtime/manager.py` |
| 推理网关 | 8080 是协议适配层：别名重写、Responses/Anthropic 翻译、Chat sanitize、SSE 心跳、结构化 503、Agent UA（含 grok） | `backend/gateway.py` `backend/compat/` |
| 监控采样 | psutil+sysctl 内存压力+dflash /metrics，SSE 推送，Swap 告警 | `backend/monitoring/sampler.py` |
| Benchmark 引擎 | Quick/A-B/AutoTune/ToolProbe，真实测量，历史入 SQLite | `backend/benchmark/engine.py` `prompts.py` |
| Control API | /api 全套路由（runtime/models/dflash/recipes/benchmark/agents/monitor/logs/settings/service） | `backend/api/routes.py` `backend/main.py` `backend/runtime/recipes.py` |
| 前端 10 页 | 暖中性+单 accent+语义色，Apple Settings 式 kv 行，SSE 实时 | `frontend/src/pages/*` `styles/global.css` |
| CLI+脚本 | local-ai 七命令；start/stop/restart/healthcheck/benchmark/install.sh | `cli/local_ai.py` `scripts/` |
| launchd | backend+gateway 双服务 KeepAlive；模型不随登录加载 | `backend/services/launchd.py` `launchd/*.plist` |
| TCC 迁移 | Desktop→~/AI（launchd exit 78 根因），工作区留符号链接，venv 重建 | 本文档 §排障 |
| 测试 | pytest 22 项（单元+活体集成）+ Vitest 9 项（含 i18n resolveLang） | `backend/tests/` `frontend/src/i18n/catalog.test.ts` |

**验收重点（全部已实测通过）**

1. `local-ai status` → backend/gateway/runtime 三绿。
2. Web Overview：Running · 内存/速度/TTFT 实时；Stop/Start/Restart 状态真实。
3. Safe/Fast 切换不改 Agent 配置，公共端点不变。
4. DFlash A/B 实测：短代码 1.49×（接受率 68%）、SwiftUI 长代码 1.07×（48.6%）——draft 仅训练 10k/60k 步，域差异真实存在。
5. Tool Calling Probe：标准 `tool_calls` + 合法 JSON + finish_reason=tool_calls。
6. **OpenCode 端到端**：读 calc.py→补 multiply/修 divide→跑 pytest→3 passed（40 秒，全程本地模型）。
7. 控制面被 kill，推理进程存活且 Gateway 继续服务；重启后自动重挂接。
8. `pytest -q` 19 pass 1 skip（skip=运行时在跑时的停机错误路径，正常）；`vitest run` 4 pass；`pnpm build` 通过。

## §1 架构与模块

见 README「Architecture」。模块索引：

| 目录 | 职责 |
|---|---|
| `backend/core/` | config（YAML 单源+原子写）、state（跨进程状态） |
| `backend/runtime/` | base（Provider 抽象）、mlx_provider（spawn/stop/health）、manager（watchdog/failover/单例） |
| `backend/gateway.py` | 独立进程：Agent 协议适配（Responses / Chat sanitize / Anthropic messages）+ 统计 + 结构化错误 |
| `backend/models/` | registry 扫描 + hub 发现/分类 + pull 落到 LM Studio 库目录 |
| `backend/benchmark/` | prompts（固定集）+ engine（JobManager 单任务队列） |
| `backend/monitoring/` | sampler：2s 采样 ring buffer + SSE 订阅 + 内存安全 |
| `backend/integrations/` | agents：Cursor / Codex / OpenCode / Cline / Roo / Grok / Claude Code 配置 + 连通性实测 |
| `backend/services/` | logs（分类降噪读取）、launchd（plist 生成/装卸） |
| `backend/api/routes.py` | 全部 /api 路由 |
| `frontend/src/` | pages 10 页 / i18n（en+zh-Hans）/ components/ui.tsx 原语 / hooks（usePoll+useMetricsStream） |
| `apps/LocalAIApp/` | 原生菜单栏 App（v0.3.8：无障碍 + 公证脚本；检查器/拖放见 v0.3.7） |
| `scripts/build_app.sh` | release 构建 + icns + 签名 → `dist/Local AI.app`；公证走 `scripts/notarize.sh` |

## §2 数据契约

- `data/downloads.json`：下载队列账本（`repo_id` / `status` / `queue`）。暂停保留 `.part`；崩溃中的 `running` 重启后回填为 `paused`。API：`POST/GET /api/models/pull`，`POST /api/models/pull/{pause,resume,dismiss}`，`POST /api/models/delete`。旧 `cancel` = 暂停。
- `runtime_state.json`：`status/mode/pid/internal_port/alias/target_*/draft_*`——Gateway 与 Backend 都读它，写必须走 `write_state`（tmp+rename）。
- SQLite `data/lacc.db`：models / benchmark_runs / runtime_events / agent_connections / settings_kv。默认不存 prompt 正文。
- dflash `/metrics`（dflash-mlx 0.1.8）：推理中读 `current_request.{decode_tok_s,acceptance_rate,ttft_s}` 与 `rates.active_decode_tok_s`、`memory.rss_gb`；`rates.average_decode_tok_s` 与 `recent_requests` 在请求结束前经常为空。旧字段仍作回退。映射见 `runtime_fields_from_dflash`。
- 公开模型名：`api.alias` + `api.alias_auto` + `api.alias_source`。自动名由 `pretty_alias(target)` 生成。Gateway `/v1/models` 列出 alias（及 Target id）。请求体里的 model 一律重写成已加载路径。
- **流式思考字段差异**（踩过的坑）：dflash=`delta.reasoning_content`，mlx_lm=`delta.reasoning`——计 token 两个都要认。
- **Agent 协议**：网关把 `/v1/responses`、`/v1/messages` 译成上游 `/v1/chat/completions`。`tool_choice` 函数指定降为 `auto`。`previous_response_id` 进程内最多记 32 条，**流式回合必须连 `tool_calls` 一起记**。心跳 `: keepalive` 每 15s，且不得取消上游 `aiter_bytes`。Claude Code/CodeG：规范化 path 里的 `?beta=true` 与双斜杠；提供 `/v1/messages/count_tokens` 与 `/api/hello`；**流式完成前不放引擎锁**；把后置 `system` 折到开头。契约见 `backend/tests/test_compat.py`、`test_gateway_http.py`、`test_agent_loop.py`。

## §3 排障

| 现象 | 根因/处理 |
|---|---|
| launchd exit 78 | TCC 拦 Desktop/Documents。项目必须在 ~/AI；重装：`backend.services.launchd.install()` |
| 503 runtime_unavailable | 正常保护路径，响应含 how_to_fix；Start 即可 |
| A/B safe 腿 0 token | 已修（reasoning 字段差异，见 §2）；同类问题先抓原始 SSE 看 delta 键名 |
| mv 卡死 | Desktop→~/AI 用 `rsync -a --exclude .venv --exclude node_modules`，venv 必须重建（shebang 绝对路径） |
| 8787/8080 被占 | `lsof -tiTCP:8787 -sTCP:LISTEN`；launchd 与手动进程勿并存 |
| 模式切换后页面数字不动 | 前端 usePoll 5-6s 周期；SSE 只有 Fast 模式有 runtime 字段 |
| swift build 编到错误产物 / SwiftUI 宏失败 | 必须 `scripts/build_app.sh`（显式 `--package-path` + `--scratch-path`）。CLT 无 `SwiftUIMacros`，勿用 `@State` |
| 菜单栏 App 状态全 idle 且 lastError 解码失败 | 对照 `Models.swift` 与 `/api/health`、`/api/runtime/status` 的 snake_case 字段；多余键可忽略，缺 required 会整轮 tick 失败 |
| 界面仍是英文 | App：包内须有 `zh-Hans.lproj`，且走 `L10n` 显式加载（不要只靠 Bundle.main）。系统为 `zh*` 时「跟随系统」应为中文。语言覆盖只在 **Settings**（Popover 不再放语言选择）。Web：侧栏底部选语言；浏览器 `zh*` 默认中文 |
| Console 切页窗口被上下撑开 | SwiftUI 固有尺寸驱动了 NSWindow。v0.3.2 起 hosting `sizingOptions=[]`；若仍巨大，确认 autosave 名为 `LocalAIConsole.v2`。Models 检查器用页内 `HStack` 分栏，禁止 `.inspector`、`.searchable`、`HSplitView`、`NavigationSplitView` |
| 8787 在 Quit 后仍 LISTEN | 旧 KeepAlive job 未 bootout，或打开了「退出后保持 API」。再开一次新版 App 后默认 Quit；`launchctl bootout gui/$(id -u)/com.localai.controlcenter.backend` |
| 切到官方 DFlash 2 起不来 | 先确认 Target/Draft 都已完整下载并扫描。引擎必须是固定 commit `60803233`（包版本 0.1.10）；`dflash doctor` 与 `dflash models` 应同时通过并列出 Qwen3.8。禁止 `pip install dflash` 覆盖 serve |
| Discover 搜索 502 / 没有推荐 | `huggingface_hub` 1.x 禁止 `list_models(direction=)`。空查询也会拉热门 MLX。改完必须重启 8787 |
| 下载中断后从头开始 | v0.3.11 起半成品是 `{file}.part`。v0.3.16 用下载列表暂停/继续；删除才会清文件夹 |
| 下载列表没有半成品 | 控制面要读得到库目录。崩溃中的 running 会回填为 paused。重启 8787 |
| Grok/Codex 开始正常随后 Agent 退出 | 旧网关把 `/v1/responses` 原样转给 dflash（400），Chat 的 function `tool_choice` 也被拒。v0.4.0 在网关翻译。必须重启 **8080**。心跳不得 `wait_for` 取消上游读，否则预填充 >15s 会丢 chunk |
| CodeG/Claude CLI「模型不存在」或 HTTP 503 连打 | Claude 把 **HTTP 404** 一律说成模型不存在。① `?beta=true` 打进 path（v0.4.1 已规范化）；② 27B 刚 Start（网关重试并改 503）；③ CodeG 并行第二路在第一路 prefill 时打进来（v0.4.2 锁覆盖整段 SSE）；④ Claude 在 user 后再发一段 system，Qwen 拒绝（v0.4.2 合并到开头）。改网关后只重启 8080。CodeG 请 **新建会话**，不要接着失败的旧回合 |
| 右键状态栏菜单往下跳 | 旧代码 `popUp` 锚在按钮上沿，且打开控制台会立刻切 `.regular`。v0.3.12 锚下沿并等菜单关闭再执行动作 |
| 右键打开控制台闪退 SIGABRT | `NavigationSplitView` 后台 Auto Layout。v0.3.13 改 `HStack` 侧栏，禁止 SplitView |
| 总览运行中但 tok/s / TTFT / 接受率全是 — | dflash 0.1.8 字段变了。v0.3.14 起读 `current_request`。改完必须重启 8787（不要 Stop 18080）。Agent「未知」= UA 未匹配，不是指标坏了 |
| API「模型」不跟主模型变 | 已手动锁定（`alias_auto: false`）。点「恢复自动命名」。新代码在 `backend/core/alias.py`，须重启 8787；App 须 v0.3.15 才有可编辑框 |
| 菜单栏图标在深色菜单栏上看不清 / 只会变色点 | v0.3.6 起必须是 template SF Symbol（`isTemplate = true`）。禁止再画非 template 位图+彩点。状态靠 `cpu` / `cpu.fill` / 时钟 / 三角 / 八角 |
| Console 标题一直是 Local AI | 必须写 `NSWindow.title = store.consolePage.title`；只设 `.navigationTitle` 不够 |
| Gatekeeper 拦 ad-hoc | 本机无 Developer ID 时未公证；右键打开。有证书后：`bash scripts/build_app.sh && bash scripts/notarize.sh`（profile `local-ai-notary` 或 `$NOTARY_PROFILE`）。本产品 **不做** Mac App Store Sandbox |

## §14 变更映射表

| 变更类型 | 必须更新 |
|---|---|
| Runtime/引擎参数 | §0 + §1 + README「DFlash」+ `mlx_provider._build_command` 的 pytest 用例 |
| API 契约（/api 或 /v1） | §0 + §2 + `backend/tests/test_api.py` + 前端 `api/client.ts` 类型 |
| 前端页面/视觉 | §0 + §1 模块表 + 截图验收（playwright screenshot） |
| 模型下载队列 | §0 + §2 `downloads.json` + README「当前模型」+ App `DownloadsPane` |
| 模型/别名/目录 | §0 + 速查表 + README「当前模型」 |
| launchd/CLI/脚本 | §0 + §3 + README「常驻服务」 |
| 原生 macOS 菜单栏应用 | §0 + 速查表 + README「macOS 应用」+ `apps/LocalAIApp/` + `scripts/build_app.sh` |
| Benchmark 口径 | §0 + §2 + README「Benchmark」（禁止改动固定 prompt 而不记录） |
| Agent 协议（Responses / Anthropic） | §0 + §2 + README「Agent 接入」+ `backend/tests/test_compat.py` |
| 仅文档 | §0 记「文档维护」 |

---
上次结构化更新：2026-08-21 · DFlash2 staging（引擎完成，模型与真机 A/B 进行中）

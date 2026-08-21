# Local AI Control Center

Apple Silicon 本地大模型 Runtime + Agent Gateway + Speculative Decoding 管理后台。

打开菜单栏 **Local AI.app**（或浏览器 <http://127.0.0.1:8787>）→ 点击 Start → Agent 直接使用本地模型。不需要终端、不需要记命令、不需要手动加载 Draft。

## Architecture

```
Local AI.app (菜单栏) ─┐
Browser ───────────────┼──► React Dashboard (静态 SPA)
                       │          │
                       ▼          ▼
              Control Backend  · FastAPI · 127.0.0.1:8787
              (Runtime Manager / Model Registry / Benchmark / Monitoring / launchd)
                          │ 管理（跨进程状态文件 data/runtime_state.json）
                          ▼
Agents ───────► Inference Gateway · FastAPI · 127.0.0.1:8080/v1
(Cursor/OpenCode/…)       │ 反向代理 + 别名重写 + 统计
                          ▼
              Inference Runtime · 127.0.0.1:18080（仅内部）
              FAST  = dflash serve   (Qwen3.8 Target + DFlash Draft 投机解码)
              SAFE  = mlx_lm server  (仅 Target)
```

三个进程完全隔离：**管理后台崩溃不影响模型 API；模型重启不影响后台；模式切换对 Agent 透明**（公共端口与模型别名永不变化）。

## 当前模型

| 角色 | 模型 | 说明 |
|---|---|---|
| Target | `McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit` | 28.6 GB · MLX 8-bit · 256K ctx |
| Draft | `jfan/Qwen3.8-27B-heretic-dflash` | 3.5 GB · block size 16（训练期固定）|

模型从 **LM Studio 库目录**（默认 `~/.lmstudio/models/{org}/{name}`）原地引用，不移动、不改名。额外扫描 `~/.cache/huggingface/hub`，但**新下载不会写到 HF 缓存**。换库目录必须在 Models / Settings 里手动选取。Models 页「发现」可搜 Hugging Face，仅 MLX 可下载；「下载」页是队列（同时只跑一个，可暂停续传）。从下载列表移除只删任务记录；清理残片只删 `.part`；整目录删除只在「已安装」页并需二次确认。架构不锁定这两个模型：已安装列表可将任何 MLX 兼容模型设为 Target。

## Install

```bash
cd ~/AI/local-ai-control-center
bash scripts/install.sh          # venv + 依赖 + 前端构建 + CLI + 可选 launchd
```

首次安装会从 `config/config.example.yaml` 创建本机 `config/config.yaml`。后者包含当前模型、目录和 UI 偏好，属于本地运行状态，默认不提交到 Git。

> 项目必须位于 `~/AI/`（或其他非 TCC 保护目录）。放在 `~/Desktop` / `~/Documents` 下 launchd 服务会被 macOS 权限拦截（exit 78）。

## Start / Stop

| 操作 | 菜单栏 App | Web | CLI |
|---|---|---|---|
| 启动全部 | Popover → Start | Overview → Start | `local-ai start` |
| 停止模型 | Popover → Stop | Overview → Stop | `local-ai stop` |
| 重启 | Popover → Restart | Overview → Restart | `local-ai restart` |
| 状态 | 菜单栏状态灯 | Overview | `local-ai status` |
| 快速基准 | Console → Benchmark | Benchmark 页 | `local-ai benchmark` |
| 日志 | Console → Logs | Logs 页 | `local-ai logs` |
| 打开后台 | Popover → Dashboard | — | `local-ai open` |
| 打开 App | — | — | `local-ai app` |

- Web UI：**http://127.0.0.1:8787**
- 模型 API：**http://127.0.0.1:8080/v1** · API Key `local` · Model 默认 **`Qwen3.8-27B-Heretic-8bit`**（随主模型自动命名，可手动锁定）

## macOS 应用（菜单栏）

原生 `Local AI.app` 是 **8787 Control API 的客户端**，不重写 Runtime。菜单栏 **template 状态图标** + popover 是第一层；Console 是第二层；Settings 只走 ⌘,（符合 macOS HIG）。发布采用双轨：当前主版本走 **Developer ID + 公证**；Mac App Store 走独立架构支线，不是给当前包直接打开 Sandbox。边界见 `docs/DISTRIBUTION-STRATEGY.md`。

```bash
cd ~/AI/local-ai-control-center
bash scripts/build_app.sh          # SwiftPM release + Hardened Runtime
RELEASE_BUILD=1 bash scripts/build_app.sh  # 生产门禁：Developer ID + 公证 + staple
open "dist/Local AI.app"           # 或 local-ai app
```

| 项 | 值 |
|---|---|
| 产物 | `dist/Local AI.app`（`dist/` 不入库） |
| Bundle ID | `com.localai.controlcenter.app` |
| 版本 | App 0.4.0 · 控制面 0.4.0（Agent 协议网关） |
| 最低系统 | macOS 15+ |
| 语言 | 英语 / 简体中文。默认跟随系统（macOS 或浏览器为中文即中文）；Settings、Web 侧栏可覆盖（菜单栏 Popover 不再放语言选择） |
| 签名 | 开发包可 ad-hoc；生产包必须 `RELEASE_BUILD=1`，并通过 Developer ID、公证、staple 与 `scripts/release_check.sh` |
| 源码 | `apps/LocalAIApp/` |
| 构建注意 | 必须走 `scripts/build_app.sh`；CLT 不要用 `@State`/`@AppStorage` |

**交互**

- 左键状态项：Popover（状态、内存/速度/接受率、**一个**主按钮 Start 或 Stop、Safe⇄Fast、Copy / Console）。语言与生命周期说明在 Settings。
- 右键：Console、Copy API Config、Dashboard、Quit（默认 Quit 会停控制面，不只关图标）。
- Console 边栏分组：Control / Decode / Integrate / Observe。窗口标题随当前页变化。工具栏：Start/Stop/Restart 用 SF Symbol；已安装筛选、Discover 搜索、Logs 搜索在工具栏（不用 `.searchable`）。Models 表可选择/排序，右侧检查器；Return 设 Target 或 Draft。关掉 Console **不会**退出 App。切页时窗口外框尺寸不变。
- 菜单：File（打开控制台 / 仪表盘 / 显示模型库）、Edit（拷贝 API ⌘⇧C）、Runtime（⌘⇧R 启动、⌘⇧K 停止、⌘⌥R 重启）、Window（控制台 ⌘L）、Help 三件事、系统 About 面板。设置不再出现在侧栏。库目录在 Settings → General；可把文件夹拖到 Models 或 General。
- 控制面不可达时 Popover/Console 给出 First Run，而不是只有红字。
- 通知权限在第一次 Start Runtime / Start Control Plane 时才申请。

**生命周期（会话由 App 拥有）**

| 操作 | 效果 |
|---|---|
| 打开 App | 拉起控制面 8787 + 网关 8080（若已停）。默认不加载 27B |
| Start | 加载模型（18080） |
| Stop | 只卸载模型；8787/8080 仍在，方便再 Start |
| 关掉 Console | 回到菜单栏，服务继续 |
| Quit（默认） | 卸载模型 + `bootout` 控制面/网关，释放 8787/8080/18080 |
| Settings → 退出后保持 API | 菜单栏退出后 Agent 仍可打 8080，直到注销或下次默认 Quit |
| 登录项 | 启动 **Local AI.app**，不是无界面 8787 |

当前主版本**不是** Mac App Store 包（其 App Sandbox 与现有 launchctl / 项目目录访问冲突）。App Store 版将在独立 target、bundle id、entitlements、bundled helper 与 security-scoped bookmarks 下开发；不得复用主版本的进程监管和发布配置。当前构建机若无 Developer ID 证书，产物只能是 ad-hoc 开发包。完整 Liquid Glass 多层图标需 Icon Composer + Xcode，本版为克制的单层 icns。

## DFlash（Fast Mode）

- Settings 里 **Fast 配方**可切换：**Heretic（默认）** 或 **官方 DFlash 2**。切换会换 Target + Draft + 旋钮；公开模型名默认跟着 Target 走，手动改过则锁定。
- Heretic：`McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit` + `jfan/Qwen3.8-27B-heretic-dflash`（DFlash 1，训练块 16）。
- 官方 DFlash 2：`mlx-community/Qwen3.8-27B-4bit` + `z-lab/Qwen3.8-27B-DFlash2`。模型不在磁盘时页面会标明 missing，不会假装已加载。
- Fast 引擎是社区 **dflash-mlx** 的 `dflash serve`，安装器固定到含 Qwen3.8 DFlash2 的上游 commit `60803233`（包版本 0.1.10）；**不是** `pip install dflash`（那个包会盖掉 serve）。
- DFlash 页实时显示接受率、每周期 token 数、生成速度、Fallback 次数。
- Heretic Draft 的 block size = 16 由训练决定。官方 DFlash2 checkpoint 的训练块为 8，但当前引擎能力上限为 5；服务会自动选择实际校验宽度，CLI 不提供 `--block-size`。Auto Tune 比较 adaptive/full-5、fixed/full-5 与 fixed/cap-4。
- M5 Max 起始参数为 prefill step 2048、Draft 长上下文窗口 64+1024、内存前缀缓存 4 条/8GB、SSD L2 50GB、MLX cache 4GB；所有参数都先经过 CLI 能力探针再下发。
- 可调校验：`verify-mode`（adaptive/dflash）与 `verify-len-cap` — 用 **Benchmark → Auto Tune** 实测选优。
- Fast 崩溃时看门狗**自动回退 Safe**，请求不中断；接受率持续 <25% 会提示建议 Safe（不强切）。

实测（M5 Max 128GB，本仓库 benchmark 页可复现）：

| 场景 | Safe | Fast | 加速 | 接受率 |
|---|---|---|---|---|
| CLI 冒烟（fibonacci 256 tok） | 18.5 tok/s | 27.5 tok/s | **1.49×** | 68.2% |
| SwiftUI 长代码（1024 tok） | 16.9 tok/s | 18.1 tok/s | 1.07× | 48.6% |

> 该 draft 权重仅训练至 10k/60k 步，不同任务域接受率差异大；作者放出完整权重后收益会更高。所有数字均为真实测量，无硬编码。

## Agent 接入

Agents 页为每个工具生成配置并可一键 Test Connection。核心三项对所有 OpenAI 兼容工具通用：

```
Base URL : http://127.0.0.1:8080/v1
API Key  : local
Model    : Qwen3.8-27B-Heretic-8bit   # 总览 / API 页可改；旧名 qwen3.8-27b-local 仍能调通
```

- **Grok.app**：自定义 OpenAI，Base URL 带 `/v1`。Responses 与 Chat Completions 都由网关翻译，不必再为协议 400 切接口。
- **OpenCode**：`~/.config/opencode/opencode.json` 加 provider（Agents 页有完整 JSON 可复制）。已实测端到端完成「读文件→改代码→跑 pytest→3 passed」完整任务。
- **Cursor**：Settings → Models → Override OpenAI Base URL（部分云端功能不适用本地端点）。
- **Codex CLI**：`~/.codex/config.toml` 加 `model_providers.local`。Codex 默认 Responses，网关会译成 Chat Completions。
- **Cline / Roo Code**：选 "OpenAI Compatible" Provider 填三项即可。
- **Claude Code / CodeG**：`ANTHROPIC_BASE_URL=http://127.0.0.1:8080`（不要加 `/v1`，也不要末尾 `/`），`ANTHROPIC_API_KEY=local`（或 `ANTHROPIC_AUTH_TOKEN=local`）。网关提供 `/v1/messages`，并兼容 CLI 把 `?beta=true` 写进路径、以及 `/v1/messages/count_tokens`。模型选当前 alias（如 `Qwen3.8-27B-Heretic-8bit`）或 `sonnet`。CodeG 会并行打两路流式请求，且会在 user 消息后再跟一段 system；网关会排队并合并 system，否则 dflash 会 404（Claude 显示成 503 重试）。

Tool Calling 已真实验证：模型输出标准 `tool_calls` + 合法 JSON 参数 + `finish_reason: "tool_calls"`（Benchmark → Tool Calling Probe 可随时复测）。

## Benchmark

- **Quick**：当前模式单次测速（tok/s、TTFT、tokens）。
- **DFlash A/B**：自动 Safe→测→Fast→测→恢复原模式，输出双速度、Speedup、RAM、接受率。
- **Auto Tune**：遍历 verify 配置组合，推荐最快稳定项。
- **Tool Calling Probe**：真实验证 OpenAI tool_calls 契约。
- 固定 prompt 集（编码短/长、Agent 工具、中文推理、8K 长上下文），temperature=0，全部历史存 SQLite。

## Monitoring / Memory Safety

- SSE 推送（2s 采样，无高频轮询）：统一内存、内核内存压力、Swap、CPU、生成/预填充速度、TTFT、接受率、RSS。
- Swap 超阈值（默认 4GB）或压力 critical 时横幅告警并给出建议（降 context / 减并发 / 卸载模型）。
- GPU 利用率 macOS 无授权接口，**如实不显示**，不造假数据。

## Logs

Logs 页分 Runtime / API / Backend / Benchmark 四类，默认「重要优先」降噪（错误、警告、重启、模型加载、基准），支持搜索、Errors only、自动滚动、复制。

## 控制面服务（launchd）

```
~/Library/LaunchAgents/com.localai.controlcenter.backend.plist   # 8787
~/Library/LaunchAgents/com.localai.controlcenter.gateway.plist   # 8080
```

`RunAtLoad` 为 **false**：登录不会偷偷占 8787。KeepAlive 只在 **job 已被 load** 时做崩溃拉起（App 打开期间）。**默认从 Local AI.app Quit 会 bootout**，端口释放。需要给 Cursor 等 Agent 留 API 时，在 Settings 打开「退出后保持 API」。

**模型不随登录加载**（27B 会占 ~29GB 内存），仅当点 Start 或开启 Auto-load（控制面启动时）才加载。Settings → Services 可安装/卸载 LaunchAgent（安装 ≠ 登录常驻）。无 App、只用 CLI 时：`local-ai start` / `local-ai stop` 仍可单独管控制面。

## 配置

单一来源 `config/config.yaml`（端口、Target/Draft、模式、context、DFlash 参数、别名、日志级别、隐私开关）。Web Settings 页修改即持久化；涉及运行时的改动会明确提示 Restart。

仓库只保留 `config/config.example.yaml`。`data/`、`logs/`、本机配置和动态生成的 `launchd/*.plist` 都被忽略；安装器会按当前 checkout 的真实路径生成 LaunchAgent，避免把个人绝对路径提交到仓库。

## 安全与隐私

- 全部端口仅监听 `127.0.0.1`，无 LAN/公网暴露选项（本版有意不提供）。
- 无 Telemetry、无 Analytics、无外部请求。
- SQLite 只存事件与基准结果，**默认不存 prompt 内容**（Settings → Privacy 可显式开启）。

## Testing

```bash
.venv/bin/python -m pytest -q            # 20 项：单元(离线) + 集成(需服务运行)
cd frontend && npx vitest run            # 前端
```

## Troubleshooting

| 症状 | 处理 |
|---|---|
| API 返回 503 | 响应体的 `how_to_fix` 有明确指引；通常是 Runtime 未启动 → Start |
| launchd 服务 exit 78 | 项目在 TCC 保护目录（Desktop/Documents）→ 移到 `~/AI/` 重装服务 |
| Fast 模式反复崩溃 | 看 Logs → Runtime；看门狗已自动回退 Safe；可 A/B 验证 draft 兼容性 |
| 页面数字全是 `—` | Safe 模式下 mlx-lm 不提供 /metrics，属如实展示；Fast 模式才有细粒度指标 |
| 改了设置不生效 | 看顶部 Restart required 横幅，点 Restart now |
| 内存告警 | 降 max context / 停其他大模型应用；Swap 阈值可在 Settings → Advanced 调 |
| 菜单栏没有 Local AI | `bash scripts/build_app.sh` 后 `local-ai app`；配件应用不在 Dock，看状态栏右侧 |
| `swift build` 找不到宏 / 编到错误目录 | 用 `scripts/build_app.sh`，不要在 `apps/` 目录裸跑 `swift build` |
| 菜单栏 App 仍显示英文键名 | Settings → Language；确认包内有 `en.lproj` / `zh-Hans.lproj` |
| 打开 App 被拦截 | ad-hoc 未公证；右键 → 打开。公证需要 Developer ID |

## Update / Uninstall

```bash
# Update
cd ~/AI/local-ai-control-center && git pull && bash scripts/install.sh
# 需要新版菜单栏 App 时再跑：bash scripts/build_app.sh

# Uninstall（不影响 LM Studio / Ollama / 模型文件）
# 若开过「登录时启动 Local AI.app」：先在 App Settings 关掉 Launch at Login，再退出 App
launchctl bootout gui/$(id -u)/com.localai.controlcenter.backend
launchctl bootout gui/$(id -u)/com.localai.controlcenter.gateway
rm -f ~/Library/LaunchAgents/com.localai.controlcenter.{backend,gateway}.plist
rm -f ~/.local/bin/local-ai
rm -rf ~/AI/local-ai-control-center
```

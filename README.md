# Local AI Control Center

Apple Silicon 本地大模型 Runtime + Agent Gateway + Speculative Decoding 管理后台。

打开 <http://127.0.0.1:8787> → 点击 Start → Agent 直接使用本地模型。不需要终端、不需要记命令、不需要手动加载 Draft。

## Architecture

```
Browser ──────────► React Dashboard (静态 SPA)
                          │
                          ▼
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

模型从 LM Studio / HF 缓存目录**原地只读引用**，不移动、不修改。架构不锁定这两个模型：Models 页可将任何 MLX 兼容模型设为 Target。

## Install

```bash
cd ~/AI/local-ai-control-center
bash scripts/install.sh          # venv + 依赖 + 前端构建 + CLI + 可选 launchd
```

> 项目必须位于 `~/AI/`（或其他非 TCC 保护目录）。放在 `~/Desktop` / `~/Documents` 下 launchd 服务会被 macOS 权限拦截（exit 78）。

## Start / Stop

| 操作 | Web | CLI |
|---|---|---|
| 启动全部 | Overview → Start | `local-ai start` |
| 停止模型 | Overview → Stop | `local-ai stop` |
| 重启 | Overview → Restart | `local-ai restart` |
| 状态 | Overview | `local-ai status` |
| 快速基准 | Benchmark 页 | `local-ai benchmark` |
| 日志 | Logs 页 | `local-ai logs` |
| 打开后台 | — | `local-ai open` |

- Web UI：**http://127.0.0.1:8787**
- 模型 API：**http://127.0.0.1:8080/v1** · API Key `local` · Model **`qwen3.8-27b-local`**

## DFlash（Fast Mode）

- Runtime 页切换 Safe（仅 Target）/ Fast（Target + Draft），Agent 配置零改动。
- DFlash 页实时显示接受率、每周期 token 数、生成速度、Fallback 次数。
- Draft 的 block size = 16 由训练决定，不可运行时调整；可调的是 `verify-mode`（adaptive/dflash）与 `verify-len-cap`（4/8/16/默认）— 用 **Benchmark → Auto Tune** 实测选优。
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
Model    : qwen3.8-27b-local
```

- **OpenCode**：`~/.config/opencode/opencode.json` 加 provider（Agents 页有完整 JSON 可复制）。已实测端到端完成「读文件→改代码→跑 pytest→3 passed」完整任务。
- **Cursor**：Settings → Models → Override OpenAI Base URL（部分云端功能不适用本地端点）。
- **Codex CLI**：`~/.codex/config.toml` 加 `model_providers.local`（页内有 TOML 片段）。
- **Cline / Roo Code**：选 "OpenAI Compatible" Provider 填三项即可。
- **Claude Code**：Anthropic 协议，需 LiteLLM 等兼容网关桥接，本版**未内置**（页内如实标注，不做假兼容）。

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

## 常驻服务（launchd）

```
~/Library/LaunchAgents/com.localai.controlcenter.backend.plist   # 8787
~/Library/LaunchAgents/com.localai.controlcenter.gateway.plist   # 8080
```

登录自启 + 崩溃自动拉起（KeepAlive）。**模型不随登录加载**（27B 会占 ~29GB 内存），仅当点 Start 或在 Settings 开启 Auto-load 时才加载。Settings → Startup 可安装/卸载服务。

## 配置

单一来源 `config/config.yaml`（端口、Target/Draft、模式、context、DFlash 参数、别名、日志级别、隐私开关）。Web Settings 页修改即持久化；涉及运行时的改动会明确提示 Restart。

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

## Update / Uninstall

```bash
# Update
cd ~/AI/local-ai-control-center && git pull && bash scripts/install.sh

# Uninstall（不影响 LM Studio / Ollama / 模型文件）
launchctl bootout gui/$(id -u)/com.localai.controlcenter.backend
launchctl bootout gui/$(id -u)/com.localai.controlcenter.gateway
rm -f ~/Library/LaunchAgents/com.localai.controlcenter.{backend,gateway}.plist
rm -f ~/.local/bin/local-ai
rm -rf ~/AI/local-ai-control-center
```

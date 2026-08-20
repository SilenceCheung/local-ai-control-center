# Environment Audit — Local AI Control Center

审计时间：2026-08-20 10:25 (UTC+8) · 审计人：Agent（只读审计，未修改任何现有配置）

## 1. 硬件与系统

| 项 | 值 |
|---|---|
| 机型芯片 | Apple M5 Max（`arm64`，GPU `applegpu_g17*` 世代，支持 dflash-mlx 的 Metal 4 NAX verify kernel） |
| 统一内存 | **128 GB** |
| macOS | 27.0 (Build 26A5416b) |
| Shell | `/bin/zsh` |

结论：128 GB 统一内存运行 26 GB 的 8-bit 27B 目标模型 + 3.2 GB 草稿模型非常宽裕；内存安全阈值可设保守值。

## 2. 工具链

| 工具 | 版本 / 路径 | 状态 |
|---|---|---|
| Python（默认） | 3.14.6 · `/opt/homebrew/bin/python3` | 偏新，不用于本项目 |
| Python 3.12 | `/opt/homebrew/bin/python3.12` | **本项目 venv 采用（3.12.13）** |
| Python 3.11 / 3.13 | Homebrew / `~/.local/bin` | 备用 |
| pip3 | `/opt/homebrew/bin/pip3` | 正常（不使用 sudo pip，不改系统 Python） |
| Homebrew | 6.0.17 | 正常 |
| Git | 2.54.0 | 正常 |
| Node | v22.16.0 · `~/.local/node/bin` | 正常 |
| npm / pnpm | 10.9.2 / 10.33.2 | 正常，前端用 pnpm |

## 3. ML 运行时现状

| 组件 | 状态 |
|---|---|
| mlx（系统 Python 3.14） | 0.31.2 已装（不复用，项目 venv 独立安装） |
| mlx-lm / mlx-vlm | 系统未装 → venv 内安装 |
| **dflash-mlx** | 未装 → venv 内安装 `dflash-mlx`（PyPI 0.1.10，Apache-2.0） |
| LM Studio | 运行中，监听 `127.0.0.1:1234`；CLI `lms` 在 `~/.lmstudio/bin` — **不修改** |
| Ollama | 0.24.0 运行中，监听 `127.0.0.1:11434` — **不修改** |

## 4. 端口

| 端口 | 占用 | 用途规划 |
|---|---|---|
| 8787 | 空闲 | Control Plane（管理后台） |
| 8080 | 空闲 | Inference Plane 对外入口（OpenAI 兼容 Gateway） |
| 18080 | 空闲 | Runtime 内部端口（dflash serve / mlx_lm.server，仅 127.0.0.1） |
| 1234 | LM Studio | 不动 |
| 11434 | Ollama | 不动 |

## 5. 模型资产

### Target：`McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit`

- 路径：`~/.lmstudio/models/McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit/`
- 架构：`Qwen3_5ForConditionalGeneration`（Qwen3.8-27B，64 层混合：48× Gated DeltaNet + 16× Gated Attention，hidden 5120，vocab 248320，原生 262K 上下文）
- 量化：MLX affine 8-bit，group_size 64 · 体积 ≈ 26 GB · 6 个 safetensors 分片
- **审计时状态：分片 4/6 仍在 LM Studio 下载中**（`downloading_model-00004-of-00006.safetensors.part`）；其余 5 片 + tokenizer + chat template 完整

### Draft：`jfan/Qwen3.8-27B-heretic-dflash`

- 路径：`~/.lmstudio/models/jfan/Qwen3.8-27B-heretic-dflash/`
- 类型：**DFlash 块扩散草稿模型**（非普通独立小模型）：5 层，461M/2B 级参数，bf16，3.2 GB
- 关键配置：`block_size: 16`（训练时固定）、`mask_token_id: 248070`、`target_layer_ids: [1,16,31,46,61]`（从目标模型 5 个层抽 hidden state 拼 25600 维输入）
- 模型卡实测（M5 Pro 48GB，10k/60k 训练步的中期检查点）：基线 16.12 tok/s → DFlash 22.82 tok/s，接受率 55.3%，**+41.6%**
- 注意：该 drafter 训练目标是 `trohrbaugh/Qwen3.8-27B-heretic-ara`（McG-221 8-bit 是其量化版）；量化不匹配可能压低接受率——需要 A/B 实测，不得预设 3x
- 仓库无 tokenizer → 运行时复用 target tokenizer（dflash-mlx 默认行为）

## 6. Runtime 选型结论

**采用 `dflash-mlx`（PyPI）作为 FAST MODE 推理引擎**，理由：

1. mlx-lm 核心尚未合入 DFlash；dflash-mlx 是当前最成熟实现（767 stars）
2. 自带 `dflash serve`：OpenAI 兼容 `/v1/chat/completions`（SSE 流式 + `delta.tool_calls` 工具调用）、最小 `/v1/responses` 适配、`/metrics` 实时指标（接受率、tokens_per_cycle、prefill/decode tok/s、rss）
3. 原生支持 Qwen3.5/3.6/3.8 混合 GatedDeltaNet 架构（tape-replay 回滚），M5 GPU 有专用 verify kernel
4. 非注册模型对可用 `--draft` 显式覆盖 → 支持本地 heretic 目标 + jfan 草稿

SAFE MODE（Target only）：`mlx_lm.server`（同一 venv），Gateway 统一对外。

**DFlash「块大小」如实说明**：本草稿检查点 `block_size=16` 为训练期固定值，不存在可选 3/4/5 的草稿长度旋钮（那是普通 speculative decoding 的参数）。可调项为 dflash-mlx 的 `--verify-mode`（adaptive/dflash）、`--fastpath-max-tokens`、`--draft-quant`、prefill step 等；Auto-Tune 将针对这些真实旋钮做基准。

## 7. 不修改清单（遵守）

LM Studio / Ollama / Cursor / Claude Code / Codex 的任何配置、系统 Python、`sudo pip` —— 全部未动，仅读。

# Production Agent Gateway Validation

> Historical baseline from before the 2026-08-21 P0–P2 hardening. The Target has since been restored, but the results below remain historical and must not be used as acceptance evidence for the new gateway build. A partial live revalidation on 2026-08-21 returned three `429 local_queue_full` failures; the current mandatory matrix and release decision are in `docs/P0-P2-PRODUCTION-READINESS.md`.

Date: 2026-08-21

Host: Apple M5 Max

Runtime: `dflash-mlx 0.1.10`

Target: `lmstudio-community/Qwen3.8-27B-MLX-4bit`

Draft: `z-lab/Qwen3.8-27B-DFlash2` (`w4:gs64`)
Public API: `http://127.0.0.1:8080/v1`

## Release decision

The gateway passes the production-agent functional gate for Grok Build 1.0.5,
Claude Code 2.1.232, and OpenCode 1.18.18. Each client completed a real repository
task using file-read, file-edit, and shell tools; the resulting patch was checked
outside the agent and all four tests passed.

This does **not** mean every request runs at 100 token/s. On this machine the
observed DFlash decode range was roughly 53–96 token/s. End-to-end latency is
dominated by cold prefill and by the number of agent turns, not decode alone.

## Measured evidence

| Gate | Result |
|---|---|
| Recipe activation | Runtime process includes Target, DFlash2 Draft, `--draft-quant w4:gs64`, adaptive verification, L1/L2 cache; request metrics report `mode_used=dflash` |
| Grok Build | PASS — 12 full agent turns, 24 tools, edit + shell loop, 4 tests passed |
| Claude Code | PASS — native Anthropic `/v1/messages`, 13 requests, 0 gateway errors, edit + shell loop, 4 tests passed |
| OpenCode | PASS — OpenAI-compatible provider, edit + shell loop, 4 tests passed |
| Mixed-protocol soak | PASS — 30/30 calls; Chat, Responses, Anthropic each 10; P50 334 ms, P95 342 ms, max 650 ms |
| Stream cancellation recovery | PASS with caveat — slot released after current 512-token generation drained in 9.5 s; next Responses call succeeded in 385 ms |
| Bounded queue | PASS — capacity 1 + maximum 3 waiting; fifth concurrent call returned HTTP 429 with `Retry-After: 15` in 40 ms |
| Gateway-only restart | PASS — gateway restarted while the loaded 27B runtime stayed healthy; next Responses call returned in 555 ms |

### Cold and warm long-context behavior

The controlled queue test produced an 18,053-token prompt:

- cold: 18,053 physical prefill tokens, 0 restored, 32.36 s;
- warm: 7 physical tokens, 18,046 restored, 0.198–0.205 s;
- four accepted requests completed successfully; the fifth was rejected before
  reaching the runtime.

The Grok Build production task had a 49 KB tool schema and an approximately 19K
initial prompt. Its first prefill was 25.61 s. Later turns restored 18.9K–21.3K
tokens and prefilling fell to 0.36–0.66 s. Decode measured 52.9–66.5 token/s with
roughly 69–80% DFlash acceptance.

Claude `--bare` exposed only three tools and started with a much smaller prompt.
Its early turns were below the engine's useful cache frontier and were cold; once
the conversation exceeded roughly 4K tokens, later turns restored 4.3K–4.7K
tokens and prefill fell to 0.64–0.73 s.

## The three root causes and shipped controls

### 1. Recipe was not demonstrably active

- `recipes.active` is `official_dflash2`;
- Target and Draft are the official compatible pair;
- runtime command-line and per-request metrics now provide evidence;
- tool-bearing requests are normalized to deterministic temperature 0 so agent
  calls do not fall into an unstable exact-target path.

Acceptance rule: do not call a run “DFlash” unless `mode_used=dflash`, Draft is
loaded, acceptance is present, and the runtime process has the expected Draft
and quantization arguments.

### 2. 20K cold prefill

- retain the loaded runtime between agent sessions;
- keep system prompt and tool order stable so the prefix fingerprint remains
  stable;
- disable unused plugins/MCP tools: tool schemas are part of every prompt;
- use Grok Build's minimal tool/plugin mode and Claude `--bare` for latency-
  sensitive tasks;
- prewarm each stable agent profile once after a runtime restart;
- start a new session when a conversation has accumulated irrelevant history.

The first cold 18–20K turn is expected to take about 25–33 seconds on the tested
configuration. The correct product target is sub-second warm prefill, not a
false promise that a never-seen 20K prefix is instant.

### 3. Cache and gateway scheduling were opaque

`GET /gateway/stats` now reports:

- active/waiting/capacity, queue totals, rejects, timeouts and maximum wait;
- in-flight and recent request ID, agent, protocol, shape, tool-schema bytes,
  queue wait, TTFT and total duration;
- physical/restored prefill tokens, cache state, prefill duration, DFlash mode,
  acceptance, decode speed and finish reason;
- prompt and prefix fingerprints only — never prompt content;
- bounded recent history and agents-seen history persisted across a gateway-only
  restart, while live active/waiting state is reset safely.

Responses include `X-LocalAI-Request-ID` and `X-LocalAI-Queue-Wait-Ms` for support
correlation.

## Agent-specific production configuration

### Grok Build

Use Chat Completions, temperature 0, a 65,536 context declaration, and streaming
tool calls. Grok launches a small auxiliary request concurrently with the main
agent turn; the scheduler gives that helper a short grace period so the full
production turn receives the single MLX slot first.

### Claude Code / Claude CLI

Set `ANTHROPIC_BASE_URL=http://127.0.0.1:8080` without `/v1` and set the model to
`Qwen3.8-27B-4bit`. Use `--bare` when low latency matters. The gateway supports
`/v1/messages`, `?beta=true`, count-tokens and streaming tool-use frames.

### OpenCode

Use `@ai-sdk/openai-compatible`, base URL `http://127.0.0.1:8080/v1`, API key
`local`, and model `Qwen3.8-27B-4bit` (legacy aliases are rewritten safely).

## Remaining production caveats

1. A disconnected stream does not interrupt an in-progress DFlash generation;
   capacity is released when that generation finishes. The tested 512-token
   cancellation recovered in 9.5 seconds. A runtime interrupt endpoint is P1.
2. macOS has `python3` but no `python`, and the system Python does not include
   pytest. Agent projects should provide their own environment. Recommended
   fallback: `uv run --with pytest pytest -q`.
3. One local MLX runtime is intentionally single-slot. The gateway provides
   bounded queuing and load shedding; it is not a multi-user inference cluster.

## Ongoing production SLO

- availability: 99% successful local requests while runtime is loaded;
- warm prefill: P95 below 1.0 s for a stable agent prefix;
- queue: never more than three waiting requests; overload returns 429 quickly;
- protocol soak: 30/30 before release;
- tool loop: all three reference agents must edit a fixture and pass its tests;
- privacy: no prompt or tool-result content in gateway telemetry.

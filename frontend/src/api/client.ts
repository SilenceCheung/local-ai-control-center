const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      msg = body.detail || body.error?.message || msg;
    } catch { /* keep default */ }
    throw new ApiError(r.status, msg);
  }
  return r.json();
}

export const api = {
  get: <T>(path: string) => req<T>(path),
  post: <T>(path: string, body?: unknown) =>
    req<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    req<T>(path, { method: "PUT", body: JSON.stringify(body) }),
};

// ---------- types ----------

export interface RuntimeStatus {
  status: "stopped" | "starting" | "running" | "stopping" | "error";
  mode: "safe" | "fast";
  provider: string;
  pid: number | null;
  alias: string;
  target_model: string | null;
  draft_model: string | null;
  error: string | null;
  process_alive: boolean;
  http_healthy: boolean;
  engine: string;
  uptime_s: number | null;
  advisory: Advisory | null;
  fallback_count: number;
}

export interface Advisory {
  level: string;
  title: string;
  detail: string;
  kind?: string;
}

export interface ModelInfo {
  id: string;
  display_name: string;
  architecture: string | null;
  parameter_size: string | null;
  quantization: string | null;
  format: string | null;
  local_path: string | null;
  huggingface_repo: string | null;
  role: string;
  compatibility: string | null;
  context_length: number | null;
  memory_estimate_gb: number | null;
  size_bytes: number | null;
  status: string;
  extra: { is_dflash_draft?: boolean; block_size?: number; model_type?: string };
}

export interface HealthResponse {
  backend: string;
  runtime: {
    status: string; mode: string; process_alive: boolean; http_healthy: boolean;
    model_loaded: boolean; draft_loaded: boolean; error: string | null;
  };
  api: { ok: boolean; detail: unknown };
  ports: { dashboard: number; api: number };
}

export interface Sample {
  t: number;
  cpu_pct: number;
  mem_used_gb: number;
  mem_total_gb: number;
  mem_pct: number;
  swap_used_gb: number;
  pressure_level: number | null;
  runtime?: {
    decode_tok_s?: number; prefill_tok_s?: number; rss_gb?: number;
    acceptance_rate?: number; ttft_s?: number; active_request?: boolean;
  };
}

export interface BenchJob {
  busy: boolean;
  job: {
    kind: string; status: string; current: string; error?: string;
    steps: { step: string; detail: string; t: number }[];
    result: Record<string, unknown> | null;
    started_at: number; finished_at?: number;
  } | null;
}

export interface BenchRun {
  id: number; kind: string; label: string; mode: string; prompt_key: string;
  config: Record<string, unknown>; results: Record<string, unknown>; created_at: number;
}

export interface AgentInfo {
  id: string; name: string; status: string; protocol: string;
  instructions: string; config_snippet?: string;
  not_supported_natively?: boolean;
  config: { base_url: string; api_key: string; model: string };
}

export interface AppConfig {
  api: { host: string; port: number; api_key: string; alias: string };
  dashboard: { host: string; port: number };
  runtime: {
    provider: string; internal_port: number; mode: string; auto_load: boolean;
    target_model: string; draft_model: string; max_context: number;
    default_max_tokens: number; enable_thinking: boolean;
  };
  dflash: {
    enabled: boolean; verify_mode: string; verify_len_cap: number;
    draft_quant: string; fastpath_max_tokens: number; prefix_cache: boolean;
  };
  memory: { swap_warn_gb: number; pressure_warn_pct: number };
  logging: { level: string };
  privacy: { log_prompts: boolean };
  model_dirs: string[];
}

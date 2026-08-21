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

export interface HubHit {
  id: string;
  downloads: number;
  likes: number;
  last_modified: string | null;
  pipeline_tag: string | null;
  library_name: string | null;
  tags: string[];
  param_size: string | null;
  local: boolean;
  partial?: boolean;
  runnable: boolean;
  kind: "target" | "draft" | "unusable";
  reason: "gguf" | "vision" | "not_mlx" | null;
}

export interface HubFile {
  name: string;
  size_bytes: number | null;
}

export interface HubCard extends HubHit {
  license: string | null;
  gated: boolean;
  architectures: string[];
  files: HubFile[];
  readme: string | null;
  url: string;
  reasoning: boolean;
  tools: boolean;
}

export interface HubSearch {
  ok: boolean;
  query: string;
  sort: string;
  format: string;
  results: HubHit[];
}

export interface ModelLibrary {
  library: string;
  library_resolved: string;
  exists: boolean;
  layout: string;
  extras: string[];
  model_dirs: string[];
}

export interface DownloadItem {
  repo_id: string;
  status: string;
  assign_role?: string | null;
  dest?: string;
  bytes_done?: number;
  bytes_total?: number;
  current?: string;
  detail?: string;
  error?: string | null;
  source?: "app" | "legacy" | "discovered";
  completion_source?: "disk" | null;
  added_at?: number;
  updated_at?: number;
  has_partial_files?: boolean;
  has_complete_model?: boolean;
  partial_bytes?: number;
}

export interface PullJob {
  busy: boolean;
  library?: ModelLibrary;
  active_id?: string | null;
  queue?: string[];
  items?: DownloadItem[];
  reconciled_models?: string[];
  job: {
    kind: string;
    status: string;
    repo_id: string;
    dest: string;
    assign_role?: string | null;
    current: string;
    detail?: string;
    error?: string | null;
    bytes_done: number;
    bytes_total: number;
    steps: { step: string; detail: string; t: number }[];
    result: Record<string, unknown> | null;
    started_at: number;
    finished_at?: number;
  } | null;
}

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

export interface RecipeSlot {
  target_model: string;
  draft_model: string;
  dflash?: Record<string, string | number>;
}

export interface RecipesStatus {
  active: string;
  generation: string;
  slots: Record<string, {
    id: string; generation: string; target_model: string; draft_model: string;
    dflash: Record<string, string | number>;
  }>;
  applied: { target_model: string; draft_model: string; dflash: Record<string, string | number> };
  missing: { id: string; role: string }[];
  engine: {
    package: string; version: string | null; cli: string; upstream: string;
    knobs_live: Record<string, boolean>;
    official_dflash2_in_engine_registry: boolean;
    generation_supported: Record<string, boolean>;
  };
}

export interface AppConfig {
  api: { host: string; port: number; api_key: string; alias: string; alias_auto?: boolean; alias_source?: string };
  dashboard: { host: string; port: number };
  runtime: {
    provider: string; internal_port: number; mode: string; auto_load: boolean;
    target_model: string; draft_model: string; max_context: number;
    default_max_tokens: number; enable_thinking: boolean;
    recipe?: string;
  };
  dflash: {
    enabled: boolean; verify_mode: string; verify_len_cap: number;
    draft_quant: string; fastpath_max_tokens: number; prefix_cache: boolean;
    runtime_block_size?: number; draft_bits?: number; reasoning?: string;
    prefill_step_size?: number; draft_sink_size?: number; draft_window_size?: number;
    prefix_cache_l2?: boolean; prefix_cache_max_entries?: number;
    prefix_cache_max_bytes?: string; prefix_cache_l2_max_bytes?: string;
    cache_limit?: string;
  };
  recipes?: {
    active: string;
    heretic?: RecipeSlot;
    official_dflash2?: RecipeSlot;
  };
  memory: { swap_warn_gb: number; pressure_warn_pct: number };
  logging: { level: string };
  privacy: { log_prompts: boolean };
  model_dirs: string[];
  ui?: { language?: string };
}

"""Unit tests: config, state contract, registry parsing, prompts."""

import json

import pytest

from backend.benchmark.prompts import BENCHMARK_PROMPTS, build_long_context_prompt
from backend.core import config as cfg_mod
from backend.core.config import DEFAULT_CONFIG, _deep_merge
from backend.core.state import RuntimeState, pid_alive


def test_deep_merge_nested():
    merged = _deep_merge({"a": {"x": 1, "y": 2}, "b": 1}, {"a": {"y": 3}})
    assert merged == {"a": {"x": 1, "y": 3}, "b": 1}


def test_default_config_is_localhost_only():
    assert DEFAULT_CONFIG["api"]["host"] == "127.0.0.1"
    assert DEFAULT_CONFIG["dashboard"]["host"] == "127.0.0.1"
    assert DEFAULT_CONFIG["runtime"]["internal_host"] == "127.0.0.1"


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")
    cfg = cfg_mod.load_config()
    cfg["runtime"]["mode"] = "safe"
    cfg_mod.save_config(cfg)
    reloaded = cfg_mod.load_config()
    assert reloaded["runtime"]["mode"] == "safe"
    # untouched defaults survive
    assert reloaded["api"]["alias"] == DEFAULT_CONFIG["api"]["alias"]


def test_update_config_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")
    out = cfg_mod.update_config({"dflash": {"verify_len_cap": 8}})
    assert out["dflash"]["verify_len_cap"] == 8
    assert out["dflash"]["verify_mode"] == "adaptive"


def test_state_roundtrip(tmp_path, monkeypatch):
    import backend.core.state as state_mod
    monkeypatch.setattr(state_mod, "STATE_PATH", tmp_path / "state.json")
    st = RuntimeState(status="running", mode="fast", pid=12345)
    state_mod.write_state(st)
    got = state_mod.read_state()
    assert got.status == "running"
    assert got.mode == "fast"
    assert got.pid == 12345


def test_state_missing_file_defaults(tmp_path, monkeypatch):
    import backend.core.state as state_mod
    monkeypatch.setattr(state_mod, "STATE_PATH", tmp_path / "nope.json")
    st = state_mod.read_state()
    assert st.status == "stopped"


def test_pid_alive():
    import os
    assert pid_alive(os.getpid())
    assert not pid_alive(None)
    assert not pid_alive(2**22)  # not a real pid


def test_registry_parses_dflash_draft(tmp_path):
    from backend.models.registry import _parse_model_dir
    d = tmp_path / "draft"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({
        "architectures": ["DFlashDraftModel"],
        "model_type": "qwen3",
        "block_size": 16,
        "dflash_config": {"target_layer_ids": [1, 16, 31, 46, 61]},
        "max_position_embeddings": 262144,
    }))
    (d / "model.safetensors").write_bytes(b"x" * 1024)
    info = _parse_model_dir(d, "org/draft")
    assert info is not None
    assert info["compatibility"] == "mlx-dflash-draft"
    extra = json.loads(info["extra"])
    assert extra["is_dflash_draft"] is True
    assert extra["block_size"] == 16


def test_registry_parses_quantized_target(tmp_path):
    from backend.models.registry import _parse_model_dir
    d = tmp_path / "target"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({
        "architectures": ["Qwen3_5ForConditionalGeneration"],
        "model_type": "qwen3_5",
        "quantization": {"bits": 8, "group_size": 64},
        "max_position_embeddings": 262144,
    }))
    (d / "model-00001.safetensors").write_bytes(b"x" * 2048)
    info = _parse_model_dir(d, "org/target-8bit")
    assert info is not None
    assert info["compatibility"] == "mlx"
    assert "8-bit" in info["quantization"]


def test_registry_parses_dflash2_nested_block_size(tmp_path):
    from backend.models.registry import _parse_model_dir
    d = tmp_path / "dflash2"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({
        "architectures": ["DFlash2DraftModel"],
        "model_type": "qwen3_8",
        "dflash_config": {"block_size": 8, "target_layer_ids": [8, 16, 24]},
    }))
    (d / "model.safetensors").write_bytes(b"x" * 1024)
    info = _parse_model_dir(d, "z-lab/Qwen3.8-27B-DFlash2")
    assert info is not None
    extra = json.loads(info["extra"])
    assert info["compatibility"] == "mlx-dflash-draft"
    assert extra["is_dflash2"] is True
    assert extra["block_size"] == 8


def test_registry_skips_incomplete_download(tmp_path):
    from backend.models.registry import _parse_model_dir
    d = tmp_path / "dl"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"model_type": "qwen3_5"}))
    (d / "model-00001.safetensors").write_bytes(b"x")
    (d / "downloading_model-00002.safetensors.part").write_bytes(b"x")
    info = _parse_model_dir(d, "org/dl")
    assert info is not None
    assert info["status"] == "downloading"


def test_resolve_path_rejects_downloading_model(tmp_path, monkeypatch):
    from backend.models import registry as reg
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    monkeypatch.setattr(reg, "get_model", lambda _: {
        "local_path": str(model_dir), "status": "downloading",
    })
    assert reg.resolve_path("org/model") is None
    monkeypatch.setattr(reg, "get_model", lambda _: {
        "local_path": str(model_dir), "status": "available",
    })
    assert reg.resolve_path("org/model") == str(model_dir)


def test_benchmark_prompts_fixed():
    assert "coding_long" in BENCHMARK_PROMPTS
    assert BENCHMARK_PROMPTS["coding_long"]["max_tokens"] == 1024
    p = build_long_context_prompt()
    assert "AMBER-COBALT-9241" in p
    assert len(p.split()) > 3000


@pytest.mark.asyncio
async def test_mlx_provider_builds_commands(tmp_path, monkeypatch):
    from backend.runtime.mlx_provider import MLXRuntimeProvider
    import backend.runtime.mlx_provider as prov_mod
    monkeypatch.setattr(prov_mod, "resolve_path", lambda mid: f"/models/{mid}")
    provider = MLXRuntimeProvider()
    cfg = cfg_mod.load_config()

    cmd, _ = provider._build_command("fast", cfg)
    joined = " ".join(cmd)
    assert "dflash" in cmd[0]
    assert "--draft-model" in joined
    assert "--host 127.0.0.1" in joined

    cmd_safe, _ = provider._build_command("safe", cfg)
    assert "mlx_lm" in " ".join(cmd_safe)
    assert "--draft-model" not in " ".join(cmd_safe)

    with pytest.raises(ValueError):
        provider._build_command("turbo", cfg)


def test_recipes_default_is_heretic(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")
    from backend.runtime import recipes as rec
    monkeypatch.setattr(rec, "_SERVE_FLAGS", frozenset({"--model", "--draft-model", "--verify-mode"}))
    monkeypatch.setattr(rec, "resolve_path", lambda mid: f"/models/{mid}")
    d = rec.describe()
    assert d["active"] == "heretic"
    assert d["generation"] == "dflash1"
    assert d["slots"]["official_dflash2"]["draft_model"] == "z-lab/Qwen3.8-27B-DFlash2"


def test_legacy_runtime_recipe_uses_effective_quant_not_only_models():
    from backend.runtime.mlx_provider import _launch_profile
    from backend.runtime.recipes import ensure_recipes
    from backend.core.config import DEFAULT_CONFIG
    import copy

    cfg = ensure_recipes(copy.deepcopy(DEFAULT_CONFIG))
    target = "lmstudio-community/Qwen3.8-27B-MLX-4bit"
    draft = "z-lab/Qwen3.8-27B-DFlash2"
    # Reproduce the old UI failure: both recipe slots ended up pointing at the
    # same model pair, so only launch arguments can identify the live recipe.
    for recipe_id in ("heretic", "official_dflash2"):
        cfg["recipes"][recipe_id]["target_model"] = target
        cfg["recipes"][recipe_id]["draft_model"] = draft
    command = [
        "dflash", "serve", "--verify-mode", "adaptive",
        "--draft-quant", "w4:gs64",
        "--chat-template-args", '{"reasoning_effort":"xhigh"}',
    ]
    profile = _launch_profile(
        "fast", cfg, command, target_model=target, draft_model=draft,
        infer_recipe=True,
    )
    assert profile["recipe_id"] == "official_dflash2"
    assert profile["draft_quant"] == "w4:gs64"


def test_recipe_activate_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")
    from backend.runtime import recipes as rec
    monkeypatch.setattr(rec, "_SERVE_FLAGS", frozenset({"--model", "--verify-mode"}))
    monkeypatch.setattr(rec, "resolve_path", lambda mid: f"/models/{mid}")
    rec.activate("official_dflash2")
    cfg = cfg_mod.load_config()
    assert cfg["recipes"]["active"] == "official_dflash2"
    assert cfg["runtime"]["draft_model"] == "z-lab/Qwen3.8-27B-DFlash2"


def test_recipe_activation_does_not_pollute_source_slot_with_destination_models(tmp_path, monkeypatch):
    from backend.core import config as cfg_mod
    from backend.runtime import recipes as rec

    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")
    cfg = cfg_mod.load_config()
    cfg["recipes"] = rec.default_recipes_section()
    cfg["runtime"]["target_model"] = rec.DEFAULT_SLOTS[rec.OFFICIAL_DFLASH2]["target_model"]
    cfg["runtime"]["draft_model"] = rec.DEFAULT_SLOTS[rec.OFFICIAL_DFLASH2]["draft_model"]
    cfg_mod.save_config(cfg)

    rec.activate(rec.OFFICIAL_DFLASH2)
    saved = cfg_mod.load_config()
    assert saved["recipes"][rec.HERETIC]["target_model"] == rec.DEFAULT_SLOTS[rec.HERETIC]["target_model"]
    assert saved["recipes"][rec.HERETIC]["draft_model"] == rec.DEFAULT_SLOTS[rec.HERETIC]["draft_model"]
    assert cfg["dflash"]["verify_mode"] == "adaptive"
    rec.activate("heretic")
    cfg = cfg_mod.load_config()
    assert cfg["runtime"]["draft_model"] == "jfan/Qwen3.8-27B-heretic-dflash"
    assert cfg["dflash"]["verify_mode"] == "adaptive"


def test_official_recipe_does_not_pass_unknown_block_size(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")
    from backend.runtime import recipes as rec
    from backend.runtime.mlx_provider import MLXRuntimeProvider
    import backend.runtime.mlx_provider as prov_mod
    monkeypatch.setattr(rec, "_SERVE_FLAGS", frozenset({
        "--model", "--draft-model", "--verify-mode", "--draft-quant",
    }))
    monkeypatch.setattr(prov_mod, "serve_supports", lambda flag: flag in rec._SERVE_FLAGS)
    monkeypatch.setattr(prov_mod, "resolve_path", lambda mid: f"/models/{mid}")
    rec.activate("official_dflash2")
    cfg = cfg_mod.load_config()
    cmd, _ = MLXRuntimeProvider()._build_command("fast", cfg)
    joined = " ".join(cmd)
    assert "--verify-mode adaptive" in joined
    assert "--draft-quant" in joined
    assert "--block-size" not in joined


def test_fast_command_passes_supported_dflash2_cache_flags(monkeypatch):
    from backend.runtime.mlx_provider import MLXRuntimeProvider
    import backend.runtime.mlx_provider as prov_mod
    supported = {
        "--prefill-step-size", "--draft-sink-size", "--draft-window-size",
        "--prefix-cache-l2",
        "--prefix-cache-max-entries", "--prefix-cache-max-bytes",
        "--prefix-cache-l2-max-bytes", "--cache-limit",
    }
    monkeypatch.setattr(prov_mod, "serve_supports", lambda flag: flag in supported)
    monkeypatch.setattr(prov_mod, "resolve_path", lambda mid: f"/models/{mid}")
    cmd, _ = MLXRuntimeProvider()._build_command("fast", cfg_mod.load_config())
    joined = " ".join(cmd)
    assert "--prefill-step-size 2048" in joined
    assert "--draft-sink-size 64" in joined
    assert "--draft-window-size 1024" in joined
    assert "--prefix-cache-l2" in joined
    assert "--prefix-cache-max-entries 4" in joined
    assert "--prefix-cache-max-bytes 8GB" in joined
    assert "--prefix-cache-l2-max-bytes 50GB" in joined
    assert "--cache-limit 4GB" in joined


def test_autotune_candidates_are_generation_aware():
    from backend.benchmark.engine import autotune_candidates
    dflash1 = autotune_candidates("dflash1")
    dflash2 = autotune_candidates("dflash2")
    assert any(c["verify_len_cap"] == 8 for c in dflash1)
    assert all(c["verify_len_cap"] <= 5 for c in dflash2)
    assert {c["verify_len_cap"] for c in dflash2} == {0, 4}


def test_hub_classify_mlx_target_vs_draft_vs_blocked():
    from backend.models.hub import classify

    mlx = classify("mlx-community/Qwen3.8-27B-4bit", tags=["mlx"], library_name="mlx")
    assert mlx["runnable"] and mlx["kind"] == "target"

    draft = classify("jfan/Qwen3.8-27B-heretic-dflash", tags=["mlx"], library_name="mlx")
    assert draft["runnable"] and draft["kind"] == "draft"

    gguf = classify("org/model-GGUF", tags=["gguf"], filenames=["model.Q4_K_M.gguf"])
    assert not gguf["runnable"] and gguf["reason"] == "gguf"

    vision = classify(
        "mlx-community/Qwen3-VL-4B-Instruct-8bit",
        tags=["mlx", "vision"],
        pipeline_tag="image-text-to-text",
        library_name="mlx",
        filenames=["model.safetensors", "model-vision.safetensors"],
    )
    assert not vision["runnable"] and vision["reason"] == "vision"

    qwen36 = classify(
        "lmstudio-community/Qwen3.6-27B-MLX-4bit",
        tags=["mlx", "image-text-to-text", "transformers"],
        pipeline_tag="image-text-to-text",
        library_name="mlx",
        filenames=["model.safetensors", "preprocessor_config.json", "tokenizer.json"],
    )
    assert qwen36["runnable"] and qwen36["kind"] == "target"

    vl_name = classify(
        "mlx-community/Qwen3-VL-4B-Instruct-8bit",
        tags=["mlx"],
        pipeline_tag="image-text-to-text",
        library_name="mlx",
        filenames=["model.safetensors"],
    )
    assert not vl_name["runnable"] and vl_name["reason"] == "vision"

    unknown = classify("someone/random-pt", tags=["pytorch"], filenames=["pytorch_model.bin"])
    assert not unknown["runnable"] and unknown["reason"] == "not_mlx"


def test_hub_list_models_kwargs_match_huggingface_hub_1x():
    from backend.models.hub import list_models_kwargs

    kw = list_models_kwargs("qwen", sort="downloads", limit=24, fmt="mlx")
    assert "direction" not in kw
    assert kw["search"] == "qwen"
    assert kw["filter"] == "mlx"
    assert kw["sort"] == "downloads"
    assert kw["limit"] == 24

    updated = list_models_kwargs("qwen", sort="updated", limit=10, fmt="mlx")
    assert updated["sort"] == "last_modified"
    assert "direction" not in updated

    relevance = list_models_kwargs("qwen", sort="relevance", limit=10, fmt="all")
    assert "sort" not in relevance
    assert "filter" not in relevance

    empty = list_models_kwargs("", sort="downloads", limit=12, fmt="mlx")
    assert empty["search"] is None
    assert empty["filter"] == "mlx"


def test_search_hub_empty_query_returns_mlx_hits(monkeypatch):
    from backend.models import hub as hub_mod

    class Info:
        def __init__(self, repo_id: str):
            self.id = repo_id
            self.tags = ["mlx"]
            self.pipeline_tag = None
            self.library_name = "mlx"
            self.downloads = 9
            self.likes = 1
            self.last_modified = None
            self.siblings = []

    class Api:
        def list_models(self, **kwargs):
            assert "direction" not in kwargs
            assert kwargs.get("filter") == "mlx"
            assert kwargs.get("search") is None
            return [Info("mlx-community/Qwen3.8-27B-4bit")]

        def model_info(self, repo_id):
            return Info(repo_id)

    monkeypatch.setattr(hub_mod, "_local_ids", lambda: set())
    monkeypatch.setattr("huggingface_hub.HfApi", lambda *a, **k: Api())
    out = hub_mod.search_hub("", sort="downloads", limit=8)
    assert out["ok"]
    ids = [row["id"] for row in out["results"]]
    assert ids[0] == "McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit"
    assert "mlx-community/Qwen3.8-27B-4bit" in ids
    assert "jfan/Qwen3.8-27B-heretic-dflash" in ids


def test_library_dir_skips_hf_hub_and_uses_lmstudio_layout(tmp_path, monkeypatch):
    from backend.models import registry as reg

    hub = tmp_path / "huggingface" / "hub"
    hub.mkdir(parents=True)
    lib = tmp_path / "lmstudio" / "models"
    lib.mkdir(parents=True)
    cfg = {
        "model_dirs": [str(hub), str(lib)],
    }
    monkeypatch.setattr(reg, "load_config", lambda: cfg)
    # expand_model_dirs uses cfg from argument via library_dir
    from backend.core import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "load_config", lambda: cfg)
    assert reg.library_dir(cfg) == lib
    dest = reg.library_model_path("mlx-community/Qwen3.8-27B-4bit", cfg)
    assert dest == lib / "mlx-community" / "Qwen3.8-27B-4bit"


def test_set_library_dir_replaces_primary_keeps_hub(tmp_path, monkeypatch):
    from pathlib import Path
    from backend.models import registry as reg
    from backend.core import config as cfg_mod

    old = tmp_path / "old-models"
    new = tmp_path / "new-models"
    hub = tmp_path / "huggingface" / "hub"
    old.mkdir(); new.mkdir(); hub.mkdir(parents=True)
    yaml_path = tmp_path / "config.yaml"
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", yaml_path)
    cfg_mod.save_config({
        **cfg_mod.DEFAULT_CONFIG,
        "model_dirs": [str(old), str(hub)],
    })
    out = reg.set_library_dir(str(new))
    assert out["ok"]
    reloaded = cfg_mod.load_config()
    assert Path(reloaded["model_dirs"][0]).expanduser().resolve() == new.resolve()
    assert any("huggingface" in d and d.endswith("hub") for d in reloaded["model_dirs"])


def test_parse_repo_id_rejects_traversal():
    from backend.models.registry import parse_repo_id
    import pytest
    with pytest.raises(ValueError):
        parse_repo_id("../etc/passwd")
    with pytest.raises(ValueError):
        parse_repo_id("org")
    assert parse_repo_id("McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit") == (
        "McG-221", "Qwen3.8-27B-heretic-ara-mlx-8Bit",
    )


def test_pull_preflight_blocks_gated_only():
    from backend.models.pull import pull_preflight
    import pytest
    pull_preflight({"gated": False, "runnable": False, "reason": "gguf"})
    with pytest.raises(RuntimeError, match="gated"):
        pull_preflight({"gated": True})


def test_safe_relpath_rejects_traversal():
    from backend.models.pull import safe_relpath
    import pytest
    assert safe_relpath("model.safetensors").as_posix() == "model.safetensors"
    assert safe_relpath("nested/a.bin").as_posix() == "nested/a.bin"
    with pytest.raises(ValueError):
        safe_relpath("../escape.bin")
    with pytest.raises(ValueError):
        safe_relpath("/abs.bin")


def test_download_file_resumes_from_part_and_keeps_it_on_failure(tmp_path):
    from backend.models.pull import download_file_resumable, part_path

    dest = tmp_path / "weights.bin"
    part = part_path(dest)
    part.write_bytes(b"hello")

    def fake_http_get(url, handle, *, resume_size=0, expected_size=None, **kwargs):
        assert url.endswith("weights.bin")
        assert resume_size == 5
        handle.write(b" world")

    download_file_resumable(
        "https://example.test/weights.bin",
        dest,
        expected_size=11,
        headers={},
        http_get_fn=fake_http_get,
    )
    assert dest.read_bytes() == b"hello world"
    assert not part.exists()

    dest.unlink()
    part.write_bytes(b"hel")

    def boom(url, handle, *, resume_size=0, expected_size=None, **kwargs):
        assert resume_size == 3
        handle.write(b"lo")
        raise OSError("network down")

    try:
        download_file_resumable(
            "https://example.test/weights.bin",
            dest,
            expected_size=11,
            headers={},
            http_get_fn=boom,
        )
    except OSError:
        pass
    assert not dest.exists()
    assert part.read_bytes() == b"hello"


def test_download_file_skips_complete_dest(tmp_path):
    from backend.models.pull import download_file_resumable

    dest = tmp_path / "done.bin"
    dest.write_bytes(b"abcdef")
    called = {"n": 0}

    def fake_http_get(*a, **k):
        called["n"] += 1

    download_file_resumable(
        "https://example.test/done.bin",
        dest,
        expected_size=6,
        headers={},
        http_get_fn=fake_http_get,
    )
    assert called["n"] == 0
    assert dest.read_bytes() == b"abcdef"


def test_existing_bytes_counts_part_files(tmp_path):
    from backend.models.pull import existing_bytes
    from backend.models.registry import _INCOMPLETE_MARKER

    dest = tmp_path / "org" / "model"
    dest.mkdir(parents=True)
    (dest / "ok.bin").write_bytes(b"xxxx")
    (dest / "rest.bin.part").write_bytes(b"yy")
    (dest / _INCOMPLETE_MARKER).write_text("downloading\n")
    files = [
        {"name": "ok.bin", "size_bytes": 4},
        {"name": "rest.bin", "size_bytes": 10},
    ]
    done, total, partial = existing_bytes(dest, files)
    assert done == 6
    assert total == 14
    assert partial is True


def test_dflash_metrics_inflight_uses_current_request():
    """dflash-mlx 0.1.8 leaves rates.average_* null while a request is decoding."""
    from backend.monitoring.sampler import runtime_fields_from_dflash

    fields = runtime_fields_from_dflash({
        "current_request": {
            "acceptance_rate": 0.5423654015887026,
            "decode_tok_s": 20.918627526758325,
            "prefill_s": 0.699908375,
            "prefill_tokens_processed": 68,
            "request_id": 1,
            "state": "decode",
            "ttft_s": 0.700856,
            "cache_status": "COLD",
            "tokens_per_cycle": 3.4,
            "cycles": 7,
            "adaptive_block": 5,
        },
        "last_request": None,
        "memory": {"rss_gb": 32.716488704},
        "rates": {
            "active_decode_tok_s": 20.918627526758325,
            "average_decode_tok_s": None,
            "generated_tokens_per_s": 0.0,
            "prefill_tokens_physical_per_s": 0.0,
        },
        "recent_requests": [],
        "totals": {"requests": 0},
    })
    assert fields["active_request"] is True
    assert abs(fields["decode_tok_s"] - 20.918627526758325) < 1e-9
    assert abs(fields["acceptance_rate"] - 0.5423654015887026) < 1e-9
    assert abs(fields["ttft_s"] - 0.700856) < 1e-9
    assert abs(fields["prefill_tok_s"] - (68 / 0.699908375)) < 1e-6
    assert abs(fields["rss_gb"] - 32.716488704) < 1e-9
    assert fields["raw"]["cache_status"] == "COLD"
    assert fields["raw"]["tokens_per_cycle"] == 3.4
    assert fields["raw"]["cycles"] == 7
    assert fields["raw"]["adaptive_block"] == 5


def test_dflash_metrics_legacy_recent_requests():
    from backend.monitoring.sampler import runtime_fields_from_dflash

    fields = runtime_fields_from_dflash({
        "rss_gb": 12.5,
        "rates": {
            "average_decode_tok_s": 31.2,
            "prefill_tok_s_physical": 800.0,
        },
        "current_request": None,
        "recent_requests": [
            {"acceptance_rate": 68.0, "ttft_s": 0.4, "decode_tok_s": 30.0},
            {"acceptance_rate": 72.0, "ttft_s": 0.6, "decode_tok_s": 32.0},
        ],
    })
    assert fields["active_request"] is False
    assert fields["decode_tok_s"] == 31.2
    assert fields["prefill_tok_s"] == 800.0
    assert fields["rss_gb"] == 12.5
    assert abs(fields["acceptance_rate"] - 0.72) < 1e-9
    assert abs(fields["ttft_s"] - 0.6) < 1e-9
    assert fields["requests_completed"] == 2


def test_pretty_alias_from_heretic_and_official_targets():
    from backend.core.alias import pretty_alias, sanitize_alias

    assert pretty_alias("McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit") == "Qwen3.8-27B-Heretic-8bit"
    assert pretty_alias("mlx-community/Qwen3.8-27B-4bit") == "Qwen3.8-27B-4bit"
    assert pretty_alias("lmstudio-community/Qwen3.6-27B-MLX-4bit") == "Qwen3.6-27B-4bit"
    assert pretty_alias("foo/Llama-3.2-3B-Instruct-4bit") == "Llama-3.2-3B-Instruct-4bit"
    assert sanitize_alias(" Qwen 3.8 ") == "Qwen-3.8"
    with pytest.raises(ValueError):
        sanitize_alias("")
    with pytest.raises(ValueError):
        sanitize_alias("本地模型")


def test_sync_alias_auto_and_manual_lock(tmp_path, monkeypatch):
    from backend.core import alias as alias_mod
    from backend.core import config as cfg_mod
    import backend.core.state as state_mod

    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(state_mod, "STATE_PATH", tmp_path / "runtime_state.json")
    cfg_mod.save_config(cfg_mod.load_config())

    cfg = alias_mod.sync_alias_for_target("mlx-community/Qwen3.8-27B-4bit")
    assert cfg["api"]["alias"] == "Qwen3.8-27B-4bit"
    assert cfg["api"]["alias_auto"] is True

    alias_mod.apply_alias("my-local", auto=False)
    cfg = alias_mod.sync_alias_for_target("McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit")
    assert cfg["api"]["alias"] == "my-local"

    cfg = alias_mod.sync_alias_for_target(
        "McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit", force=True
    )
    assert cfg["api"]["alias"] == "Qwen3.8-27B-Heretic-8bit"
    assert cfg["api"]["alias_auto"] is True


def test_delete_library_folder_refuses_escape(tmp_path, monkeypatch):
    from backend.models import registry as reg

    lib = tmp_path / "library"
    lib.mkdir()
    monkeypatch.setattr(reg, "library_dir", lambda cfg=None: lib)
    monkeypatch.setattr(reg, "forget_model", lambda mid: None)
    dest = lib / "org" / "name"
    dest.mkdir(parents=True)
    (dest / "weights.safetensors").write_bytes(b"x")
    monkeypatch.setattr(reg, "library_model_path", lambda repo_id, cfg=None: lib / "org" / "name")
    removed = reg.delete_library_folder("org/name")
    assert "org" in removed
    assert not dest.exists()

    outside = tmp_path / "other" / "x" / "y"
    monkeypatch.setattr(reg, "library_model_path", lambda repo_id, cfg=None: outside)
    with pytest.raises(ValueError):
        reg.delete_library_folder("x/y")


def test_complete_library_model_rejects_partial_folder(tmp_path, monkeypatch):
    from backend.models import registry as reg

    dest = tmp_path / "org" / "model"
    dest.mkdir(parents=True)
    (dest / "config.json").write_text("{}")
    (dest / "weights.safetensors").write_bytes(b"complete")
    monkeypatch.setattr(reg, "library_model_path", lambda repo_id, cfg=None: dest)
    assert reg.is_complete_library_model("org/model") is True
    (dest / "extra.safetensors.part").write_bytes(b"partial")
    assert reg.is_complete_library_model("org/model") is False


def test_clear_download_partials_preserves_completed_model_files(tmp_path, monkeypatch):
    import asyncio
    from backend.core import config as cfg_mod
    from backend.models import pull as pull_mod

    repo = tmp_path / "org" / "model"
    repo.mkdir(parents=True)
    config = repo / "config.json"
    weights = repo / "weights.safetensors"
    partial = repo / "tokenizer.json.part"
    marker = repo / ".download-incomplete"
    config.write_text("{}")
    weights.write_bytes(b"complete")
    partial.write_bytes(b"partial")
    marker.write_text("downloading")

    monkeypatch.setattr(cfg_mod, "DOWNLOADS_PATH", tmp_path / "downloads.json")
    monkeypatch.setattr(pull_mod, "library_model_path", lambda rid, cfg=None: repo)
    monkeypatch.setattr(pull_mod, "library_status", lambda cfg=None: {"library": str(tmp_path)})
    monkeypatch.setattr("backend.models.registry.discover_incomplete_repos", lambda cfg=None: [])
    manager = pull_mod.PullJobManager()
    manager.items = {
        "org/model": manager._blank_item("org/model", None, repo),
    }
    manager.items["org/model"]["status"] = "paused"

    before = manager.snapshot()["items"][0]
    assert before["has_partial_files"] is True
    assert before["has_complete_model"] is False
    result = asyncio.run(manager.clear_partials("org/model"))

    assert result["ok"] is True
    assert not partial.exists()
    assert not marker.exists()
    assert config.exists()
    assert weights.read_bytes() == b"complete"
    assert "org/model" not in manager.items


def test_full_model_delete_requires_exact_installed_scope():
    import asyncio
    from fastapi import HTTPException
    from backend.api import routes

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.models_delete(routes.DeleteModelBody(model_id="org/model")))
    assert exc.value.status_code == 422
    assert "exact confirm_model_id" in str(exc.value.detail)


def test_pull_manager_queues_second_download(tmp_path, monkeypatch):
    from backend.core import config as cfg_mod
    from backend.models import pull as pull_mod

    monkeypatch.setattr(cfg_mod, "DOWNLOADS_PATH", tmp_path / "downloads.json")
    monkeypatch.setattr(pull_mod, "library_model_path", lambda rid, cfg=None: tmp_path / rid.replace("/", "_"))
    monkeypatch.setattr(pull_mod, "library_status", lambda cfg=None: {"library": str(tmp_path)})
    monkeypatch.setattr("backend.models.registry.discover_incomplete_repos", lambda cfg=None: [])
    mgr = pull_mod.PullJobManager()
    mgr.items = {}
    mgr._queue = []
    mgr._task = type("T", (), {"done": lambda self: False})()
    mgr._active_id = "org/one"
    mgr.items["org/one"] = mgr._blank_item("org/one", None, tmp_path / "one")
    mgr.items["org/one"]["status"] = "running"
    out = mgr.start("org/two")
    assert out["ok"] is True
    assert out["queued"] is True
    assert mgr.items["org/two"]["status"] == "queued"
    assert "org/two" in mgr._queue
    paused = mgr.pause("org/two")
    assert paused["ok"] is True
    assert mgr.items["org/two"]["status"] == "paused"
    assert "org/two" not in mgr._queue

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

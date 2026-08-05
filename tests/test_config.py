"""配置加载测试：环境变量注入、缺配置报错。"""

import pytest

from app.config import load_config, _resolve_env_var, ConfigError


def test_resolve_env_var(monkeypatch):
    monkeypatch.setenv("TEST_KEY_XYZ", "secret123")
    assert _resolve_env_var("$TEST_KEY_XYZ") == "secret123"
    assert _resolve_env_var("${TEST_KEY_XYZ}") == "secret123"
    assert _resolve_env_var("$MISSING_VAR_XYZ") == ""
    assert _resolve_env_var("ollama") == "ollama"  # 非引用原样返回
    assert _resolve_env_var("") == ""


def test_load_config_real_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "k1")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "default_model: m1\n"
        "default_max_tokens: 1024\n"
        "default_temperature: 0.3\n"
        "max_retries: 5\n"
        "request_timeout: 30\n"
        "providers:\n"
        "  - name: p1\n"
        "    base_url: http://x/v1\n"
        "    api_key: $TEST_API_KEY\n"
        "    models: [m1, m2]\n"
    )
    cfg = load_config(str(cfg_file))
    assert cfg.default_model == "m1"
    assert cfg.default_max_tokens == 1024
    assert cfg.max_retries == 5
    assert cfg.available_models == ["m1", "m2"]
    assert cfg.get_provider_for_model("m2").name == "p1"


def test_load_config_skips_provider_without_key(tmp_path):
    """api_key 引用未设置的环境变量 → 该 provider 静默跳过。"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "default_model: m1\n"
        "providers:\n"
        "  - name: p1\n"
        "    base_url: http://x/v1\n"
        "    api_key: $UNSET_KEY_ABC\n"
        "    models: [m1]\n"
    )
    with pytest.raises(ConfigError, match="api_key"):
        load_config(str(cfg_file))


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="不存在"):
        load_config(str(tmp_path / "nope.yaml"))


def test_load_config_bad_yaml(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("providers: [unclosed")
    with pytest.raises(ConfigError, match="格式错误"):
        load_config(str(cfg_file))


def test_load_config_no_providers(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("default_model: m1\nproviders: []\n")
    with pytest.raises(ConfigError, match="providers"):
        load_config(str(cfg_file))


def test_load_config_default_model_missing(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "default_model: ghost\n"
        "providers:\n"
        "  - name: p1\n"
        "    base_url: http://x/v1\n"
        "    api_key: plain-key\n"
        "    models: [m1]\n"
    )
    with pytest.raises(ConfigError, match="default_model"):
        load_config(str(cfg_file))

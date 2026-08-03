"""
配置加载器——读取 config.yaml，解析多模型网关配置，启动时校验。

职责：
1. 读取并解析 config.yaml
2. 解析 ${ENV_VAR} / $ENV_VAR 环境变量注入
3. 按 default_model 定位目标 provider
4. 校验：没有可用 API key → 拒绝启动
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ── 配置数据类 ──────────────────────────────────────────────

@dataclass
class ProviderConfig:
    """单个 provider 的配置"""
    name: str
    base_url: str
    api_key: str                  # 已解析后的真实 key
    models: list[str] = field(default_factory=list)


@dataclass
class ModelGatewayConfig:
    """解析后的完整模型网关配置"""
    default_model: str
    default_max_tokens: int
    default_temperature: float
    max_retries: int
    request_timeout: int
    providers: list[ProviderConfig]
    
    # 快捷查询
    _provider_by_name: dict[str, ProviderConfig] = field(default_factory=dict)
    _model_to_provider: dict[str, ProviderConfig] = field(default_factory=dict)

    def get_provider_for_model(self, model: str | None = None) -> ProviderConfig:
        """根据 model 名定位 provider。

        查找顺序：指定 model → default_model
        """
        target = model or self.default_model
        provider = self._model_to_provider.get(target)
        if provider is None:
            raise ConfigError(
                f"模型 '{target}' 未在任何 provider 中配置。"
                f" 可用的模型: {list(self._model_to_provider.keys())}"
            )
        return provider

    @property
    def available_models(self) -> list[str]:
        return list(self._model_to_provider.keys())


# ── 错误 ────────────────────────────────────────────────────

class ConfigError(Exception):
    """配置校验失败"""


# ── 加载入口 ────────────────────────────────────────────────

def load_config(config_path: str = "config.yaml") -> ModelGatewayConfig:
    """加载并校验模型网关配置。

    Args:
        config_path: 配置文件路径

    Returns:
        解析后的 ModelGatewayConfig

    Raises:
        ConfigError: 配置缺失、格式错误或没有可用的 API key
    """
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(
            f"配置文件不存在: {path.absolute()}\n"
            f"请参考 config.yaml.example 创建配置文件，至少配置一个 provider 的 api_key。"
        )

    # 1. 解析 YAML
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ConfigError(f"配置文件格式错误（非合法 YAML）: {e}") from e

    if raw is None:
        raise ConfigError(f"配置文件为空: {path.absolute()}")

    # 2. 解析 provider 列表
    providers_raw: list[dict] = raw.get("providers", [])
    if not providers_raw:
        raise ConfigError("config.yaml 中未配置任何 providers，至少需要一个。")

    providers: list[ProviderConfig] = []
    model_to_provider: dict[str, ProviderConfig] = {}

    for p in providers_raw:
        name = p.get("name", "")
        base_url = p.get("base_url", "")
        raw_api_key = p.get("api_key", "")
        models = p.get("models", [])

        # 解析环境变量
        api_key = _resolve_env_var(raw_api_key)

        # 跳过未设置环境变量的 provider（静默降级）
        if not api_key:
            continue

        provider = ProviderConfig(
            name=name,
            base_url=base_url,
            api_key=api_key,
            models=models,
        )
        providers.append(provider)

        for m in models:
            model_to_provider[m] = provider

    # 3. 校验：至少有一个可用的 provider
    if not providers:
        # 给出具体帮助信息
        configured = [p.get("name", "?") for p in providers_raw]
        env_vars = []
        for p in providers_raw:
            raw_k = p.get("api_key", "")
            match = re.match(r"^\$(\w+)", raw_k)
            if match:
                env_vars.append(match.group(1))
        hint = ""
        if env_vars:
            hint = f"\n需要设置环境变量: {' '.join(env_vars)}"
        raise ConfigError(
            f"所有 provider 的 api_key 均不可用。已配置: {configured}。{hint}"
        )

    # 4. 校验 default_model 存在
    default_model = raw.get("default_model", "")
    if default_model not in model_to_provider:
        raise ConfigError(
            f"default_model '{default_model}' 不在任何可用 provider 的 models 列表中。"
            f" 可用: {list(model_to_provider.keys())}"
        )

    config = ModelGatewayConfig(
        default_model=default_model,
        default_max_tokens=raw.get("default_max_tokens", 2048),
        default_temperature=raw.get("default_temperature", 0.7),
        max_retries=raw.get("max_retries", 3),
        request_timeout=raw.get("request_timeout", 60),
        providers=providers,
    )
    # 填充快捷索引
    config._provider_by_name = {p.name: p for p in providers}
    config._model_to_provider = model_to_provider

    return config


def _resolve_env_var(value: str) -> str:
    """解析 ${VAR} 或 $VAR 格式的环境变量引用。

    Args:
        value: 原始值，如 "$DEEPSEEK_API_KEY" 或 "ollama"

    Returns:
        解析后的值。如果引用了一个不存在的环境变量，返回空字符串。
    """
    match = re.match(r"^\$\{?(\w+)\}?$", value.strip())
    if match:
        return os.environ.get(match.group(1), "")
    return value

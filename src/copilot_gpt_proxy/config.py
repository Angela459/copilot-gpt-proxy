from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILE_NAME = "config.yaml"
REASONING_CONTENT_FILE_NAME = "reasoning_content.sqlite3"

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}
MISSING = object()

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000
DEFAULT_UPSTREAM_BASE_URL = "https://api.deepseek.com"
DEFAULT_UPSTREAM_MODEL = "deepseek-v4-pro"
DEFAULT_THINKING = "enabled"
DEFAULT_REASONING_EFFORT = "max"
DEFAULT_DISPLAY_REASONING = True
DEFAULT_COLLAPSIBLE_REASONING = True
DEFAULT_VERBOSE = False
DEFAULT_REQUEST_TIMEOUT = 300.0
DEFAULT_MAX_REQUEST_BODY_BYTES = 20 * 1024 * 1024
DEFAULT_CORS = False
DEFAULT_MISSING_REASONING_STRATEGY = "recover"
DEFAULT_EMPTY_APPLY_PATCH = "retry_once"
DEFAULT_MAX_TOOL_RETRIES = 1
DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
DEFAULT_REASONING_CACHE_MAX_ROWS = 100_000

DEFAULT_CONFIG_HEADER = (
    "# This file was created automatically in the current directory."
)
DEFAULT_CONFIG_TEXT = f"""{DEFAULT_CONFIG_HEADER}
# API keys are read from Copilot's Authorization header and forwarded upstream.

# `model` is the default alias when a request has no model.
model: {DEFAULT_UPSTREAM_MODEL}
providers:
  DeepSeek:
    base_url: {DEFAULT_UPSTREAM_BASE_URL}
models:
  DeepSeek:
    - {DEFAULT_UPSTREAM_MODEL}
thinking: {DEFAULT_THINKING}
reasoning_effort: {DEFAULT_REASONING_EFFORT}
display_reasoning: {str(DEFAULT_DISPLAY_REASONING).lower()}
collasible_reasoning: {str(DEFAULT_COLLAPSIBLE_REASONING).lower()}

host: {DEFAULT_HOST}
port: {DEFAULT_PORT}
verbose: {str(DEFAULT_VERBOSE).lower()}
request_timeout: {DEFAULT_REQUEST_TIMEOUT:g}
max_request_body_bytes: {DEFAULT_MAX_REQUEST_BODY_BYTES}
cors: {str(DEFAULT_CORS).lower()}
empty_apply_patch: {DEFAULT_EMPTY_APPLY_PATCH}
max_tool_retries: {DEFAULT_MAX_TOOL_RETRIES}

reasoning_content_path: {REASONING_CONTENT_FILE_NAME}
missing_reasoning_strategy: {DEFAULT_MISSING_REASONING_STRATEGY}
reasoning_cache_max_age_seconds: {DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS}
reasoning_cache_max_rows: {DEFAULT_REASONING_CACHE_MAX_ROWS}
"""


def default_config_path() -> Path:
    return Path.cwd() / CONFIG_FILE_NAME


def default_reasoning_content_path() -> Path:
    return Path.cwd() / REASONING_CONTENT_FILE_NAME


def populate_default_config_file(config_path: Path) -> None:
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path.parent.chmod(0o700)
    config_path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    config_path.chmod(0o600)


def load_config_file(config_path: str | Path) -> dict[str, Any]:
    config_path = Path(config_path).expanduser()
    if not config_path.exists():
        return {}

    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML config at {config_path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"Config file must contain a YAML mapping: {config_path}")
    return dict(loaded)


def resolve_config_path(config_path: str | Path | None) -> Path:
    return Path(config_path or default_config_path()).expanduser()


def setting_value(settings: Mapping[str, Any], key: str) -> Any:
    return settings.get(key, MISSING)


def setting_value_any(settings: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = setting_value(settings, key)
        if value is not MISSING:
            return value
    return MISSING


def as_str(value: Any, default: str) -> str:
    if value is MISSING or value is None:
        return default
    return str(value)


def as_bool(value: Any, default: bool) -> bool:
    if value is MISSING or value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def as_int(value: Any, default: int) -> int:
    if value is MISSING or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float) -> float:
    if value is MISSING or value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_path(value: Any, default_path: Path, relative_base: Path) -> Path:
    if value is MISSING or value is None or value == "":
        return default_path
    candidate_path = Path(str(value)).expanduser()
    if candidate_path.is_absolute():
        return candidate_path
    return relative_base / candidate_path


def settings_from_config(
    config_path: str | Path | None,
) -> tuple[dict[str, Any], Path]:
    resolved_config_path = resolve_config_path(config_path)
    if config_path is None and not resolved_config_path.exists():
        populate_default_config_file(resolved_config_path)
    return load_config_file(resolved_config_path), resolved_config_path


def normalize_thinking(value: Any) -> str:
    thinking = as_str(value, DEFAULT_THINKING).strip().lower()
    if thinking in {"enabled", "disabled"}:
        return thinking
    return DEFAULT_THINKING


def normalize_missing_reasoning_strategy(value: Any) -> str:
    strategy = as_str(value, DEFAULT_MISSING_REASONING_STRATEGY).strip().lower()
    if strategy in {"recover", "reject"}:
        return strategy
    return DEFAULT_MISSING_REASONING_STRATEGY


def normalize_empty_apply_patch(value: Any) -> str:
    strategy = as_str(value, DEFAULT_EMPTY_APPLY_PATCH).strip().lower()
    if strategy in {"retry_once", "reject", "allow"}:
        return strategy
    return DEFAULT_EMPTY_APPLY_PATCH


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str


@dataclass(frozen=True)
class ModelRoute:
    alias: str
    provider: str
    upstream_model: str


@dataclass(frozen=True)
class ResolvedRoute:
    requested_model: str
    provider: str
    upstream_base_url: str
    upstream_model: str


class UnknownModelError(ValueError):
    pass


def parse_providers(value: Any) -> dict[str, ProviderConfig]:
    if value is MISSING or value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("`providers` must be a YAML mapping")

    providers: dict[str, ProviderConfig] = {}
    for raw_name, raw_provider in value.items():
        name = str(raw_name).strip()
        if not name:
            raise ValueError("Provider names must not be empty")
        if not isinstance(raw_provider, Mapping):
            raise ValueError(f"Provider {name!r} must be a YAML mapping")
        if "api_key" in raw_provider or "api_key_env" in raw_provider:
            raise ValueError(
                f"Provider {name!r} must not configure an API key; "
                "set it in GitHub Copilot App"
            )
        base_url = str(raw_provider.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            raise ValueError(f"Provider {name!r} requires `base_url`")
        providers[name] = ProviderConfig(
            name=name,
            base_url=base_url,
        )
    return providers


def parse_model_routes(
    value: Any,
    providers: Mapping[str, ProviderConfig],
) -> dict[str, ModelRoute]:
    if value is MISSING or value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("`models` must be a YAML mapping")
    if not providers:
        raise ValueError("`models` requires at least one configured provider")

    routes: dict[str, ModelRoute] = {}
    grouped = all(isinstance(models, list) for models in value.values())
    legacy = all(isinstance(route, Mapping) for route in value.values())
    if not grouped and not legacy:
        raise ValueError("`models` must group model-name lists by provider name")

    if grouped:
        for raw_provider, raw_models in value.items():
            provider = str(raw_provider).strip()
            if provider not in providers:
                raise ValueError(f"Models reference unknown provider {provider!r}")
            for raw_model in raw_models:
                if not isinstance(raw_model, str) or not raw_model.strip():
                    raise ValueError(
                        f"Provider {provider!r} contains an invalid model name"
                    )
                model = raw_model.strip()
                if model in routes:
                    raise ValueError(
                        f"Model {model!r} is configured under multiple providers"
                    )
                routes[model] = ModelRoute(
                    alias=model,
                    provider=provider,
                    upstream_model=model,
                )
        return routes

    for raw_alias, raw_route in value.items():
        alias = str(raw_alias).strip()
        if not alias:
            raise ValueError("Legacy model aliases must not be empty")
        provider = str(raw_route.get("provider") or "").strip()
        if provider not in providers:
            raise ValueError(
                f"Model route {alias!r} references unknown provider {provider!r}"
            )
        upstream_model = str(raw_route.get("model") or alias).strip()
        if not upstream_model:
            raise ValueError(f"Model route {alias!r} requires a model name")
        routes[alias] = ModelRoute(alias, provider, upstream_model)
    return routes


@dataclass(frozen=True)
class ProxyConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    upstream_base_url: str = DEFAULT_UPSTREAM_BASE_URL
    upstream_model: str = DEFAULT_UPSTREAM_MODEL
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    model_routes: dict[str, ModelRoute] = field(default_factory=dict)
    thinking: str = DEFAULT_THINKING
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES
    reasoning_content_path: Path = field(default_factory=default_reasoning_content_path)
    missing_reasoning_strategy: str = DEFAULT_MISSING_REASONING_STRATEGY
    empty_apply_patch: str = DEFAULT_EMPTY_APPLY_PATCH
    max_tool_retries: int = DEFAULT_MAX_TOOL_RETRIES
    reasoning_cache_max_age_seconds: int = DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS
    reasoning_cache_max_rows: int = DEFAULT_REASONING_CACHE_MAX_ROWS
    display_reasoning: bool = DEFAULT_DISPLAY_REASONING
    collapsible_reasoning: bool = DEFAULT_COLLAPSIBLE_REASONING
    cors: bool = DEFAULT_CORS
    verbose: bool = DEFAULT_VERBOSE
    trace_dir: Path | None = None

    def resolve_route(self, requested_model: str | None = None) -> ResolvedRoute:
        model = str(requested_model or self.upstream_model).strip()
        if self.model_routes:
            route = self.model_routes.get(model)
            if route is None:
                available = ", ".join(self.model_routes)
                raise UnknownModelError(
                    f"Unknown model {model!r}; configured models: {available}"
                )
            provider = self.providers[route.provider]
            return ResolvedRoute(
                requested_model=model,
                provider=provider.name,
                upstream_base_url=provider.base_url,
                upstream_model=route.upstream_model,
            )

        upstream_model = model if model.startswith("deepseek-") else self.upstream_model
        return ResolvedRoute(
            requested_model=model,
            provider="default",
            upstream_base_url=self.upstream_base_url,
            upstream_model=upstream_model,
        )

    def available_models(self) -> list[str]:
        if self.model_routes:
            return list(self.model_routes)
        return list(
            dict.fromkeys([self.upstream_model, "deepseek-v4-pro", "deepseek-v4-flash"])
        )

    @classmethod
    def from_file(
        cls: type[ProxyConfig],
        config_path: str | Path | None = None,
    ) -> "ProxyConfig":
        settings, resolved_config_path = settings_from_config(config_path)
        config_dir = resolved_config_path.parent

        if "api_key" in settings or "api_key_env" in settings:
            raise ValueError(
                "API keys must not be configured in config.yaml; "
                "set them in GitHub Copilot App"
            )

        providers = parse_providers(setting_value(settings, "providers"))
        model_routes = parse_model_routes(setting_value(settings, "models"), providers)
        configured_model = setting_value(settings, "model")
        if model_routes:
            upstream_model = (
                next(iter(model_routes))
                if configured_model is MISSING
                else as_str(configured_model, next(iter(model_routes))).strip()
            )
            if upstream_model not in model_routes:
                raise ValueError(
                    f"Default model {upstream_model!r} is not defined in `models`"
                )
            default_route = model_routes[upstream_model]
            upstream_base_url = providers[default_route.provider].base_url
        else:
            upstream_model = as_str(configured_model, DEFAULT_UPSTREAM_MODEL)
            upstream_base_url = as_str(
                setting_value(settings, "base_url"),
                DEFAULT_UPSTREAM_BASE_URL,
            ).rstrip("/")

        return cls(
            host=as_str(
                setting_value(settings, "host"),
                DEFAULT_HOST,
            ),
            port=as_int(
                setting_value(settings, "port"),
                DEFAULT_PORT,
            ),
            upstream_base_url=upstream_base_url,
            upstream_model=upstream_model,
            providers=providers,
            model_routes=model_routes,
            thinking=normalize_thinking(setting_value(settings, "thinking")),
            reasoning_effort=as_str(
                setting_value(settings, "reasoning_effort"),
                DEFAULT_REASONING_EFFORT,
            ),
            request_timeout=as_float(
                setting_value(settings, "request_timeout"),
                DEFAULT_REQUEST_TIMEOUT,
            ),
            max_request_body_bytes=as_int(
                setting_value(settings, "max_request_body_bytes"),
                DEFAULT_MAX_REQUEST_BODY_BYTES,
            ),
            reasoning_content_path=as_path(
                setting_value(settings, "reasoning_content_path"),
                default_reasoning_content_path(),
                config_dir,
            ),
            missing_reasoning_strategy=normalize_missing_reasoning_strategy(
                setting_value(settings, "missing_reasoning_strategy")
            ),
            empty_apply_patch=normalize_empty_apply_patch(
                setting_value(settings, "empty_apply_patch")
            ),
            max_tool_retries=max(
                0,
                min(
                    1,
                    as_int(
                        setting_value(settings, "max_tool_retries"),
                        DEFAULT_MAX_TOOL_RETRIES,
                    ),
                ),
            ),
            reasoning_cache_max_age_seconds=as_int(
                setting_value(settings, "reasoning_cache_max_age_seconds"),
                DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS,
            ),
            reasoning_cache_max_rows=as_int(
                setting_value(settings, "reasoning_cache_max_rows"),
                DEFAULT_REASONING_CACHE_MAX_ROWS,
            ),
            display_reasoning=as_bool(
                setting_value(settings, "display_reasoning"),
                DEFAULT_DISPLAY_REASONING,
            ),
            collapsible_reasoning=as_bool(
                setting_value_any(
                    settings,
                    "collasible_reasoning",
                    "collapsible_reasoning",
                ),
                DEFAULT_COLLAPSIBLE_REASONING,
            ),
            cors=as_bool(
                setting_value(settings, "cors"),
                DEFAULT_CORS,
            ),
            verbose=as_bool(
                setting_value(settings, "verbose"),
                DEFAULT_VERBOSE,
            ),
        )

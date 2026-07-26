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
DEFAULT_CONFIG_VERSION = 1

DEFAULT_CONFIG_HEADER = (
    "# This file was created automatically in the current directory."
)
DEFAULT_CONFIG_TEXT = f"""{DEFAULT_CONFIG_HEADER}
# API keys are read from Copilot's Authorization header and forwarded upstream.

# `default_model` is the alias used when a request has no model.
config_version: {DEFAULT_CONFIG_VERSION}
default_model: {DEFAULT_UPSTREAM_MODEL}
api_providers:
  - name: deepseek
    base_url: {DEFAULT_UPSTREAM_BASE_URL}
models:
  - name: {DEFAULT_UPSTREAM_MODEL}
    model_identifier: {DEFAULT_UPSTREAM_MODEL}
    api_provider: deepseek
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


def parse_config_version(value: Any) -> int:
    if value is MISSING or value is None:
        return DEFAULT_CONFIG_VERSION
    if isinstance(value, bool):
        raise ValueError("config_version must be an integer")
    try:
        version = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("config_version must be an integer") from exc
    if version != DEFAULT_CONFIG_VERSION:
        raise ValueError(
            f"Unsupported config_version {version}; expected {DEFAULT_CONFIG_VERSION}"
        )
    return version


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str | None = None


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
    api_key_env: str | None = None


class UnknownModelError(ValueError):
    pass


def parse_providers(value: Any) -> dict[str, ProviderConfig]:
    if value is MISSING or value is None:
        return {}
    if isinstance(value, Mapping):
        items = [
            dict(provider, name=name)
            for name, provider in value.items()
            if isinstance(provider, Mapping)
        ]
        if len(items) != len(value):
            raise ValueError("Each legacy `providers` entry must be a YAML mapping")
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError("`api_providers` must be a YAML list")

    providers: dict[str, ProviderConfig] = {}
    for raw_provider in items:
        if not isinstance(raw_provider, Mapping):
            raise ValueError("Each `api_providers` entry must be a YAML mapping")
        name = str(raw_provider.get("name") or "").strip()
        if not name:
            raise ValueError("Each API provider requires a non-empty `name`")
        if name in providers:
            raise ValueError(f"Duplicate API provider name {name!r}")
        if "api_key" in raw_provider:
            raise ValueError(
                f"Provider {name!r} must use `api_key_env`; plaintext `api_key` "
                "is not supported"
            )
        base_url = str(raw_provider.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            raise ValueError(f"Provider {name!r} requires `base_url`")
        raw_api_key_env = raw_provider.get("api_key_env")
        api_key_env = (
            str(raw_api_key_env).strip() if raw_api_key_env is not None else None
        )
        if api_key_env == "":
            api_key_env = None
        providers[name] = ProviderConfig(
            name=name,
            base_url=base_url,
            api_key_env=api_key_env,
        )
    return providers


def parse_model_routes(
    value: Any,
    providers: Mapping[str, ProviderConfig],
) -> dict[str, ModelRoute]:
    if value is MISSING or value is None:
        return {}
    if isinstance(value, Mapping):
        items = [
            dict(route, name=alias)
            for alias, route in value.items()
            if isinstance(route, Mapping)
        ]
        if len(items) != len(value):
            raise ValueError("Each legacy `models` entry must be a YAML mapping")
        legacy = True
    elif isinstance(value, list):
        items = value
        legacy = False
    else:
        raise ValueError("`models` must be a YAML list")
    if not providers:
        raise ValueError("`models` requires at least one configured provider")

    routes: dict[str, ModelRoute] = {}
    for raw_route in items:
        if not isinstance(raw_route, Mapping):
            raise ValueError("Each `models` entry must be a YAML mapping")
        alias = str(raw_route.get("name") or "").strip()
        if not alias:
            raise ValueError("Each model requires a non-empty `name`")
        if alias in routes:
            raise ValueError(f"Duplicate model name {alias!r}")
        provider_key = "provider" if legacy else "api_provider"
        model_key = "model" if legacy else "model_identifier"
        provider = str(raw_route.get(provider_key) or "").strip()
        if provider not in providers:
            raise ValueError(
                f"Model route {alias!r} references unknown provider {provider!r}"
            )
        upstream_model = str(raw_route.get(model_key) or alias).strip()
        if not upstream_model:
            raise ValueError(f"Model route {alias!r} requires a model name")
        routes[alias] = ModelRoute(
            alias=alias,
            provider=provider,
            upstream_model=upstream_model,
        )
    return routes


@dataclass(frozen=True)
class ProxyConfig:
    config_version: int = DEFAULT_CONFIG_VERSION
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
                api_key_env=provider.api_key_env,
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

        config_version = parse_config_version(setting_value(settings, "config_version"))
        providers_value = setting_value_any(settings, "api_providers", "providers")
        providers = parse_providers(providers_value)
        model_routes = parse_model_routes(setting_value(settings, "models"), providers)
        if providers and not model_routes:
            raise ValueError("`api_providers` requires at least one configured model")
        configured_model = setting_value_any(settings, "default_model", "model")
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
            config_version=config_version,
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

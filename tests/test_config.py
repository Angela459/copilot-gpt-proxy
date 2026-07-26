from __future__ import annotations

import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from copilot_gpt_proxy.config import (
    DEFAULT_COLLAPSIBLE_REASONING,
    DEFAULT_EMPTY_APPLY_PATCH,
    DEFAULT_MAX_TOOL_RETRIES,
    DEFAULT_MISSING_REASONING_STRATEGY,
    DEFAULT_PORT,
    DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS,
    DEFAULT_REASONING_CACHE_MAX_ROWS,
    DEFAULT_THINKING,
    DEFAULT_UPSTREAM_MODEL,
    DEFAULT_VERBOSE,
    ModelRoute,
    ProviderConfig,
    ProxyConfig,
    UnknownModelError,
    default_config_path,
    default_reasoning_content_path,
)


class ConfigTests(unittest.TestCase):
    def test_default_paths_live_in_current_directory(self) -> None:
        project_dir = Path("/tmp/copilot-gpt-proxy")

        with patch("copilot_gpt_proxy.config.Path.cwd", return_value=project_dir):
            self.assertEqual(default_config_path(), project_dir / "config.yaml")
            self.assertEqual(
                default_reasoning_content_path(),
                project_dir / "reasoning_content.sqlite3",
            )
            self.assertEqual(
                ProxyConfig().reasoning_content_path,
                project_dir / "reasoning_content.sqlite3",
            )
            self.assertEqual(
                ProxyConfig().collapsible_reasoning,
                DEFAULT_COLLAPSIBLE_REASONING,
            )
            self.assertIsNone(ProxyConfig().trace_dir)
            self.assertEqual(ProxyConfig().empty_apply_patch, DEFAULT_EMPTY_APPLY_PATCH)
            self.assertEqual(ProxyConfig().max_tool_retries, DEFAULT_MAX_TOOL_RETRIES)

    def test_missing_default_config_file_is_populated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)

            with patch("copilot_gpt_proxy.config.Path.cwd", return_value=project_dir):
                config = ProxyConfig.from_file(config_path=None)
                config_path = default_config_path()

            config_text = config_path.read_text(encoding="utf-8")

            self.assertTrue(config_path.exists())
            self.assertIn(f"model: {DEFAULT_UPSTREAM_MODEL}", config_text)
            self.assertIn(
                f"missing_reasoning_strategy: {DEFAULT_MISSING_REASONING_STRATEGY}",
                config_text,
            )
            self.assertIn(
                "reasoning_cache_max_age_seconds: "
                f"{DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS}",
                config_text,
            )
            self.assertIn(
                f"reasoning_cache_max_rows: {DEFAULT_REASONING_CACHE_MAX_ROWS}",
                config_text,
            )
            self.assertIn(
                f"empty_apply_patch: {DEFAULT_EMPTY_APPLY_PATCH}", config_text
            )
            self.assertIn(f"max_tool_retries: {DEFAULT_MAX_TOOL_RETRIES}", config_text)
            self.assertIn(
                "collasible_reasoning: "
                f"{str(DEFAULT_COLLAPSIBLE_REASONING).lower()}",
                config_text,
            )
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o600)
            self.assertEqual(config.upstream_model, DEFAULT_UPSTREAM_MODEL)
            self.assertEqual(
                config.collapsible_reasoning,
                DEFAULT_COLLAPSIBLE_REASONING,
            )
            self.assertEqual(
                config.missing_reasoning_strategy, DEFAULT_MISSING_REASONING_STRATEGY
            )
            self.assertEqual(
                config.reasoning_cache_max_age_seconds,
                DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS,
            )
            self.assertEqual(
                config.reasoning_cache_max_rows, DEFAULT_REASONING_CACHE_MAX_ROWS
            )

    def test_missing_explicit_config_file_is_not_populated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "missing.yaml"

            config = ProxyConfig.from_file(config_path=config_path)

            self.assertFalse(config_path.exists())
            self.assertEqual(config.upstream_model, DEFAULT_UPSTREAM_MODEL)
            self.assertEqual(
                config.reasoning_cache_max_age_seconds,
                DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS,
            )
            self.assertEqual(
                config.reasoning_cache_max_rows, DEFAULT_REASONING_CACHE_MAX_ROWS
            )

    def test_loads_config_from_user_yaml_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            reasoning_content_path = Path(temp_dir) / "reasoning_content.sqlite3"
            config_path.write_text(
                "\n".join(
                    [
                        "base_url: https://example.com/v1/",
                        "model: deepseek-v4-flash",
                        "thinking: disabled",
                        "reasoning_effort: max",
                        "port: 9100",
                        "host: 0.0.0.0",
                        "verbose: true",
                        "request_timeout: 123.5",
                        "max_request_body_bytes: 1234",
                        "cors: true",
                        "display_reasoning: false",
                        "collasible_reasoning: false",
                        f"reasoning_content_path: {reasoning_content_path}",
                        "missing_reasoning_strategy: reject",
                        "reasoning_cache_max_age_seconds: 60",
                        "reasoning_cache_max_rows: 50",
                        "empty_apply_patch: reject",
                        "max_tool_retries: 0",
                    ]
                ),
                encoding="utf-8",
            )

            config = ProxyConfig.from_file(config_path=config_path)

        self.assertEqual(config.upstream_base_url, "https://example.com/v1")
        self.assertEqual(config.upstream_model, "deepseek-v4-flash")
        self.assertEqual(config.thinking, "disabled")
        self.assertEqual(config.reasoning_effort, "max")
        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 9100)
        self.assertTrue(config.verbose)
        self.assertEqual(config.request_timeout, 123.5)
        self.assertEqual(config.max_request_body_bytes, 1234)
        self.assertTrue(config.cors)
        self.assertFalse(config.display_reasoning)
        self.assertFalse(config.collapsible_reasoning)
        self.assertEqual(config.reasoning_content_path, reasoning_content_path)
        self.assertEqual(config.missing_reasoning_strategy, "reject")
        self.assertEqual(config.reasoning_cache_max_age_seconds, 60)
        self.assertEqual(config.reasoning_cache_max_rows, 50)
        self.assertEqual(config.empty_apply_patch, "reject")
        self.assertEqual(config.max_tool_retries, 0)

    def test_loads_and_resolves_multiple_providers_and_models(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "model: gpt-fast",
                        "providers:",
                        "  OpenAI:",
                        "    base_url: https://openai.example/v1/",
                        "  OpenRouter:",
                        "    base_url: https://openrouter.example/v1",
                        "models:",
                        "  OpenAI:",
                        "    - gpt-fast",
                        "  OpenRouter:",
                        "    - gpt-strong",
                    ]
                ),
                encoding="utf-8",
            )

            config = ProxyConfig.from_file(config_path=config_path)

        self.assertEqual(
            config.providers["OpenAI"],
            ProviderConfig("OpenAI", "https://openai.example/v1"),
        )
        self.assertEqual(
            config.model_routes["gpt-strong"],
            ModelRoute("gpt-strong", "OpenRouter", "gpt-strong"),
        )
        self.assertEqual(config.upstream_model, "gpt-fast")
        self.assertEqual(config.available_models(), ["gpt-fast", "gpt-strong"])
        route = config.resolve_route("gpt-strong")
        self.assertEqual(route.provider, "OpenRouter")
        self.assertEqual(route.upstream_base_url, "https://openrouter.example/v1")
        self.assertEqual(route.upstream_model, "gpt-strong")

        with self.assertRaises(UnknownModelError):
            config.resolve_route("missing")

    def test_model_route_rejects_unknown_provider(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "providers:",
                        "  OpenAI:",
                        "    base_url: https://openai.example/v1",
                        "models:",
                        "  MissingProvider:",
                        "    - gpt",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unknown provider"):
                ProxyConfig.from_file(config_path=config_path)

    def test_provider_rejects_api_key_configuration(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "providers:",
                        "  OpenAI:",
                        "    base_url: https://openai.example/v1",
                        "    api_key_env: OPENAI_API_KEY",
                        "models:",
                        "  OpenAI:",
                        "    - gpt",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "GitHub Copilot App"):
                ProxyConfig.from_file(config_path=config_path)

    def test_rejects_top_level_api_key_configuration(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("api_key: sk-test", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "GitHub Copilot App"):
                ProxyConfig.from_file(config_path=config_path)

    def test_rejects_duplicate_model_across_providers(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "providers:",
                        "  OpenAI:",
                        "    base_url: https://openai.example/v1",
                        "  OpenRouter:",
                        "    base_url: https://openrouter.example/v1",
                        "models:",
                        "  OpenAI:",
                        "    - gpt",
                        "  OpenRouter:",
                        "    - gpt",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "multiple providers"):
                ProxyConfig.from_file(config_path=config_path)

    def test_legacy_per_model_routes_remain_supported(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "model: copilot-alias",
                        "providers:",
                        "  ExistingProvider:",
                        "    base_url: https://provider.example/v1",
                        "models:",
                        "  copilot-alias:",
                        "    provider: ExistingProvider",
                        "    model: upstream-model",
                    ]
                ),
                encoding="utf-8",
            )

            config = ProxyConfig.from_file(config_path=config_path)

        route = config.resolve_route("copilot-alias")
        self.assertEqual(route.provider, "ExistingProvider")
        self.assertEqual(route.upstream_model, "upstream-model")

    def test_invalid_config_values_fall_back_to_defaults(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "thinking: maybe",
                        "missing_reasoning_strategy: maybe",
                        "port: nope",
                        "verbose: maybe",
                        "collasible_reasoning: maybe",
                    ]
                ),
                encoding="utf-8",
            )

            config = ProxyConfig.from_file(config_path=config_path)

        self.assertEqual(config.thinking, DEFAULT_THINKING)
        self.assertEqual(
            config.missing_reasoning_strategy, DEFAULT_MISSING_REASONING_STRATEGY
        )
        self.assertEqual(config.port, DEFAULT_PORT)
        self.assertEqual(config.verbose, DEFAULT_VERBOSE)
        self.assertEqual(
            config.collapsible_reasoning,
            DEFAULT_COLLAPSIBLE_REASONING,
        )

    def test_relative_reasoning_content_path_in_config_is_relative_to_config_file(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "reasoning_content_path: custom.sqlite3",
                    ]
                ),
                encoding="utf-8",
            )

            config = ProxyConfig.from_file(config_path=config_path)

        self.assertEqual(
            config.reasoning_content_path, Path(temp_dir) / "custom.sqlite3"
        )

    def test_cursor_reasoning_display_can_be_disabled_from_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "display_reasoning: false",
                    ]
                ),
                encoding="utf-8",
            )

            config = ProxyConfig.from_file(config_path=config_path)

        self.assertFalse(config.display_reasoning)

    def test_collapsible_reasoning_can_use_corrected_config_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("collapsible_reasoning: false\n", encoding="utf-8")

            config = ProxyConfig.from_file(config_path=config_path)

        self.assertFalse(config.collapsible_reasoning)

    def test_invalid_yaml_config_raises_value_error(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                ProxyConfig.from_file(config_path=config_path)

    def test_process_environment_does_not_override_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("verbose: false\n", encoding="utf-8")

            with (
                patch.dict(
                    "os.environ",
                    {
                        "PROXY_VERBOSE": "true",
                        "DEEPSEEK_CURSOR_PROXY_CONFIG_PATH": "/ignored.yaml",
                    },
                    clear=True,
                ),
                patch("copilot_gpt_proxy.config.Path.cwd", return_value=Path(temp_dir)),
            ):
                config = ProxyConfig.from_file(config_path=config_path)
                self.assertEqual(
                    dict(os.environ),
                    {
                        "PROXY_VERBOSE": "true",
                        "DEEPSEEK_CURSOR_PROXY_CONFIG_PATH": "/ignored.yaml",
                    },
                )

        self.assertFalse(config.verbose)


if __name__ == "__main__":
    unittest.main()

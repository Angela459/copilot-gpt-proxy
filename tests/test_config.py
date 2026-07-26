from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from copilot_gpt_proxy.config import (
    DEFAULT_EMPTY_APPLY_PATCH,
    DEFAULT_UPSTREAM_BASE_URL,
    DEFAULT_UPSTREAM_MODEL,
    ProxyConfig,
    UnknownModelError,
    load_config_file,
    populate_default_config_file,
)


class ConfigTests(unittest.TestCase):
    def test_defaults_target_openai_compatible_gpt(self) -> None:
        config = ProxyConfig()
        self.assertEqual(config.upstream_base_url, "https://api.openai.com/v1")
        self.assertEqual(config.upstream_model, "gpt-5.4")
        self.assertEqual(config.available_models(), ["gpt-5.4"])
        self.assertEqual(config.empty_apply_patch, DEFAULT_EMPTY_APPLY_PATCH)

    def test_missing_default_config_is_created_in_requested_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            populate_default_config_file(path)
            config = ProxyConfig.from_file(path)

            self.assertTrue(path.exists())
            self.assertEqual(config.upstream_base_url, DEFAULT_UPSTREAM_BASE_URL)
            self.assertEqual(config.upstream_model, DEFAULT_UPSTREAM_MODEL)
            text = path.read_text(encoding="utf-8")
            self.assertIn("OpenAI:", text)
            self.assertNotIn("api_key", text)

    def test_grouped_models_build_provider_routes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text(
                """
model: gpt-strong
providers:
  OpenAI:
    base_url: https://openai.example/v1/
  Gateway:
    base_url: https://gateway.example/v1
models:
  OpenAI:
    - gpt-fast
  Gateway:
    - gpt-strong
thinking: disabled
reasoning_effort: high
empty_apply_patch: reject
max_tool_retries: 0
""".lstrip(),
                encoding="utf-8",
            )

            config = ProxyConfig.from_file(path)

        self.assertEqual(config.upstream_model, "gpt-strong")
        self.assertEqual(config.available_models(), ["gpt-fast", "gpt-strong"])
        route = config.resolve_route("gpt-strong")
        self.assertEqual(route.provider, "Gateway")
        self.assertEqual(route.upstream_base_url, "https://gateway.example/v1")
        self.assertEqual(route.upstream_model, "gpt-strong")
        self.assertEqual(config.thinking, "disabled")
        self.assertEqual(config.reasoning_effort, "high")
        self.assertEqual(config.empty_apply_patch, "reject")
        self.assertEqual(config.max_tool_retries, 0)

    def test_unknown_model_is_rejected_when_routes_are_configured(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text(
                """
providers:
  OpenAI:
    base_url: https://openai.example/v1
models:
  OpenAI:
    - gpt-5.4
""".lstrip(),
                encoding="utf-8",
            )
            config = ProxyConfig.from_file(path)

        with self.assertRaises(UnknownModelError):
            config.resolve_route("missing")

    def test_default_model_must_be_listed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text(
                """
model: missing
providers:
  OpenAI:
    base_url: https://openai.example/v1
models:
  OpenAI:
    - gpt-5.4
""".lstrip(),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Default model"):
                ProxyConfig.from_file(path)

    def test_duplicate_model_across_providers_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text(
                """
providers:
  A:
    base_url: https://a.example/v1
  B:
    base_url: https://b.example/v1
models:
  A:
    - gpt-5.4
  B:
    - gpt-5.4
""".lstrip(),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "multiple providers"):
                ProxyConfig.from_file(path)

    def test_api_keys_are_rejected_at_root_and_provider_level(self) -> None:
        cases = (
            "api_key: secret\n",
            """
providers:
  OpenAI:
    base_url: https://openai.example/v1
    api_key: secret
models:
  OpenAI:
    - gpt-5.4
""".lstrip(),
        )
        for content in cases:
            with self.subTest(content=content), TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "config.yaml"
                path.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "API key"):
                    ProxyConfig.from_file(path)

    def test_invalid_yaml_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text("providers: [", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid YAML"):
                load_config_file(path)


if __name__ == "__main__":
    unittest.main()

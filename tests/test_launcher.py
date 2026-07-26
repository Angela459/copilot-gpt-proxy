from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from copilot_gpt_proxy.config import ProxyConfig
from copilot_gpt_proxy.launcher import (
    choose_copilot_app,
    copilot_environment,
    main,
    update_launcher_config,
)


class LauncherTests(unittest.TestCase):
    def test_explicit_copilot_app_must_be_github_exe(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_path = Path(temp_dir) / "github.exe"
            app_path.write_bytes(b"")

            selected = choose_copilot_app(explicit_path=app_path)

        self.assertEqual(selected, app_path.resolve())

    def test_rejects_a_vs_code_settings_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "github.exe"):
                choose_copilot_app(explicit_path=settings_path)

    def test_migration_removes_legacy_vs_code_settings(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_path = root / "github.exe"
            config_path = root / "config.yaml"
            app_path.write_bytes(b"")
            config_path.write_text(
                "\n".join(
                    [
                        'base_url: "https://provider.test/v1"',
                        'model: "gpt-5.4"',
                        'copilot_settings_path: "C:/Code/User/settings.json"',
                        'copilot_model_id: "gpt-5.4"',
                        "verbose: true",
                    ]
                ),
                encoding="utf-8",
            )

            update_launcher_config(config_path, app_path=app_path.resolve())
            source = config_path.read_text(encoding="utf-8")
            config = ProxyConfig.from_file(config_path)

        self.assertNotIn("copilot_settings_path", source)
        self.assertNotIn("copilot_model_id", source)
        self.assertEqual(config.copilot_app_path, app_path.resolve())
        self.assertTrue(config.verbose)

    def test_copilot_environment_targets_proxy_without_changing_api_key(self) -> None:
        config = ProxyConfig(
            upstream_model="gpt-5.4",
            copilot_wire_api="responses",
        )
        with patch.dict(
            os.environ,
            {"COPILOT_PROVIDER_API_KEY": "keep-existing-key"},
            clear=True,
        ):
            environment = copilot_environment(config, "http://127.0.0.1:9000/v1/")

        self.assertEqual(
            environment["COPILOT_PROVIDER_BASE_URL"],
            "http://127.0.0.1:9000/v1",
        )
        self.assertEqual(environment["COPILOT_PROVIDER_WIRE_API"], "responses")
        self.assertEqual(environment["COPILOT_MODEL"], "gpt-5.4")
        self.assertEqual(environment["COPILOT_PROVIDER_API_KEY"], "keep-existing-key")

    def test_no_start_generates_config_for_copilot_app(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_path = root / "github.exe"
            config_path = root / "config.yaml"
            template_path = root / "config.example.yaml"
            app_path.write_bytes(b"")
            template_path.write_text(
                "\n".join(
                    [
                        'base_url: "__BASE_URL__"',
                        'model: "__MODEL_ID__"',
                        'copilot_app_path: "__COPILOT_APP_PATH__"',
                        'copilot_wire_api: "__COPILOT_WIRE_API__"',
                        "ngrok: __NGROK__",
                    ]
                ),
                encoding="utf-8",
            )

            result = main(
                [
                    "--no-start",
                    "--copilot-app",
                    str(app_path),
                    "--base-url",
                    "https://provider.test/v1",
                    "--model-id",
                    "gpt-5.4",
                    "--config",
                    str(config_path),
                    "--template",
                    str(template_path),
                ]
            )
            config = ProxyConfig.from_file(config_path)

        self.assertEqual(result, 0)
        self.assertEqual(config.upstream_base_url, "https://provider.test/v1")
        self.assertEqual(config.upstream_model, "gpt-5.4")
        self.assertEqual(config.copilot_app_path, app_path.resolve())
        self.assertEqual(config.copilot_wire_api, "responses")
        self.assertFalse(config.ngrok)


if __name__ == "__main__":
    unittest.main()

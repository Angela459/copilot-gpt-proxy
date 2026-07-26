from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from copilot_gpt_proxy.copilot_config import load_copilot_settings
from copilot_gpt_proxy.config import ProxyConfig
from copilot_gpt_proxy.launcher import (
    choose_settings_path,
    existing_standard_settings,
    main,
    standard_settings_candidates,
    upstream_base_url,
)


class LauncherTests(unittest.TestCase):
    def test_standard_locations_are_derived_from_appdata_without_scanning(self) -> None:
        candidates = standard_settings_candidates({"APPDATA": "C:/Users/Test/AppData"})

        self.assertEqual(
            [(candidate.label, candidate.path.as_posix()) for candidate in candidates],
            [
                (
                    "Visual Studio Code",
                    "C:/Users/Test/AppData/Code/User/settings.json",
                ),
                (
                    "Visual Studio Code Insiders",
                    "C:/Users/Test/AppData/Code - Insiders/User/settings.json",
                ),
                (
                    "VSCodium",
                    "C:/Users/Test/AppData/VSCodium/User/settings.json",
                ),
            ],
        )

    def test_only_exact_standard_files_are_detected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            appdata = Path(temp_dir)
            standard = appdata / "Code" / "User" / "settings.json"
            unrelated = appdata / "Other" / "settings.json"
            standard.parent.mkdir(parents=True)
            unrelated.parent.mkdir(parents=True)
            standard.write_text("{}", encoding="utf-8")
            unrelated.write_text("{}", encoding="utf-8")

            detected = existing_standard_settings({"APPDATA": str(appdata)})

        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0].label, "Visual Studio Code")

    def test_explicit_settings_path_must_be_a_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text("{}", encoding="utf-8")

            selected = choose_settings_path(explicit_path=path)

        self.assertEqual(selected, path.resolve())

    def test_reconfiguration_uses_original_upstream_backup(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            backup = path.with_name("settings.json.copilot-gpt-proxy.bak")
            path.write_text(
                '{"oaicopilot.models":[{"id":"gpt-x","baseUrl":"http://127.0.0.1:9000/v1"}]}',
                encoding="utf-8",
            )
            backup.write_text(
                '{"oaicopilot.models":[{"id":"gpt-x","baseUrl":"https://provider.test/v1"}]}',
                encoding="utf-8",
            )
            model = load_copilot_settings(path).selected_model("gpt-x")

            base_url = upstream_base_url(path, model)

        self.assertEqual(base_url, "https://provider.test/v1")

    def test_no_start_generates_project_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "settings.json"
            config_path = root / "config.yaml"
            template_path = root / "config.example.yaml"
            settings_path.write_text(
                '{"oaicopilot.models":[{"id":"gpt-x","baseUrl":"https://provider.test/v1","apiMode":"openai"}]}',
                encoding="utf-8",
            )
            template_path.write_text(
                "\n".join(
                    [
                        'base_url: "__BASE_URL__"',
                        'model: "__MODEL_ID__"',
                        'copilot_settings_path: "__COPILOT_SETTINGS_PATH__"',
                        'copilot_model_id: "__MODEL_ID__"',
                        "ngrok: __NGROK__",
                    ]
                ),
                encoding="utf-8",
            )

            result = main(
                [
                    "--reconfigure",
                    "--no-start",
                    "--settings",
                    str(settings_path),
                    "--model-id",
                    "gpt-x",
                    "--config",
                    str(config_path),
                    "--template",
                    str(template_path),
                ]
            )
            config = ProxyConfig.from_file(config_path)

        self.assertEqual(result, 0)
        self.assertEqual(config.upstream_model, "gpt-x")
        self.assertEqual(config.upstream_base_url, "https://provider.test/v1")
        self.assertFalse(config.ngrok)


if __name__ == "__main__":
    unittest.main()

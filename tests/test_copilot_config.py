from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from copilot_gpt_proxy.copilot_config import load_copilot_settings


class CopilotSettingsTests(unittest.TestCase):
    def test_loads_explicit_jsonc_path_without_credentials(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                """
                // VS Code user settings
                {
                  "oaicopilot.baseUrl": "https://example.test/v1",
                  "oaicopilot.models": [
                    {"id": "__provider__demo", "apiMode": "openai",},
                    {"id": "gpt-5.4", "baseUrl": "https://example.test/v1", "apiMode": "openai-responses", "owned_by": "demo"}
                  ],
                  "oaicopilot.apiKey": "must-not-be-read"
                }
                """,
                encoding="utf-8",
            )

            settings = load_copilot_settings(path)

        self.assertEqual(settings.base_url, "https://example.test/v1")
        self.assertEqual(settings.selected_model().model_id, "gpt-5.4")
        self.assertEqual(settings.selected_model().api_mode, "openai-responses")
        self.assertNotIn("apiKey", str(settings.public_dict()))

    def test_explicit_model_selection_rejects_unknown_id(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                '{"oaicopilot.models":[{"id":"gpt-5.4"}]}', encoding="utf-8"
            )
            settings = load_copilot_settings(path)

        self.assertIsNone(settings.selected_model("missing"))

    def test_missing_path_is_rejected_without_directory_scan(self) -> None:
        with self.assertRaises(ValueError):
            load_copilot_settings("C:/does-not-exist/settings.json")


if __name__ == "__main__":
    unittest.main()

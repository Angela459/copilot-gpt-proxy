from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from copilot_gpt_proxy.copilot_config import (
    load_copilot_settings,
    update_copilot_proxy_url,
)


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

    def test_updates_selected_proxy_urls_and_preserves_jsonc(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            original = """
            {
              // Keep this comment and unrelated secret.
              "oaicopilot.baseUrl": "https://provider.test/v1",
              "oaicopilot.apiKey": "must-stay-private",
              "oaicopilot.models": [
                {"id": "__provider__demo", "baseUrl": "https://provider.test/v1"},
                {"id": "gpt-a", "baseUrl": "https://a.test/v1"},
                {"id": "gpt-b", "baseUrl": "https://b.test/v1", "owned_by": "demo"},
              ],
            }
            """.replace(
                "\n", "\r\n"
            )
            path.write_bytes(original.encode("utf-8"))

            changed = update_copilot_proxy_url(
                path,
                "gpt-b",
                "http://127.0.0.1:9000/v1/",
            )
            settings = load_copilot_settings(path)

            self.assertTrue(changed)
            self.assertEqual(settings.base_url, "http://127.0.0.1:9000/v1")
            self.assertEqual(
                settings.selected_model("gpt-b").base_url,
                "http://127.0.0.1:9000/v1",
            )
            self.assertEqual(
                settings.selected_model("gpt-a").base_url,
                "https://a.test/v1",
            )
            self.assertEqual(
                settings.selected_model("__provider__demo").base_url,
                "http://127.0.0.1:9000/v1",
            )
            updated_source = path.read_bytes().decode("utf-8")
            self.assertIn("// Keep this comment", updated_source)
            self.assertIn('"oaicopilot.apiKey": "must-stay-private"', updated_source)
            self.assertEqual(updated_source.count("\r\n"), original.count("\r\n"))
            self.assertNotIn("\r\r\n", updated_source)
            backup = path.with_name("settings.json.copilot-gpt-proxy.bak")
            self.assertEqual(backup.read_bytes().decode("utf-8"), original)
            self.assertFalse(
                update_copilot_proxy_url(
                    path,
                    "gpt-b",
                    "http://127.0.0.1:9000/v1",
                )
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest

from copilot_gpt_proxy.config import ModelRoute, ProviderConfig, ProxyConfig
from copilot_gpt_proxy.transform import (
    extract_text_content,
    normalize_reasoning_effort,
    prepare_upstream_request,
    rewrite_response_body,
    strip_copilot_thinking_blocks,
)


def _gpt_config(**overrides: object) -> ProxyConfig:
    values: dict[str, object] = {
        "providers": {
            "OpenAI": ProviderConfig("OpenAI", "https://example.com/v1")
        },
        "model_routes": {
            "gpt-5.6-sol": ModelRoute(
                "gpt-5.6-sol", "OpenAI", "gpt-5.6-sol"
            )
        },
    }
    values.update(overrides)
    return ProxyConfig(**values)


class ContentHelpersTests(unittest.TestCase):
    def test_extract_text_content_flattens_multipart_array(self) -> None:
        content = [
            {"type": "text", "text": "hello"},
            {"type": "image_url", "image_url": {"url": "data:..."}},
            {"type": "input_text", "text": "world"},
        ]
        self.assertEqual(
            extract_text_content(content),
            "hello\n[image_url omitted by proxy]\nworld",
        )

    def test_strip_copilot_thinking_blocks_removes_mirrored_reasoning(self) -> None:
        self.assertEqual(
            strip_copilot_thinking_blocks(
                "<details>\n<summary>Thinking</summary>\n\nplan\n</details>\n\nanswer"
            ),
            "answer",
        )
        self.assertEqual(
            strip_copilot_thinking_blocks("<think>\nplan\n</think>\n\nanswer"),
            "answer",
        )

    def test_reasoning_effort_aliases_match_gateway_contract(self) -> None:
        self.assertEqual(normalize_reasoning_effort("low"), "high")
        self.assertEqual(normalize_reasoning_effort("medium"), "high")
        self.assertEqual(normalize_reasoning_effort("high"), "high")
        self.assertEqual(normalize_reasoning_effort("max"), "max")
        self.assertEqual(normalize_reasoning_effort("xhigh"), "max")


class RequestPreparationTests(unittest.TestCase):
    def test_legacy_functions_are_converted_to_tools(self) -> None:
        prepared = prepare_upstream_request(
            {
                "model": "gpt-5.6-sol",
                "messages": [{"role": "user", "content": "hi"}],
                "functions": [{"name": "lookup", "parameters": {"type": "object"}}],
                "function_call": "auto",
            },
            _gpt_config(),
        )
        self.assertEqual(prepared.payload["tools"][0]["function"]["name"], "lookup")
        self.assertEqual(prepared.payload["tool_choice"], "auto")
        self.assertNotIn("functions", prepared.payload)
        self.assertNotIn("function_call", prepared.payload)

    def test_max_completion_tokens_is_aliased(self) -> None:
        prepared = prepare_upstream_request(
            {
                "model": "gpt-5.6-sol",
                "messages": [{"role": "user", "content": "hi"}],
                "max_completion_tokens": 256,
            },
            _gpt_config(),
        )
        self.assertEqual(prepared.payload["max_tokens"], 256)

    def test_gpt_tool_history_is_preserved_without_reasoning_recovery(self) -> None:
        messages = [
            {"role": "user", "content": "Create test.txt"},
            {
                "role": "assistant",
                "content": "Creating the file.",
                "tool_calls": [
                    {
                        "id": "call_patch",
                        "type": "custom",
                        "custom": {
                            "name": "apply_patch",
                            "input": "*** Begin Patch",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_patch",
                "content": "Failed to apply patch: File already exists: test.txt",
            },
        ]

        prepared = prepare_upstream_request(
            {"model": "gpt-5.6-sol", "messages": messages},
            _gpt_config(thinking="enabled"),
        )

        self.assertEqual(len(prepared.payload["messages"]), 3)
        tool_call = prepared.payload["messages"][1]["tool_calls"][0]
        self.assertEqual(tool_call["type"], "custom")
        self.assertEqual(tool_call["custom"]["name"], "apply_patch")
        self.assertEqual(tool_call["custom"]["input"], "*** Begin Patch")
        self.assertEqual(
            prepared.payload["messages"][2]["tool_call_id"], "call_patch"
        )
        self.assertIn("already exists", prepared.payload["messages"][2]["content"])

    def test_reasoning_content_is_not_forwarded_in_chat_history(self) -> None:
        prepared = prepare_upstream_request(
            {
                "model": "gpt-5.6-sol",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {
                        "role": "assistant",
                        "content": "answer",
                        "reasoning_content": "provider-private reasoning",
                    },
                ],
            },
            _gpt_config(),
        )
        self.assertNotIn("reasoning_content", prepared.payload["messages"][1])

    def test_route_and_thinking_settings_are_applied(self) -> None:
        prepared = prepare_upstream_request(
            {"model": "gpt-5.6-sol", "messages": []},
            _gpt_config(thinking="enabled", reasoning_effort="max"),
        )
        self.assertEqual(prepared.upstream_model, "gpt-5.6-sol")
        self.assertEqual(prepared.provider_name, "OpenAI")
        self.assertEqual(prepared.payload["thinking"], {"type": "enabled"})
        self.assertEqual(prepared.payload["reasoning_effort"], "max")


class ResponseRewriteTests(unittest.TestCase):
    def test_restores_requested_model(self) -> None:
        body = json.dumps(
            {
                "model": "provider-model",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            }
        ).encode()
        rewritten = rewrite_response_body(body, "gpt-5.6-sol")
        self.assertEqual(json.loads(rewritten)["model"], "gpt-5.6-sol")

    def test_can_display_provider_reasoning(self) -> None:
        body = json.dumps(
            {
                "model": "gpt-5.6-sol",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "plan",
                            "content": "answer",
                        }
                    }
                ],
            }
        ).encode()
        rewritten = rewrite_response_body(
            body,
            "gpt-5.6-sol",
            display_reasoning=True,
            collapsible_reasoning=True,
        )
        content = json.loads(rewritten)["choices"][0]["message"]["content"]
        self.assertIn("<summary>Thinking</summary>", content)
        self.assertTrue(content.endswith("answer"))


if __name__ == "__main__":
    unittest.main()

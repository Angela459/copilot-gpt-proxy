from __future__ import annotations

import unittest

from copilot_gpt_proxy.streaming import (
    CopilotReasoningDisplayAdapter,
    StreamAccumulator,
    fold_reasoning_into_content,
)


class StreamAccumulatorTests(unittest.TestCase):
    def test_accumulates_content_reasoning_and_tool_call_deltas(self) -> None:
        accumulator = StreamAccumulator()
        accumulator.ingest_chunk(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "reasoning_content": "Need ",
                            "content": "",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_patch",
                                    "type": "function",
                                    "function": {
                                        "name": "apply_",
                                        "arguments": '{"input":"',
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        )
        accumulator.ingest_chunk(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "reasoning_content": "context.",
                            "content": "Editing.",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {
                                        "name": "patch",
                                        "arguments": "patch" + '"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        )

        message = accumulator.messages()[0]
        self.assertEqual(message["reasoning_content"], "Need context.")
        self.assertEqual(message["content"], "Editing.")
        self.assertEqual(message["tool_calls"][0]["id"], "call_patch")
        self.assertEqual(
            message["tool_calls"][0]["function"]["name"], "apply_patch"
        )
        self.assertEqual(
            message["tool_calls"][0]["function"]["arguments"],
            '{"input":"patch"}',
        )


class ReasoningDisplayTests(unittest.TestCase):
    def test_stream_adapter_wraps_reasoning_and_closes_before_content(self) -> None:
        adapter = CopilotReasoningDisplayAdapter(collapsible=True)
        reasoning_chunk = {
            "id": "chunk-1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-5.4",
            "choices": [
                {
                    "index": 0,
                    "delta": {"reasoning_content": "plan"},
                    "finish_reason": None,
                }
            ],
        }
        adapter.rewrite_chunk(reasoning_chunk)
        self.assertIn(
            "<summary>Thinking</summary>",
            reasoning_chunk["choices"][0]["delta"]["content"],
        )

        content_chunk = {
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "answer"},
                    "finish_reason": None,
                }
            ]
        }
        adapter.rewrite_chunk(content_chunk)
        content = content_chunk["choices"][0]["delta"]["content"]
        self.assertIn("</details>", content)
        self.assertTrue(content.endswith("answer"))
        self.assertIsNone(adapter.flush_chunk("gpt-5.4"))

    def test_flush_closes_unfinished_reasoning_block(self) -> None:
        adapter = CopilotReasoningDisplayAdapter(collapsible=False)
        chunk = {
            "choices": [
                {
                    "index": 0,
                    "delta": {"reasoning_content": "plan"},
                    "finish_reason": None,
                }
            ]
        }
        adapter.rewrite_chunk(chunk)
        closing = adapter.flush_chunk("gpt-5.4")
        self.assertIsNotNone(closing)
        self.assertIn("</think>", closing["choices"][0]["delta"]["content"])

    def test_non_streaming_reasoning_is_mirrored(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "reasoning_content": "plan",
                        "content": "answer",
                    }
                }
            ]
        }
        fold_reasoning_into_content(payload, collapsible=True)
        content = payload["choices"][0]["message"]["content"]
        self.assertIn("plan", content)
        self.assertTrue(content.endswith("answer"))


if __name__ == "__main__":
    unittest.main()

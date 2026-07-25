from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from copilot_gpt_proxy.config import ProxyConfig
from copilot_gpt_proxy.reasoning_store import ReasoningStore
from copilot_gpt_proxy.responses import (
    has_custom_apply_patch_tool,
    inspect_responses_body,
    normalize_responses_request,
    repair_responses_request,
    restore_custom_apply_patch_response,
)
from copilot_gpt_proxy.server import DeepSeekProxyHandler, DeepSeekProxyServer


def _event(event: dict) -> bytes:
    return b"data: " + json.dumps(event, separators=(",", ":")).encode() + b"\n\n"


def _named_event(event: dict) -> bytes:
    return (
        f"event: {event['type']}\n".encode()
        + b"data: "
        + json.dumps(event, separators=(",", ":")).encode()
        + b"\n\n"
    )


def _responses_stream(arguments: str, completed: bool = True) -> bytes:
    item = {
        "id": "fc_patch",
        "call_id": "call_patch",
        "type": "function_call",
        "name": "apply_patch",
        "arguments": arguments,
    }
    body = _event(
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**item, "arguments": ""},
        }
    )
    body += _event(
        {
            "type": "response.function_call_arguments.done",
            "item_id": "fc_patch",
            "output_index": 0,
            "arguments": arguments,
        }
    )
    body += _event(
        {"type": "response.output_item.done", "output_index": 0, "item": item}
    )
    if completed:
        body += _event(
            {
                "type": "response.completed",
                "response": {"id": "resp_1", "status": "completed", "output": [item]},
            }
        )
    return body


def _custom_responses_stream(tool_input: str, completed: bool = True) -> bytes:
    item = {
        "id": "ctc_patch",
        "call_id": "call_custom_patch",
        "type": "custom_tool_call",
        "name": "apply_patch",
        "input": tool_input,
    }
    body = _event(
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**item, "input": ""},
        }
    )
    midpoint = len(tool_input) // 2
    for delta in (tool_input[:midpoint], tool_input[midpoint:]):
        body += _event(
            {
                "type": "response.custom_tool_call_input.delta",
                "item_id": "ctc_patch",
                "output_index": 0,
                "delta": delta,
            }
        )
    body += _event(
        {
            "type": "response.custom_tool_call_input.done",
            "item_id": "ctc_patch",
            "output_index": 0,
            "input": tool_input,
        }
    )
    body += _event(
        {"type": "response.output_item.done", "output_index": 0, "item": item}
    )
    if completed:
        body += _event(
            {
                "type": "response.completed",
                "response": {"id": "resp_1", "status": "completed", "output": [item]},
            }
        )
    return body


class ResponsesAccumulatorTests(unittest.TestCase):
    def test_detects_empty_apply_patch_and_completion(self) -> None:
        invalid, completed = inspect_responses_body(_responses_stream("{}"), True)
        self.assertEqual(invalid, ["call_patch"])
        self.assertTrue(completed)

    def test_detects_stream_without_completed_event(self) -> None:
        invalid, completed = inspect_responses_body(
            _responses_stream('{"patch":"*** Begin Patch"}', completed=False),
            True,
        )
        self.assertEqual(invalid, [])
        self.assertFalse(completed)

    def test_detects_empty_function_call_input_field(self) -> None:
        invalid, completed = inspect_responses_body(
            _responses_stream('{"input":""}'), True
        )
        self.assertEqual(invalid, ["call_patch"])
        self.assertTrue(completed)

    def test_detects_empty_custom_tool_call(self) -> None:
        invalid, completed = inspect_responses_body(_custom_responses_stream(""), True)
        self.assertEqual(invalid, ["call_custom_patch"])
        self.assertTrue(completed)

    def test_accepts_valid_custom_tool_call(self) -> None:
        patch = "*** Begin Patch\n*** End Patch"
        invalid, completed = inspect_responses_body(
            _custom_responses_stream(patch), True
        )
        self.assertEqual(invalid, [])
        self.assertTrue(completed)

    def test_retry_removes_empty_call_history_and_matching_outputs(self) -> None:
        valid_call = {
            "type": "custom_tool_call",
            "call_id": "call_valid",
            "name": "apply_patch",
            "input": "*** Begin Patch\n*** End Patch",
        }
        payload = {
            "input": [
                {"type": "message", "role": "user", "content": "edit it"},
                {
                    "type": "function_call",
                    "call_id": "call_empty_function",
                    "name": "apply_patch",
                    "arguments": '{"input":""}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_empty_function",
                    "output": "apply_patch requires a non-empty string input",
                },
                {
                    "type": "custom_tool_call",
                    "call_id": "call_empty_custom",
                    "name": "apply_patch",
                    "input": "",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_empty_custom",
                    "output": "apply_patch requires a non-empty string input",
                },
                valid_call,
                {
                    "type": "function_call_output",
                    "call_id": "call_valid",
                    "output": "Done!",
                },
            ]
        }

        repaired = repair_responses_request(payload)

        self.assertEqual(
            repaired["input"],
            [payload["input"][0], valid_call, payload["input"][-1]],
        )
        self.assertEqual(len(payload["input"]), 7)
        self.assertIn("free-form custom tool", repaired["instructions"])

    def test_normalization_converts_custom_patch_to_required_function_input(
        self,
    ) -> None:
        custom_tool = {
            "type": "custom",
            "name": "apply_patch",
            "description": "Edit files.",
            "format": {"type": "grammar", "syntax": "lark", "definition": "..."},
        }
        other_tool = {"type": "custom", "name": "shell", "description": "Run it."}
        payload = {
            "input": "edit it",
            "tools": [custom_tool, other_tool],
            "tool_choice": {"type": "custom", "name": "apply_patch"},
        }

        repaired = normalize_responses_request(payload)

        patch_tool = repaired["tools"][0]
        self.assertEqual(patch_tool["type"], "function")
        self.assertEqual(patch_tool["name"], "apply_patch")
        self.assertEqual(patch_tool["parameters"]["required"], ["input"])
        self.assertEqual(
            patch_tool["parameters"]["properties"]["input"]["minLength"], 1
        )
        self.assertFalse(patch_tool["strict"])
        self.assertEqual(repaired["tools"][1], other_tool)
        self.assertEqual(
            repaired["tool_choice"], {"type": "function", "name": "apply_patch"}
        )
        self.assertEqual(payload["tools"][0], custom_tool)

    def test_restores_function_patch_stream_to_custom_tool_events(self) -> None:
        patch = "*** Begin Patch\n*** End Patch"
        restored = restore_custom_apply_patch_response(
            _responses_stream(json.dumps({"input": patch})), True
        )
        text = restored.decode("utf-8")

        self.assertIn('"type":"custom_tool_call"', text)
        self.assertIn('"type":"response.custom_tool_call_input.done"', text)
        self.assertIn('"input":"*** Begin Patch\\n*** End Patch"', text)
        self.assertNotIn("response.function_call_arguments", text)
        invalid, completed = inspect_responses_body(restored, True)
        self.assertEqual(invalid, [])
        self.assertTrue(completed)

    def test_restored_stream_has_no_orphan_event_frames(self) -> None:
        arguments = json.dumps({"input": "*** Begin Patch\n*** End Patch"})
        item = {
            "id": "fc_patch",
            "call_id": "call_patch",
            "type": "function_call",
            "name": "apply_patch",
            "arguments": arguments,
        }
        source = _named_event(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {**item, "arguments": ""},
            }
        )
        source += _named_event(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_patch",
                "output_index": 0,
                "delta": arguments,
            }
        )
        source += _named_event(
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_patch",
                "output_index": 0,
                "arguments": arguments,
            }
        )
        source += _named_event(
            {"type": "response.output_item.done", "output_index": 0, "item": item}
        )
        restored = restore_custom_apply_patch_response(source, True).decode("utf-8")

        frames = [frame for frame in restored.split("\n\n") if frame.strip()]
        self.assertTrue(frames)
        self.assertTrue(all("data: " in frame for frame in frames))
        self.assertNotIn("event: response.function_call_arguments.delta", restored)
        self.assertNotIn("event: response.function_call_arguments.done", restored)
        self.assertIn("event: response.custom_tool_call_input.done", restored)

    def test_restored_stream_trims_repeated_request_metadata(self) -> None:
        source = _named_event(
            {
                "type": "response.created",
                "response": {
                    "id": "resp_1",
                    "instructions": "large prompt" * 100,
                    "tools": [{"type": "function", "name": "tool"}] * 50,
                    "output": [],
                },
            }
        )

        restored = restore_custom_apply_patch_response(source, True)
        data_line = next(
            line for line in restored.splitlines() if line.startswith(b"data:")
        )
        event = json.loads(data_line[len(b"data:") :])

        self.assertIsNone(event["response"]["instructions"])
        self.assertEqual(event["response"]["tools"], [])
        self.assertEqual(event["response"]["id"], "resp_1")

    def test_detects_custom_patch_tool_without_matching_other_tools(self) -> None:
        self.assertTrue(
            has_custom_apply_patch_tool(
                {"tools": [{"type": "custom", "name": "apply_patch"}]}
            )
        )
        self.assertFalse(
            has_custom_apply_patch_tool(
                {"tools": [{"type": "function", "name": "apply_patch"}]}
            )
        )


class _ResponsesUpstream(BaseHTTPRequestHandler):
    requests: list[dict] = []
    incomplete = False
    custom = False
    always_empty = False

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length))
        self.__class__.requests.append(payload)
        patch_tool = next(
            (
                tool
                for tool in payload.get("tools", [])
                if isinstance(tool, dict) and tool.get("name") == "apply_patch"
            ),
            None,
        )
        function_fallback = (
            self.__class__.custom
            and isinstance(patch_tool, dict)
            and patch_tool.get("type") == "function"
        )
        empty = self.__class__.always_empty or (
            len(self.__class__.requests) == 1 and not function_fallback
        )
        if self.__class__.custom and (
            not isinstance(patch_tool, dict) or patch_tool.get("type") == "custom"
        ):
            tool_input = "" if empty else "*** Begin Patch\n*** End Patch"
            body = _custom_responses_stream(
                tool_input, completed=not self.__class__.incomplete
            )
        else:
            arguments = "{}" if empty else '{"input":"*** Begin Patch\\n*** End Patch"}'
            body = _responses_stream(arguments, completed=not self.__class__.incomplete)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


class _Fixture:
    def __init__(self, server: ThreadingHTTPServer) -> None:
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class ResponsesIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        _ResponsesUpstream.requests = []
        _ResponsesUpstream.incomplete = False
        _ResponsesUpstream.custom = False
        _ResponsesUpstream.always_empty = False
        self.upstream = _Fixture(
            ThreadingHTTPServer(("127.0.0.1", 0), _ResponsesUpstream)
        )
        self.store = ReasoningStore(":memory:")
        proxy = DeepSeekProxyServer(("127.0.0.1", 0), DeepSeekProxyHandler)
        proxy.config = ProxyConfig(
            upstream_base_url=self.upstream.url,
            upstream_model="gpt-5.4",
            ngrok=False,
            display_reasoning=False,
        )
        proxy.reasoning_store = self.store
        proxy.trace_writer = None
        self.proxy = _Fixture(proxy)

    def tearDown(self) -> None:
        self.proxy.close()
        self.upstream.close()
        self.store.close()

    def _post(self) -> tuple[int, bytes, str]:
        request = Request(
            f"{self.proxy.url}/v1/responses",
            data=json.dumps(
                {
                    "model": "gpt-5.4",
                    "stream": True,
                    "input": "edit it",
                    "tools": [
                        {
                            "type": "custom",
                            "name": "apply_patch",
                            "description": "Edit files.",
                            "format": {
                                "type": "grammar",
                                "syntax": "lark",
                                "definition": "...",
                            },
                        }
                    ],
                }
            ).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer sk-test",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=5) as response:
                return (
                    response.status,
                    response.read(),
                    response.headers.get_content_type(),
                )
        except HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get_content_type()

    def test_empty_responses_call_is_retried_before_forwarding(self) -> None:
        status, body, content_type = self._post()
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/event-stream")
        self.assertEqual(len(_ResponsesUpstream.requests), 2)
        self.assertNotIn(b'"arguments":"{}"', body)
        self.assertIn(b"Begin Patch", body)
        self.assertIn(b"response.completed", body)
        self.assertIn(
            "Compatibility retry", _ResponsesUpstream.requests[1]["instructions"]
        )

    def test_incomplete_stream_is_bounded_after_one_retry(self) -> None:
        _ResponsesUpstream.incomplete = True
        status, body, content_type = self._post()
        payload = json.loads(body)
        self.assertEqual(status, 502)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(len(_ResponsesUpstream.requests), 2)
        self.assertEqual(payload["error"]["code"], "incomplete_response")

    def test_custom_patch_is_normalized_before_first_upstream_request(self) -> None:
        _ResponsesUpstream.custom = True
        status, body, content_type = self._post()
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/event-stream")
        self.assertEqual(len(_ResponsesUpstream.requests), 1)
        self.assertIn(b"*** Begin Patch", body)
        self.assertIn(b'"type":"custom_tool_call"', body)
        self.assertIn(b"response.custom_tool_call_input.done", body)
        self.assertNotIn(b"response.function_call_arguments", body)
        self.assertEqual(_ResponsesUpstream.requests[0]["tools"][0]["type"], "function")
        self.assertNotIn("instructions", _ResponsesUpstream.requests[0])

    def test_repeated_empty_custom_calls_return_bounded_error(self) -> None:
        _ResponsesUpstream.custom = True
        _ResponsesUpstream.always_empty = True
        status, body, content_type = self._post()
        payload = json.loads(body)
        self.assertEqual(status, 502)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(len(_ResponsesUpstream.requests), 2)
        self.assertEqual(payload["error"]["code"], "empty_apply_patch")


if __name__ == "__main__":
    unittest.main()

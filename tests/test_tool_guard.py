from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from copilot_gpt_proxy.config import ProxyConfig
from copilot_gpt_proxy.server import GPTProxyHandler, GPTProxyServer
from copilot_gpt_proxy.tool_guard import (
    REPAIR_INSTRUCTION,
    empty_apply_patch_calls,
)


def _tool_call(arguments: object, call_id: str = "call_patch") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "apply_patch", "arguments": arguments},
    }


class ToolGuardUnitTests(unittest.TestCase):
    def test_detects_empty_argument_representations(self) -> None:
        for arguments in (
            None,
            "",
            "   ",
            "{}",
            {},
            '{"patch":""}',
            '{"input":""}',
            '{"patch":"", "attempt":1}',
            "[]",
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(
                    empty_apply_patch_calls([{"tool_calls": [_tool_call(arguments)]}]),
                    ["call_patch"],
                )

    def test_accepts_raw_and_json_wrapped_patch_content(self) -> None:
        for arguments in (
            "*** Begin Patch\n*** End Patch",
            '{"patch":"*** Begin Patch\\n*** End Patch"}',
            '{"input":"*** Begin Patch\\n*** End Patch"}',
            {"patch": "*** Begin Patch\n*** End Patch"},
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(
                    empty_apply_patch_calls([{"tool_calls": [_tool_call(arguments)]}]),
                    [],
                )

    def test_ignores_other_tools(self) -> None:
        call = _tool_call("{}")
        call["function"]["name"] = "read_file"
        self.assertEqual(empty_apply_patch_calls([{"tool_calls": [call]}]), [])


class _GuardUpstream(BaseHTTPRequestHandler):
    requests: list[dict] = []
    always_empty = False

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length))
        self.__class__.requests.append(payload)
        empty = self.__class__.always_empty or len(self.__class__.requests) == 1
        arguments = "{}" if empty else '{"patch":"*** Begin Patch\\n*** End Patch"}'
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                {
                    "id": "stream-guard",
                    "model": "gpt-5.4",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_patch",
                                        "type": "function",
                                        "function": {
                                            "name": "apply_",
                                            "arguments": arguments[:1],
                                        },
                                    }
                                ]
                            },
                        }
                    ],
                },
                {
                    "id": "stream-guard",
                    "model": "gpt-5.4",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {
                                            "name": "patch",
                                            "arguments": arguments[1:],
                                        },
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                },
            ]
            for chunk in chunks:
                self.wfile.write(
                    b"data: "
                    + json.dumps(chunk, separators=(",", ":")).encode()
                    + b"\n\n"
                )
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        response = {
            "id": "guard",
            "object": "chat.completion",
            "model": "gpt-5.4",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [_tool_call(arguments)],
                    },
                }
            ],
        }
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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


class ToolGuardIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        _GuardUpstream.requests = []
        _GuardUpstream.always_empty = False
        self.upstream = _Fixture(ThreadingHTTPServer(("127.0.0.1", 0), _GuardUpstream))
        proxy = GPTProxyServer(("127.0.0.1", 0), GPTProxyHandler)
        proxy.config = ProxyConfig(
            upstream_base_url=self.upstream.url,
            upstream_model="gpt-5.4",
            display_reasoning=False,
        )
        proxy.trace_writer = None
        self.proxy = _Fixture(proxy)

    def tearDown(self) -> None:
        self.proxy.close()
        self.upstream.close()

    def _post(self, stream: bool = False) -> tuple[int, bytes, str]:
        request = Request(
            f"{self.proxy.url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "gpt-5.4",
                    "stream": stream,
                    "messages": [{"role": "user", "content": "edit it"}],
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

    def test_non_streaming_empty_call_is_retried_once(self) -> None:
        status, body, _ = self._post()
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(_GuardUpstream.requests), 2)
        self.assertEqual(
            _GuardUpstream.requests[1]["messages"][-1],
            {"role": "system", "content": REPAIR_INSTRUCTION},
        )
        arguments = payload["choices"][0]["message"]["tool_calls"][0]["function"][
            "arguments"
        ]
        self.assertIn("Begin Patch", arguments)

    def test_streamed_arguments_are_assembled_before_retry(self) -> None:
        status, body, content_type = self._post(stream=True)
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/event-stream")
        self.assertEqual(len(_GuardUpstream.requests), 2)
        self.assertNotIn(b'"arguments":"{}"', body)
        self.assertIn(b"Begin Patch", body)
        self.assertTrue(body.rstrip().endswith(b"data: [DONE]"))

    def test_second_empty_call_returns_bounded_error(self) -> None:
        _GuardUpstream.always_empty = True
        status, body, content_type = self._post(stream=True)
        payload = json.loads(body)
        self.assertEqual(status, 502)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(len(_GuardUpstream.requests), 2)
        self.assertEqual(payload["error"]["code"], "empty_apply_patch")
        self.assertIn("stopped after one", payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()

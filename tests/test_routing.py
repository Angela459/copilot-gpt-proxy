from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from copilot_gpt_proxy.config import ModelRoute, ProviderConfig, ProxyConfig
from copilot_gpt_proxy.reasoning_store import ReasoningStore
from copilot_gpt_proxy.server import DeepSeekProxyHandler, DeepSeekProxyServer


class _RoutingUpstream(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length))
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "payload": payload,
            }
        )
        if self.path.endswith("/responses"):
            body = {
                "id": "resp-routing",
                "object": "response",
                "status": "completed",
                "model": payload["model"],
                "output": [],
            }
        else:
            body = {
                "id": "chatcmpl-routing",
                "object": "chat.completion",
                "created": 1,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            }
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


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


def _upstream_fixture() -> _Fixture:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RoutingUpstream)
    server.requests = []  # type: ignore[attr-defined]
    return _Fixture(server)


class MultiProviderRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.primary = _upstream_fixture()
        self.backup = _upstream_fixture()
        self.store = ReasoningStore(":memory:")
        proxy = DeepSeekProxyServer(("127.0.0.1", 0), DeepSeekProxyHandler)
        proxy.config = ProxyConfig(
            upstream_base_url=self.primary.url,
            upstream_model="fast",
            providers={
                "primary": ProviderConfig("primary", self.primary.url),
                "backup": ProviderConfig(
                    "backup", self.backup.url, "BACKUP_PROVIDER_API_KEY"
                ),
            },
            model_routes={
                "fast": ModelRoute("fast", "primary", "upstream-fast"),
                "strong": ModelRoute("strong", "backup", "upstream-strong"),
            },
            thinking="disabled",
            display_reasoning=False,
        )
        proxy.reasoning_store = self.store
        proxy.trace_writer = None
        self.proxy = _Fixture(proxy)

    def tearDown(self) -> None:
        self.proxy.close()
        self.primary.close()
        self.backup.close()
        self.store.close()

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        request = Request(
            f"{self.proxy.url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": "Bearer sk-from-copilot",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_chat_routes_alias_to_provider_model_and_provider_key(self) -> None:
        with patch.dict(os.environ, {"BACKUP_PROVIDER_API_KEY": "sk-backup"}):
            status, response = self._post(
                "/v1/chat/completions",
                {
                    "model": "strong",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(response["model"], "strong")
        self.assertEqual(self.primary.server.requests, [])  # type: ignore[attr-defined]
        request = self.backup.server.requests[0]  # type: ignore[attr-defined]
        self.assertEqual(request["path"], "/chat/completions")
        self.assertEqual(request["payload"]["model"], "upstream-strong")
        self.assertEqual(request["authorization"], "Bearer sk-backup")

    def test_responses_routes_alias_and_restores_response_model(self) -> None:
        status, response = self._post(
            "/v1/responses",
            {"model": "fast", "input": "hi"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["model"], "fast")
        request = self.primary.server.requests[0]  # type: ignore[attr-defined]
        self.assertEqual(request["path"], "/responses")
        self.assertEqual(request["payload"]["model"], "upstream-fast")
        self.assertEqual(request["authorization"], "Bearer sk-from-copilot")

    def test_unknown_model_is_rejected_without_upstream_request(self) -> None:
        status, response = self._post(
            "/v1/chat/completions",
            {
                "model": "missing",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

        self.assertEqual(status, 400)
        self.assertEqual(response["error"]["code"], "unknown_model")
        self.assertEqual(self.primary.server.requests, [])  # type: ignore[attr-defined]
        self.assertEqual(self.backup.server.requests, [])  # type: ignore[attr-defined]

    def test_models_endpoint_lists_configured_aliases(self) -> None:
        with urlopen(f"{self.proxy.url}/v1/models", timeout=5) as response:
            payload = json.loads(response.read())

        self.assertEqual([model["id"] for model in payload["data"]], ["fast", "strong"])

    def test_missing_provider_api_key_is_reported(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            status, response = self._post(
                "/v1/chat/completions",
                {
                    "model": "strong",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )

        self.assertEqual(status, 502)
        self.assertEqual(response["error"]["code"], "provider_api_key_missing")
        self.assertEqual(self.backup.server.requests, [])  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()

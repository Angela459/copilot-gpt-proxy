from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any

from .tool_guard import REPAIR_INSTRUCTION, empty_apply_patch_calls


INCOMPLETE_RESPONSES_STREAM_ERROR = (
    "The upstream Responses API stream ended without response.completed. "
    "The proxy stopped after one compatibility retry."
)


@dataclass
class ResponsesAccumulator:
    calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    completed: bool = False

    def ingest(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        if event_type == "response.completed":
            self.completed = True
            response = event.get("response")
            if isinstance(response, dict):
                self._ingest_output(response.get("output"))
            return

        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "function_call":
            self._ingest_call(item, event)

        if event_type == "response.function_call_arguments.delta":
            call = self._call_for_event(event)
            delta = event.get("delta")
            if isinstance(delta, str):
                call["function"]["arguments"] += delta
        elif event_type == "response.function_call_arguments.done":
            call = self._call_for_event(event)
            arguments = event.get("arguments")
            if isinstance(arguments, str):
                call["function"]["arguments"] = arguments

    def messages(self) -> list[dict[str, Any]]:
        return [{"role": "assistant", "tool_calls": list(self.calls.values())}]

    def _ingest_output(self, output: Any) -> None:
        if not isinstance(output, list):
            return
        for index, item in enumerate(output):
            if isinstance(item, dict) and item.get("type") == "function_call":
                self._ingest_call(item, {"output_index": index})

    def _ingest_call(self, item: dict[str, Any], event: dict[str, Any]) -> None:
        key = self._event_key(event, item)
        call = self.calls.setdefault(
            key,
            {
                "id": str(item.get("call_id") or item.get("id") or key),
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        name = item.get("name")
        if isinstance(name, str) and name:
            call["function"]["name"] = name
        arguments = item.get("arguments")
        if isinstance(arguments, str) and arguments:
            call["function"]["arguments"] = arguments

    def _call_for_event(self, event: dict[str, Any]) -> dict[str, Any]:
        key = self._event_key(event)
        return self.calls.setdefault(
            key,
            {
                "id": str(event.get("call_id") or event.get("item_id") or key),
                "type": "function",
                "function": {
                    "name": str(event.get("name") or ""),
                    "arguments": "",
                },
            },
        )

    @staticmethod
    def _event_key(event: dict[str, Any], item: dict[str, Any] | None = None) -> str:
        item = item or {}
        return str(
            event.get("item_id")
            or item.get("id")
            or item.get("call_id")
            or event.get("call_id")
            or f"output_{event.get('output_index', 0)}"
        )


def inspect_responses_body(body: bytes, streaming: bool) -> tuple[list[str], bool]:
    accumulator = ResponsesAccumulator()
    if streaming:
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.startswith(b"data:"):
                continue
            data = stripped[len(b"data:") :].strip()
            if not data or data == b"[DONE]":
                continue
            try:
                accumulator.ingest(json.loads(data.decode("utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
        return empty_apply_patch_calls(accumulator.messages()), accumulator.completed

    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [], True
    if isinstance(payload, dict):
        accumulator._ingest_output(payload.get("output"))
    return empty_apply_patch_calls(accumulator.messages()), True


def repair_responses_request(payload: dict[str, Any]) -> dict[str, Any]:
    repaired = deepcopy(payload)
    instructions = repaired.get("instructions")
    prefix = f"{instructions}\n\n" if isinstance(instructions, str) else ""
    repaired["instructions"] = prefix + REPAIR_INSTRUCTION
    return repaired

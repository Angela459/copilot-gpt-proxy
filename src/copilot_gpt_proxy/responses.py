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

APPLY_PATCH_FUNCTION_DESCRIPTION = (
    "Apply a patch to files. The input field must contain the complete patch text, "
    "starting with '*** Begin Patch' and ending with '*** End Patch'."
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
        if isinstance(item, dict) and item.get("type") in {
            "function_call",
            "custom_tool_call",
        }:
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
        elif event_type == "response.custom_tool_call_input.delta":
            call = self._call_for_event(event)
            delta = event.get("delta")
            if isinstance(delta, str):
                call["function"]["arguments"] += delta
        elif event_type == "response.custom_tool_call_input.done":
            call = self._call_for_event(event)
            tool_input = event.get("input")
            if isinstance(tool_input, str):
                call["function"]["arguments"] = tool_input

    def messages(self) -> list[dict[str, Any]]:
        return [{"role": "assistant", "tool_calls": list(self.calls.values())}]

    def _ingest_output(self, output: Any) -> None:
        if not isinstance(output, list):
            return
        for index, item in enumerate(output):
            if isinstance(item, dict) and item.get("type") in {
                "function_call",
                "custom_tool_call",
            }:
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
        if not isinstance(arguments, str):
            arguments = item.get("input")
        if isinstance(arguments, str):
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
    request_input = repaired.get("input")
    if isinstance(request_input, list):
        repaired["input"] = _remove_empty_apply_patch_history(request_input)
    tools = repaired.get("tools")
    if isinstance(tools, list):
        repaired["tools"] = [_repair_tool(tool) for tool in tools]
    tool_choice = repaired.get("tool_choice")
    if (
        isinstance(tool_choice, dict)
        and tool_choice.get("type") == "custom"
        and tool_choice.get("name") == "apply_patch"
    ):
        repaired["tool_choice"] = {"type": "function", "name": "apply_patch"}
    instructions = repaired.get("instructions")
    prefix = f"{instructions}\n\n" if isinstance(instructions, str) else ""
    repaired["instructions"] = prefix + REPAIR_INSTRUCTION
    return repaired


def _repair_tool(tool: Any) -> Any:
    if not isinstance(tool, dict):
        return tool
    if tool.get("type") != "custom" or tool.get("name") != "apply_patch":
        return tool
    description = tool.get("description")
    if not isinstance(description, str) or not description.strip():
        description = APPLY_PATCH_FUNCTION_DESCRIPTION
    else:
        description = f"{description.rstrip()} {APPLY_PATCH_FUNCTION_DESCRIPTION}"
    return {
        "type": "function",
        "name": "apply_patch",
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Complete patch text from *** Begin Patch through "
                        "*** End Patch."
                    ),
                }
            },
            "required": ["input"],
            "additionalProperties": False,
        },
        "strict": False,
    }


def _remove_empty_apply_patch_history(items: list[Any]) -> list[Any]:
    empty_call_ids = {
        str(item.get("call_id") or item.get("id"))
        for item in items
        if isinstance(item, dict) and _is_empty_apply_patch_item(item)
    }
    if not empty_call_ids:
        return items

    return [
        item
        for item in items
        if not (
            isinstance(item, dict)
            and (
                _is_empty_apply_patch_item(item)
                or (
                    item.get("type")
                    in {
                        "function_call_output",
                        "custom_tool_call_output",
                    }
                    and str(item.get("call_id") or "") in empty_call_ids
                )
            )
        )
    ]


def _is_empty_apply_patch_item(item: dict[str, Any]) -> bool:
    item_type = item.get("type")
    if item_type not in {"function_call", "custom_tool_call"}:
        return False
    if str(item.get("name") or "").strip() != "apply_patch":
        return False
    arguments = item.get("arguments")
    if item_type == "custom_tool_call":
        arguments = item.get("input")
    call = {
        "id": item.get("call_id") or item.get("id"),
        "type": "function",
        "function": {"name": "apply_patch", "arguments": arguments},
    }
    return bool(empty_apply_patch_calls([{"tool_calls": [call]}]))

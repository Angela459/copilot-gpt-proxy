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


def has_custom_apply_patch_tool(payload: dict[str, Any]) -> bool:
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return False
    return any(
        isinstance(tool, dict)
        and tool.get("type") == "custom"
        and tool.get("name") == "apply_patch"
        for tool in tools
    )


def restore_custom_apply_patch_response(body: bytes, streaming: bool) -> bytes:
    if not streaming:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return body
        if not isinstance(payload, dict):
            return body
        _restore_output(payload.get("output"))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

    item_names: dict[str, str] = {}
    rewritten: list[bytes] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith(b"data:"):
            rewritten.append(line)
            continue
        data = stripped[len(b"data:") :].strip()
        if not data or data == b"[DONE]":
            rewritten.append(line)
            continue
        try:
            event = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            rewritten.append(line)
            continue
        if not isinstance(event, dict):
            rewritten.append(line)
            continue
        original_type = event.get("type")
        restored = _restore_stream_event(event, item_names)
        if restored is None:
            if rewritten and rewritten[-1].strip().startswith(b"event:"):
                rewritten.pop()
            continue
        restored_type = restored.get("type")
        if (
            restored_type != original_type
            and isinstance(restored_type, str)
            and rewritten
            and rewritten[-1].strip().startswith(b"event:")
        ):
            rewritten[-1] = f"event: {restored_type}".encode("utf-8")
        rewritten.append(
            b"data: "
            + json.dumps(restored, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
    return b"\n".join(rewritten) + (b"\n" if body.endswith((b"\n", b"\r")) else b"")


def repair_responses_request(payload: dict[str, Any]) -> dict[str, Any]:
    repaired = normalize_responses_request(payload)
    request_input = repaired.get("input")
    if isinstance(request_input, list):
        repaired["input"] = _remove_empty_apply_patch_history(request_input)
    instructions = repaired.get("instructions")
    prefix = f"{instructions}\n\n" if isinstance(instructions, str) else ""
    repaired["instructions"] = prefix + REPAIR_INSTRUCTION
    return repaired


def normalize_responses_request(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(payload)
    tools = normalized.get("tools")
    if isinstance(tools, list):
        normalized["tools"] = [_repair_tool(tool) for tool in tools]
    tool_choice = normalized.get("tool_choice")
    if (
        isinstance(tool_choice, dict)
        and tool_choice.get("type") == "custom"
        and tool_choice.get("name") == "apply_patch"
    ):
        normalized["tool_choice"] = {"type": "function", "name": "apply_patch"}
    return normalized


def _restore_stream_event(
    event: dict[str, Any], item_names: dict[str, str]
) -> dict[str, Any] | None:
    event_type = event.get("type")
    response = event.get("response")
    if isinstance(response, dict):
        _trim_repeated_request_metadata(response)
    item = event.get("item")
    if isinstance(item, dict) and item.get("type") == "function_call":
        item_id = str(item.get("id") or event.get("item_id") or "")
        name = str(item.get("name") or "")
        if item_id:
            item_names[item_id] = name
        if name == "apply_patch":
            event["item"] = _restore_call_item(item)

    item_id = str(event.get("item_id") or "")
    if item_names.get(item_id) == "apply_patch":
        if event_type == "response.function_call_arguments.delta":
            return None
        if event_type == "response.function_call_arguments.done":
            event["type"] = "response.custom_tool_call_input.done"
            event["input"] = _patch_input(event.pop("arguments", ""))

    if event_type == "response.completed":
        if isinstance(response, dict):
            _restore_output(response.get("output"))
    return event


def _trim_repeated_request_metadata(response: dict[str, Any]) -> None:
    if "instructions" in response:
        response["instructions"] = None
    if "tools" in response:
        response["tools"] = []


def _restore_output(output: Any) -> None:
    if not isinstance(output, list):
        return
    for index, item in enumerate(output):
        if (
            isinstance(item, dict)
            and item.get("type") == "function_call"
            and item.get("name") == "apply_patch"
        ):
            output[index] = _restore_call_item(item)


def _restore_call_item(item: dict[str, Any]) -> dict[str, Any]:
    restored = dict(item)
    restored["type"] = "custom_tool_call"
    restored["input"] = _patch_input(restored.pop("arguments", ""))
    return restored


def _patch_input(arguments: Any) -> str:
    if not isinstance(arguments, str):
        return ""
    stripped = arguments.strip()
    if not stripped:
        return ""
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return arguments
    if isinstance(decoded, dict):
        for key in ("input", "patch", "content"):
            value = decoded.get(key)
            if isinstance(value, str):
                return value
        return ""
    if isinstance(decoded, str):
        return decoded
    return ""


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

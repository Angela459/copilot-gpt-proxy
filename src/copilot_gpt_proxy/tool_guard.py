from __future__ import annotations

from copy import deepcopy
import json
from typing import Any


EMPTY_APPLY_PATCH_ERROR = (
    "The upstream model returned apply_patch without non-empty patch content. "
    "The proxy stopped after one compatibility retry to prevent a tool-call loop."
)

REPAIR_INSTRUCTION = (
    "Compatibility retry: your previous response attempted to call apply_patch "
    "without patch content. Repeat the requested task now. If you call "
    "apply_patch, provide the complete non-empty patch string required by the "
    "tool schema. Do not pass an empty object or empty string. If no edit is "
    "needed, explain that instead of calling the tool."
)


def empty_apply_patch_calls(messages: list[dict[str, Any]]) -> list[str]:
    """Return identifiers for completed apply_patch calls with empty arguments."""
    invalid: list[str] = []
    for message in messages:
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for index, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            if str(function.get("name") or "").strip() != "apply_patch":
                continue
            if _has_patch_content(function.get("arguments")):
                continue
            invalid.append(str(tool_call.get("id") or f"tool_call_{index}"))
    return invalid


def messages_from_completion(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return []
    return [
        message
        for choice in choices
        if isinstance(choice, dict)
        for message in [choice.get("message")]
        if isinstance(message, dict)
    ]


def repair_request(payload: dict[str, Any]) -> dict[str, Any]:
    repaired = deepcopy(payload)
    messages = repaired.get("messages")
    if not isinstance(messages, list):
        messages = []
        repaired["messages"] = messages
    messages.append({"role": "system", "content": REPAIR_INSTRUCTION})
    return repaired


def _has_patch_content(arguments: Any) -> bool:
    if isinstance(arguments, dict):
        return _mapping_has_content(arguments)
    if arguments is None:
        return False
    if not isinstance(arguments, str):
        return bool(arguments)

    stripped = arguments.strip()
    if not stripped:
        return False
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        # Some Copilot-facing tool schemas use the patch itself as arguments.
        return True
    if isinstance(decoded, dict):
        return _mapping_has_content(decoded)
    if isinstance(decoded, str):
        return bool(decoded.strip())
    return False


def _mapping_has_content(arguments: dict[Any, Any]) -> bool:
    if not arguments:
        return False
    patch_keys = ("patch", "input", "content")
    present_patch_values = [arguments[key] for key in patch_keys if key in arguments]
    values = present_patch_values or list(arguments.values())
    return any(isinstance(value, str) and bool(value.strip()) for value in values)

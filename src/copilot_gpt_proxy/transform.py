from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from .config import ProxyConfig, ResolvedRoute
from .logging import LOG
from .streaming import fold_reasoning_into_content


SUPPORTED_REQUEST_FIELDS = {
    "model",
    "messages",
    "stream",
    "stream_options",
    "max_tokens",
    "response_format",
    "stop",
    "tools",
    "tool_choice",
    "thinking",
    "reasoning_effort",
    "temperature",
    "top_p",
    "presence_penalty",
    "frequency_penalty",
    "logprobs",
    "top_logprobs",
    "user",
    "seed",
    "n",
    "logit_bias",
}

MESSAGE_FIELDS = {
    "role",
    "content",
    "name",
    "tool_call_id",
    "tool_calls",
}

ROLE_MESSAGE_FIELDS = {
    "system": {"role", "content", "name"},
    "user": {"role", "content", "name"},
    "assistant": {"role", "content", "name", "tool_calls"},
    "tool": {"role", "content", "tool_call_id"},
}

EFFORT_ALIASES = {
    "low": "high",
    "medium": "high",
    "high": "high",
    "max": "max",
    "xhigh": "max",
}

COPILOT_THINKING_BLOCK_RE = re.compile(
    r"""
    (?:
        <(?:think|thinking)\b[^>]*>[\s\S]*?(?:</(?:think|thinking)>|\Z)
        |
        <details\b[^>]*>\s*
        <summary\b[^>]*>\s*Thinking\s*</summary>
        [\s\S]*?(?:</details>|\Z)
    )\s*
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class PreparedRequest:
    payload: dict[str, Any]
    original_model: str
    upstream_model: str
    upstream_base_url: str
    provider_name: str


def normalize_reasoning_effort(value: Any) -> str:
    if not isinstance(value, str):
        return "high"
    return EFFORT_ALIASES.get(value.strip().lower(), "high")


def extract_text_content(content: Any) -> str | None:
    if content is None or isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            item_type = item.get("type")
            text = item.get("text") or item.get("content")
            if isinstance(text, str):
                parts.append(text)
            elif item_type:
                parts.append(f"[{item_type} omitted by proxy]")
        return "\n".join(part for part in parts if part)
    if isinstance(content, (dict, tuple)):
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    return str(content)


def strip_copilot_thinking_blocks(content: str) -> str:
    return COPILOT_THINKING_BLOCK_RE.sub("", content).lstrip("\r\n")


def normalize_tool_call(tool_call: Any) -> dict[str, Any]:
    if not isinstance(tool_call, dict):
        tool_call = {}
    call_type = str(tool_call.get("type") or "function")
    normalized: dict[str, Any] = {
        "id": str(tool_call.get("id") or ""),
        "type": call_type,
    }

    if call_type == "custom":
        custom = tool_call.get("custom") or {}
        if not isinstance(custom, dict):
            custom = {}
        normalized["custom"] = {
            "name": str(custom.get("name") or ""),
            "input": str(custom.get("input") or ""),
        }
    else:
        function = tool_call.get("function") or {}
        if not isinstance(function, dict):
            function = {}
        arguments = function.get("arguments", "")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        normalized["function"] = {
            "name": str(function.get("name") or ""),
            "arguments": arguments,
        }

    if not normalized["id"]:
        normalized.pop("id")
    return normalized


def normalize_tool(tool: Any) -> dict[str, Any]:
    if not isinstance(tool, dict):
        return {
            "type": "function",
            "function": {"name": "", "description": "", "parameters": {}},
        }
    normalized = dict(tool)
    normalized["type"] = normalized.get("type") or "function"
    return normalized


def legacy_function_to_tool(function: Any) -> dict[str, Any]:
    if not isinstance(function, dict):
        function = {}
    return {"type": "function", "function": function}


def convert_function_call(function_call: Any) -> Any:
    if isinstance(function_call, str):
        if function_call in {"auto", "none", "required"}:
            return function_call
        return None
    if isinstance(function_call, dict) and function_call.get("name"):
        return {
            "type": "function",
            "function": {"name": str(function_call["name"])},
        }
    return None


def normalize_tool_choice(tool_choice: Any) -> Any:
    if isinstance(tool_choice, str):
        if tool_choice in {"auto", "none", "required"}:
            return tool_choice
        return None
    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "function":
            function = tool_choice.get("function")
            if isinstance(function, dict) and function.get("name"):
                return {
                    "type": "function",
                    "function": {"name": str(function["name"])},
                }
        return tool_choice
    return tool_choice


def normalize_message(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        message = {"role": "user", "content": str(message)}
    normalized = {key: value for key, value in message.items() if key in MESSAGE_FIELDS}
    role = str(normalized.get("role") or "user")
    normalized["role"] = "tool" if role == "function" else role

    if "content" in normalized:
        normalized["content"] = extract_text_content(normalized["content"]) or ""
    elif normalized["role"] in {"assistant", "tool", "system", "user"}:
        normalized["content"] = ""
    if normalized["role"] == "assistant" and isinstance(
        normalized.get("content"), str
    ):
        normalized["content"] = strip_copilot_thinking_blocks(normalized["content"])

    if normalized.get("tool_calls"):
        normalized["tool_calls"] = [
            normalize_tool_call(tool_call)
            for tool_call in normalized.get("tool_calls") or []
        ]

    allowed_fields = ROLE_MESSAGE_FIELDS.get(normalized["role"], MESSAGE_FIELDS)
    return {key: value for key, value in normalized.items() if key in allowed_fields}


def normalize_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    return [normalize_message(message) for message in messages]


def upstream_route_for(original_model: str, config: ProxyConfig) -> ResolvedRoute:
    return config.resolve_route(original_model)


def upstream_model_for(original_model: str, config: ProxyConfig) -> str:
    return upstream_route_for(original_model, config).upstream_model


def prepare_upstream_request(
    payload: dict[str, Any],
    config: ProxyConfig,
) -> PreparedRequest:
    original_model = str(payload.get("model") or config.upstream_model)
    route = upstream_route_for(original_model, config)

    prepared = {
        key: value for key, value in payload.items() if key in SUPPORTED_REQUEST_FIELDS
    }
    dropped_fields = sorted(
        key
        for key in payload
        if key not in SUPPORTED_REQUEST_FIELDS
        and key not in {"max_completion_tokens", "functions", "function_call"}
    )
    if dropped_fields:
        LOG.warning(
            "dropping unsupported request field(s): %s", ", ".join(dropped_fields)
        )
    if "max_tokens" not in prepared and "max_completion_tokens" in payload:
        prepared["max_tokens"] = payload["max_completion_tokens"]

    prepared["model"] = route.upstream_model
    if prepared.get("stream"):
        stream_options = prepared.get("stream_options")
        stream_options = dict(stream_options) if isinstance(stream_options, dict) else {}
        stream_options["include_usage"] = True
        prepared["stream_options"] = stream_options

    if isinstance(prepared.get("tools"), list):
        prepared["tools"] = [normalize_tool(tool) for tool in prepared["tools"]]
    elif isinstance(payload.get("functions"), list):
        prepared["tools"] = [
            legacy_function_to_tool(function) for function in payload["functions"]
        ]

    if "tool_choice" in prepared:
        tool_choice = normalize_tool_choice(prepared["tool_choice"])
        if tool_choice is None:
            prepared.pop("tool_choice", None)
        else:
            prepared["tool_choice"] = tool_choice
    elif "function_call" in payload:
        tool_choice = convert_function_call(payload.get("function_call"))
        if tool_choice is not None:
            prepared["tool_choice"] = tool_choice

    prepared["thinking"] = {"type": config.thinking}
    if config.thinking == "enabled":
        prepared["reasoning_effort"] = normalize_reasoning_effort(
            config.reasoning_effort
        )
    prepared["messages"] = normalize_messages(payload.get("messages"))

    return PreparedRequest(
        payload=prepared,
        original_model=original_model,
        upstream_model=route.upstream_model,
        upstream_base_url=route.upstream_base_url,
        provider_name=route.provider,
    )


def rewrite_response_body(
    body: bytes,
    original_model: str,
    display_reasoning: bool = False,
    collapsible_reasoning: bool = True,
) -> bytes:
    response_payload = json.loads(body.decode("utf-8"))
    if isinstance(response_payload, dict):
        if display_reasoning:
            fold_reasoning_into_content(response_payload, collapsible_reasoning)
        if "model" in response_payload:
            response_payload["model"] = original_model
    return json.dumps(
        response_payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")

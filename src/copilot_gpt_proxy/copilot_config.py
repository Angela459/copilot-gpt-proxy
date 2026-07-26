from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any


@dataclass(frozen=True)
class CopilotModel:
    model_id: str
    base_url: str | None
    api_mode: str | None
    owned_by: str | None


@dataclass(frozen=True)
class CopilotSettings:
    path: Path
    base_url: str | None
    models: tuple[CopilotModel, ...]

    def selected_model(self, model_id: str | None = None) -> CopilotModel | None:
        if model_id:
            return next(
                (model for model in self.models if model.model_id == model_id), None
            )
        return next(
            (
                model
                for model in self.models
                if not model.model_id.startswith("__provider__")
            ),
            self.models[0] if self.models else None,
        )

    def public_dict(self, model_id: str | None = None) -> dict[str, Any]:
        selected = self.selected_model(model_id)
        return {
            "path": str(self.path),
            "base_url": self.base_url,
            "models": [asdict(model) for model in self.models],
            "selected_model": asdict(selected) if selected else None,
        }


def load_copilot_settings(path: str | Path) -> CopilotSettings:
    settings_path = Path(path).expanduser()
    if not settings_path.is_file():
        raise ValueError(f"Copilot settings file does not exist: {settings_path}")
    try:
        raw = settings_path.read_text(encoding="utf-8")
        payload = json.loads(_strip_json_comments(raw))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Invalid Copilot settings JSON: {settings_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"Copilot settings must contain a JSON object: {settings_path}"
        )

    global_base_url = _optional_string(payload.get("oaicopilot.baseUrl"))
    raw_models = payload.get("oaicopilot.models")
    models: list[CopilotModel] = []
    if isinstance(raw_models, list):
        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                continue
            model_id = _optional_string(raw_model.get("id"))
            if not model_id:
                continue
            models.append(
                CopilotModel(
                    model_id=model_id,
                    base_url=_optional_string(raw_model.get("baseUrl")),
                    api_mode=_optional_string(raw_model.get("apiMode")),
                    owned_by=_optional_string(raw_model.get("owned_by")),
                )
            )
    return CopilotSettings(settings_path, global_base_url, tuple(models))


def update_copilot_proxy_url(
    path: str | Path,
    model_id: str,
    proxy_url: str,
) -> bool:
    settings_path = Path(path).expanduser()
    settings = load_copilot_settings(settings_path)
    selected_model = settings.selected_model(model_id)
    if selected_model is None:
        raise ValueError(f"Copilot model does not exist: {model_id}")
    provider_id = (
        f"__provider__{selected_model.owned_by}" if selected_model.owned_by else None
    )

    source = settings_path.read_bytes().decode("utf-8")
    updated = _rewrite_proxy_urls(
        source,
        model_id,
        provider_id,
        proxy_url.rstrip("/"),
    )
    if updated == source:
        return False

    backup_path = settings_path.with_name(f"{settings_path.name}.copilot-gpt-proxy.bak")
    if not backup_path.exists():
        shutil.copy2(settings_path, backup_path)

    temporary_path = settings_path.with_name(f".{settings_path.name}.tmp")
    try:
        temporary_path.write_bytes(updated.encode("utf-8"))
        temporary_path.chmod(settings_path.stat().st_mode)
        os.replace(temporary_path, settings_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return True


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _strip_json_comments(source: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
        elif char == "/" and next_char == "/":
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                index += 1
        elif char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(source) and source[index : index + 2] != "*/":
                index += 1
            index += 2
        else:
            output.append(char)
            index += 1
    return re.sub(r",(?=\s*[}\]])", "", "".join(output))


@dataclass(frozen=True)
class _JsonToken:
    kind: str
    start: int
    end: int
    value: str | None = None


def _jsonc_tokens(source: str) -> list[_JsonToken]:
    tokens: list[_JsonToken] = []
    index = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if char.isspace():
            index += 1
            continue
        if char == "/" and next_char == "/":
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(source) and source[index : index + 2] != "*/":
                index += 1
            index += 2
            continue
        if char == '"':
            start = index
            index += 1
            escaped = False
            while index < len(source):
                current = source[index]
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    index += 1
                    break
                index += 1
            raw = source[start:index]
            tokens.append(_JsonToken("string", start, index, json.loads(raw)))
            continue
        if char in "{}[]:,":
            tokens.append(_JsonToken(char, index, index + 1))
        index += 1
    return tokens


def _direct_object_properties(
    tokens: list[_JsonToken],
    start: int,
    end: int,
) -> dict[str, _JsonToken]:
    properties: dict[str, _JsonToken] = {}
    depth = 0
    index = start + 1
    while index < end:
        token = tokens[index]
        if token.kind in {"{", "["}:
            depth += 1
        elif token.kind in {"}", "]"}:
            depth -= 1
        elif (
            depth == 0
            and token.kind == "string"
            and index + 2 < end
            and tokens[index + 1].kind == ":"
        ):
            properties[str(token.value)] = tokens[index + 2]
        index += 1
    return properties


def _object_ranges(tokens: list[_JsonToken]) -> list[tuple[int, int]]:
    stack: list[int] = []
    ranges: list[tuple[int, int]] = []
    for index, token in enumerate(tokens):
        if token.kind == "{":
            stack.append(index)
        elif token.kind == "}" and stack:
            ranges.append((stack.pop(), index))
    return ranges


def _rewrite_proxy_urls(
    source: str,
    model_id: str,
    provider_id: str | None,
    proxy_url: str,
) -> str:
    tokens = _jsonc_tokens(source)
    object_ranges = _object_ranges(tokens)
    if not object_ranges:
        raise ValueError("Copilot settings must contain a JSON object")

    root_start, root_end = max(object_ranges, key=lambda item: item[1] - item[0])
    root_properties = _direct_object_properties(tokens, root_start, root_end)
    replacements: list[tuple[int, int, str]] = []
    encoded_url = json.dumps(proxy_url, ensure_ascii=False)

    global_base_url = root_properties.get("oaicopilot.baseUrl")
    if global_base_url is not None:
        if global_base_url.kind != "string":
            raise ValueError("oaicopilot.baseUrl must be a string")
        replacements.append((global_base_url.start, global_base_url.end, encoded_url))

    target_ids = {model_id}
    if provider_id:
        target_ids.add(provider_id)
    found_ids: set[str] = set()
    selected_has_base_url = False
    for start, end in object_ranges:
        if start == root_start:
            continue
        properties = _direct_object_properties(tokens, start, end)
        identifier = properties.get("id")
        if identifier is None or identifier.value not in target_ids:
            continue
        current_id = str(identifier.value)
        found_ids.add(current_id)
        model_base_url = properties.get("baseUrl")
        if model_base_url is not None:
            if model_base_url.kind != "string":
                raise ValueError(f"Copilot model {current_id} baseUrl must be a string")
            replacements.append((model_base_url.start, model_base_url.end, encoded_url))
            if current_id == model_id:
                selected_has_base_url = True

    if model_id not in found_ids:
        raise ValueError(f"Copilot model does not exist: {model_id}")
    if global_base_url is None and not selected_has_base_url:
        raise ValueError(
            "Copilot settings do not define oaicopilot.baseUrl or a model baseUrl"
        )

    updated = source
    for start, end, replacement in sorted(replacements, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    return updated

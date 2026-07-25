from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
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

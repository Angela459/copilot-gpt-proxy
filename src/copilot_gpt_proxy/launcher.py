from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Callable, Mapping

from .copilot_config import CopilotModel, CopilotSettings, load_copilot_settings
from .server import main as run_proxy


@dataclass(frozen=True)
class SettingsCandidate:
    label: str
    path: Path


def standard_settings_candidates(
    environment: Mapping[str, str] | None = None,
) -> tuple[SettingsCandidate, ...]:
    environment = environment or os.environ
    appdata = environment.get("APPDATA")
    if not appdata:
        return ()
    root = Path(appdata)
    return (
        SettingsCandidate(
            "Visual Studio Code",
            root / "Code" / "User" / "settings.json",
        ),
        SettingsCandidate(
            "Visual Studio Code Insiders",
            root / "Code - Insiders" / "User" / "settings.json",
        ),
        SettingsCandidate(
            "VSCodium",
            root / "VSCodium" / "User" / "settings.json",
        ),
    )


def existing_standard_settings(
    environment: Mapping[str, str] | None = None,
) -> tuple[SettingsCandidate, ...]:
    return tuple(
        candidate
        for candidate in standard_settings_candidates(environment)
        if candidate.path.is_file()
    )


def choose_settings_path(
    *,
    explicit_path: Path | None = None,
    input_fn: Callable[[str], str] = input,
) -> Path:
    if explicit_path is not None:
        resolved = explicit_path.expanduser().resolve()
        if not resolved.is_file():
            raise ValueError(f"Copilot settings file does not exist: {resolved}")
        return resolved

    candidates = existing_standard_settings()
    if len(candidates) == 1:
        selected = candidates[0]
        print(f"Detected {selected.label} settings: {selected.path}")
        return selected.path.resolve()
    if len(candidates) > 1:
        print("Detected Copilot settings:")
        for index, candidate in enumerate(candidates, start=1):
            print(f"  {index}. {candidate.label}: {candidate.path}")
        while True:
            choice = input_fn("Select an editor number: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                return candidates[int(choice) - 1].path.resolve()

    print("No settings.json was found at the standard editor locations.")
    selected_file = _select_settings_file()
    if selected_file is None:
        entered = input_fn("Paste the full path to settings.json: ").strip().strip('"')
        selected_file = Path(entered).expanduser() if entered else None
    if selected_file is None or not selected_file.is_file():
        raise ValueError("No valid Copilot settings.json file was selected")
    return selected_file.resolve()


def supported_models(settings: CopilotSettings) -> tuple[CopilotModel, ...]:
    return tuple(
        model
        for model in settings.models
        if not model.model_id.startswith("__provider__")
        and model.api_mode in {None, "openai", "openai-responses"}
    )


def choose_model(
    settings: CopilotSettings,
    *,
    model_id: str | None = None,
    input_fn: Callable[[str], str] = input,
) -> CopilotModel:
    models = supported_models(settings)
    if not models:
        raise ValueError(f"No supported Copilot models were found in {settings.path}")
    if model_id:
        selected = next((model for model in models if model.model_id == model_id), None)
        if selected is None:
            raise ValueError(f"Copilot model does not exist: {model_id}")
        return selected
    if len(models) == 1:
        print(f"Selected model: {models[0].model_id}")
        return models[0]

    print("Available Copilot models:")
    for index, model in enumerate(models, start=1):
        print(f"  {index}. {model.model_id}")
    while True:
        choice = input_fn("Select a model number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            return models[int(choice) - 1]


def upstream_base_url(settings_path: Path, selected_model: CopilotModel) -> str:
    source_settings = load_copilot_settings(settings_path)
    backup_path = settings_path.with_name(f"{settings_path.name}.copilot-gpt-proxy.bak")
    if backup_path.is_file():
        backup_settings = load_copilot_settings(backup_path)
        if backup_settings.selected_model(selected_model.model_id) is not None:
            source_settings = backup_settings

    source_model = source_settings.selected_model(selected_model.model_id)
    if source_model is None:
        raise ValueError(f"Copilot model does not exist: {selected_model.model_id}")
    base_url = source_model.base_url or source_settings.base_url
    if not base_url:
        raise ValueError(
            "The selected Copilot model does not define a third-party API base URL"
        )
    return base_url.rstrip("/")


def write_generated_config(
    template_path: Path,
    config_path: Path,
    *,
    base_url: str,
    model_id: str,
    settings_path: Path,
    ngrok: bool,
) -> None:
    if not template_path.is_file():
        raise ValueError(f"Configuration template does not exist: {template_path}")
    content = template_path.read_text(encoding="utf-8")
    replacements = {
        '"__BASE_URL__"': _yaml_double_quoted(base_url),
        '"__MODEL_ID__"': _yaml_double_quoted(model_id),
        '"__COPILOT_SETTINGS_PATH__"': _yaml_double_quoted(str(settings_path)),
        "__NGROK__": str(ngrok).lower(),
    }
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(content, encoding="utf-8")


def confirm_settings_update() -> bool:
    message = (
        "The selected Copilot model will be connected to this proxy.\n\n"
        "A one-time settings.json.copilot-gpt-proxy.bak backup will be kept.\n"
        "Continue?"
    )
    if os.name == "nt":
        try:
            import ctypes

            return (
                ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                    None,
                    message,
                    "Copilot GPT Proxy",
                    0x1 | 0x40,
                )
                == 1
            )
        except (AttributeError, OSError):
            pass
    print(message)
    return input(
        "Press Enter to continue, or type N to cancel: "
    ).strip().lower() not in {
        "n",
        "no",
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure and start Copilot GPT Proxy"
    )
    parser.add_argument("--reconfigure", action="store_true")
    parser.add_argument("--ngrok", action="store_true")
    parser.add_argument("--no-start", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--model-id")
    parser.add_argument("--config", type=Path, default=Path.cwd() / "config.yaml")
    parser.add_argument(
        "--template",
        type=Path,
        default=Path.cwd() / "config.example.yaml",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config_path = args.config.resolve()
    try:
        if args.reconfigure or not config_path.is_file():
            settings_path = choose_settings_path(explicit_path=args.settings)
            settings = load_copilot_settings(settings_path)
            selected_model = choose_model(settings, model_id=args.model_id)
            base_url = upstream_base_url(settings_path, selected_model)
            write_generated_config(
                args.template.resolve(),
                config_path,
                base_url=base_url,
                model_id=selected_model.model_id,
                settings_path=settings_path,
                ngrok=args.ngrok,
            )
            print(f"Generated configuration: {config_path}")
            print(f"Upstream model: {selected_model.model_id}")
            print(f"Upstream base URL: {base_url}")
        if args.no_start:
            return 0
        if not confirm_settings_update():
            return 0
        return run_proxy(
            [
                "--config",
                str(config_path),
                "--ngrok" if args.ngrok else "--no-ngrok",
            ]
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _select_settings_file() -> Path | None:
    try:
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        selected = filedialog.askopenfilename(
            title="Select Copilot settings.json",
            filetypes=[("VS Code settings", "settings.json"), ("JSON files", "*.json")],
        )
        root.destroy()
        return Path(selected) if selected else None
    except (ImportError, OSError, RuntimeError):
        return None


def _yaml_double_quoted(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


if __name__ == "__main__":
    raise SystemExit(main())

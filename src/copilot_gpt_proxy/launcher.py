from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen

from .config import ProxyConfig
from .tunnel import (
    DEFAULT_NGROK_API_URL,
    local_tunnel_target,
    ngrok_agent_urls,
    parse_ngrok_public_url,
)


DEFAULT_MODEL = "gpt-5.4"
DEFAULT_WIRE_API = "responses"


def choose_copilot_app(
    *,
    explicit_path: Path | None = None,
    input_fn: Callable[[str], str] = input,
) -> Path:
    if explicit_path is not None:
        return _validate_copilot_app(explicit_path)

    print("Select the GitHub Copilot App executable (github.exe).")
    print("Common locations:")
    print(r"  %LOCALAPPDATA%\Programs\GitHub Copilot\github.exe")
    print(r"  C:\Program Files\GitHub Copilot\github.exe")
    print("  Or the custom installation directory you selected.")
    selected_file = _select_copilot_app_file()
    if selected_file is None:
        entered = input_fn("Paste the full path to github.exe: ").strip().strip('"')
        selected_file = Path(entered).expanduser() if entered else None
    if selected_file is None:
        raise ValueError("No GitHub Copilot App executable was selected")
    return _validate_copilot_app(selected_file)


def prompt_value(
    prompt: str,
    *,
    default: str | None = None,
    input_fn: Callable[[str], str] = input,
) -> str:
    suffix = f" [{default}]" if default else ""
    value = input_fn(f"{prompt}{suffix}: ").strip()
    value = value or (default or "")
    if not value:
        raise ValueError(f"{prompt} is required")
    return value


def write_fresh_config(
    template_path: Path,
    config_path: Path,
    *,
    base_url: str,
    model_id: str,
    app_path: Path,
    wire_api: str,
) -> None:
    if not template_path.is_file():
        raise ValueError(f"Configuration template does not exist: {template_path}")
    content = template_path.read_text(encoding="utf-8")
    replacements = {
        '"__BASE_URL__"': _yaml_double_quoted(base_url.rstrip("/")),
        '"__MODEL_ID__"': _yaml_double_quoted(model_id),
        '"__COPILOT_APP_PATH__"': _yaml_double_quoted(str(app_path)),
        '"__COPILOT_WIRE_API__"': _yaml_double_quoted(wire_api),
        "__NGROK__": "false",
    }
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(content, encoding="utf-8")


def update_launcher_config(
    config_path: Path,
    *,
    app_path: Path,
    base_url: str | None = None,
    model_id: str | None = None,
    wire_api: str = DEFAULT_WIRE_API,
) -> None:
    source = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    values: dict[str, str] = {
        "copilot_app_path": str(app_path),
        "copilot_wire_api": wire_api,
    }
    if base_url is not None:
        values["base_url"] = base_url.rstrip("/")
    if model_id is not None:
        values["model"] = model_id

    legacy_keys = {"copilot_settings_path", "copilot_model_id"}
    output: list[str] = []
    replaced: set[str] = set()
    for line in source.splitlines():
        stripped = line.lstrip()
        key = stripped.split(":", 1)[0] if ":" in stripped else ""
        if key in legacy_keys:
            continue
        if key in values and len(line) == len(stripped):
            output.append(f"{key}: {_yaml_double_quoted(values[key])}")
            replaced.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in replaced:
            output.append(f"{key}: {_yaml_double_quoted(value)}")
    config_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def copilot_environment(config: ProxyConfig, proxy_url: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "COPILOT_PROVIDER_BASE_URL": proxy_url.rstrip("/"),
            "COPILOT_PROVIDER_TYPE": "openai",
            "COPILOT_PROVIDER_WIRE_API": config.copilot_wire_api,
            "COPILOT_PROVIDER_TRANSPORT": "http",
            "COPILOT_MODEL": config.upstream_model,
            "COPILOT_PROVIDER_MODEL_ID": config.upstream_model,
            "COPILOT_PROVIDER_WIRE_MODEL": config.upstream_model,
        }
    )
    return environment


def wait_for_proxy(
    process: subprocess.Popen[bytes],
    health_url: str,
    *,
    timeout: float = 15.0,
) -> None:
    deadline = time.monotonic() + timeout
    last_error = "proxy did not respond"
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"Proxy exited during startup with code {return_code}")
        try:
            with urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, URLError) as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for proxy: {last_error}")


def wait_for_ngrok_url(
    process: subprocess.Popen[bytes],
    *,
    timeout: float = 15.0,
) -> str:
    deadline = time.monotonic() + timeout
    last_error = "ngrok did not report a public URL"
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"Proxy exited during startup with code {return_code}")
        for api_url in ngrok_agent_urls(DEFAULT_NGROK_API_URL):
            try:
                with urlopen(api_url, timeout=1) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                public_url = parse_ngrok_public_url(payload)
                if public_url:
                    return f"{public_url.rstrip('/')}/v1"
            except (OSError, URLError, json.JSONDecodeError) as exc:
                last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for ngrok: {last_error}")


def launch_copilot_app(app_path: Path, environment: dict[str, str]) -> None:
    subprocess.Popen(
        [str(app_path)],
        cwd=str(app_path.parent),
        env=environment,
    )


def confirm_launch(app_path: Path) -> bool:
    message = (
        "Close GitHub Copilot App completely before continuing.\n\n"
        "The proxy will start first, then Copilot App will reopen using it.\n"
        f"App: {app_path}\n\n"
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
    ).strip().lower() not in {"n", "no"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure, start, and connect GitHub Copilot App to the proxy"
    )
    parser.add_argument("--reconfigure", action="store_true")
    parser.add_argument("--ngrok", action="store_true")
    parser.add_argument("--no-start", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-launch-app", action="store_true")
    parser.add_argument("--copilot-app", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--model-id")
    parser.add_argument(
        "--wire-api",
        choices=["completions", "responses"],
        default=DEFAULT_WIRE_API,
    )
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
    proxy_process: subprocess.Popen[bytes] | None = None
    try:
        existing = ProxyConfig.from_file(config_path) if config_path.is_file() else None
        configured_app = existing.copilot_app_path if existing else None
        needs_app = configured_app is None or not configured_app.is_file()
        if args.reconfigure or needs_app or not config_path.is_file():
            app_path = choose_copilot_app(explicit_path=args.copilot_app)
            if existing is None:
                base_url = args.base_url or prompt_value("Third-party API Base URL")
                model_id = args.model_id or prompt_value(
                    "Model ID", default=DEFAULT_MODEL
                )
                write_fresh_config(
                    args.template.resolve(),
                    config_path,
                    base_url=base_url,
                    model_id=model_id,
                    app_path=app_path,
                    wire_api=args.wire_api,
                )
            else:
                base_url = args.base_url
                model_id = args.model_id
                if args.reconfigure:
                    base_url = base_url or prompt_value(
                        "Third-party API Base URL",
                        default=existing.upstream_base_url,
                    )
                    model_id = model_id or prompt_value(
                        "Model ID", default=existing.upstream_model
                    )
                update_launcher_config(
                    config_path,
                    app_path=app_path,
                    base_url=base_url,
                    model_id=model_id,
                    wire_api=args.wire_api,
                )
            print(f"Generated configuration: {config_path}")

        config = ProxyConfig.from_file(config_path)
        app_path = config.copilot_app_path
        if app_path is None or not app_path.is_file():
            raise ValueError("GitHub Copilot App executable is not configured")
        if args.no_start:
            return 0
        if not args.no_launch_app and not confirm_launch(app_path):
            return 0

        proxy_argv = [
            sys.executable,
            "-m",
            "copilot_gpt_proxy",
            "--config",
            str(config_path),
            "--ngrok" if args.ngrok else "--no-ngrok",
        ]
        proxy_process = subprocess.Popen(proxy_argv)
        local_origin = local_tunnel_target(config.host, config.port)
        local_url = f"{local_origin}/v1"
        wait_for_proxy(proxy_process, f"{local_origin}/healthz")
        proxy_url = wait_for_ngrok_url(proxy_process) if args.ngrok else local_url
        if not args.no_launch_app:
            launch_copilot_app(app_path, copilot_environment(config, proxy_url))
            print(f"Started GitHub Copilot App with API Base URL: {proxy_url}")
        return proxy_process.wait()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if proxy_process is not None and proxy_process.poll() is None:
            proxy_process.terminate()
            try:
                proxy_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proxy_process.kill()
                proxy_process.wait(timeout=5)


def _select_copilot_app_file() -> Path | None:
    try:
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        selected = filedialog.askopenfilename(
            title="Select GitHub Copilot App (github.exe)",
            filetypes=[("GitHub Copilot App", "github.exe"), ("Programs", "*.exe")],
        )
        root.destroy()
        return Path(selected) if selected else None
    except (ImportError, OSError, RuntimeError):
        return None


def _validate_copilot_app(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.name.lower() != "github.exe":
        raise ValueError(f"GitHub Copilot App github.exe does not exist: {resolved}")
    return resolved


def _yaml_double_quoted(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


if __name__ == "__main__":
    raise SystemExit(main())

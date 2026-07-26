@echo off
setlocal
cd /d "%~dp0"

uv run python -m copilot_gpt_proxy.launcher %*
set "proxy_exit_code=%errorlevel%"

if not "%proxy_exit_code%"=="0" (
    echo.
    echo copilot-gpt-proxy exited with code %proxy_exit_code%.
)
pause
exit /b %proxy_exit_code%

@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "proxy_exit_code=%errorlevel%"

if not "%proxy_exit_code%"=="0" (
    echo.
    echo copilot-gpt-proxy exited with code %proxy_exit_code%.
)
pause
exit /b %proxy_exit_code%

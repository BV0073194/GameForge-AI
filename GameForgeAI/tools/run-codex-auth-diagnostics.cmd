@echo off
setlocal
cd /d "%~dp0.."
echo GameForge Codex Auth Deep Diagnostics
echo.
where py >nul 2>nul && (py -3 tools\codex_auth_deep_diagnostics.py & goto :done)
where python >nul 2>nul && (python tools\codex_auth_deep_diagnostics.py & goto :done)
echo Python was not found in this shell.
:done
echo.
echo The report is named gameforge-codex-auth-diagnostics-*.txt
echo It intentionally omits credential values. Send that TXT file for analysis.
pause

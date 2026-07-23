@echo off
REM Double-click to sync the LuGroupLib KiCad library from the server.
REM Edit client_config.json first (copy client_config.example.json).
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py sync_client.py %*
) else (
  python sync_client.py %*
)

echo.
pause

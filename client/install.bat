@echo off
REM Double-click to set up LuGroupLib for KiCad on this machine (one time).
REM Close KiCad first - it overwrites its own config when it exits.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py install.py %*
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    python install.py %*
  ) else (
    echo.
    echo Python was not found.
    echo Install Python 3 from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH", then run this again.
  )
)

echo.
pause

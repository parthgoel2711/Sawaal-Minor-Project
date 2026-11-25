@echo off
REM Presentation mode for Windows. No API key needed.
cd /d "%~dp0"
if not exist .venv ( python -m venv .venv || goto :error )
call .venv\Scripts\python.exe -m pip install -q -r backend\requirements.txt || goto :error
if not exist frontend\dist\index.html (
  pushd frontend
  call npm install --no-audit --no-fund || goto :error
  call npm run build || goto :error
  popd
)
set DEMO_MODE=true
set OPEN_BROWSER=1
echo.
echo   Sawaal demo (no login).
echo.
cd backend
..\.venv\Scripts\python.exe -m app
goto :eof
:error
echo Setup failed.
pause

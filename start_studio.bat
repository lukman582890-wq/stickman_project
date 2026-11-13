@echo off
title Stickman Hybrid Studio
set "TEMP=e:\Youtube Content\Stickman Project\.cache\tmp"
set "TMP=e:\Youtube Content\Stickman Project\.cache\tmp"
if not exist "%TEMP%" mkdir "%TEMP%"

echo Starting Stickman Hybrid Studio on http://localhost:8000 ...
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000"
"e:\Youtube Content\Stickman Project\.venv\Scripts\uvicorn.exe" app.main:app --app-dir "%~dp0backend" --host 0.0.0.0 --port 8000
pause

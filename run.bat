@echo off
cd /d "%~dp0"

start "SAGE Backend" cmd /k ".\.venv\Scripts\python.exe -m uvicorn sage.main:app --host 0.0.0.0 --port 8000 --loop asyncio"

start "SAGE Frontend" /D "%~dp0frontend" cmd /k "bun run dev"
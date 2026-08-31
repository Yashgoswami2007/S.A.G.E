@echo off
setlocal enabledelayedexpansion

echo.
echo ===================================================
echo  SAGE - Sovereign On-Premise Agentic AI Workbench
echo ===================================================
echo.

:: ── 1. Python check ──────────────────────────────────
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found in PATH.  Install Python 3.11+ and retry.
    pause
    exit /b 1
)

:: ── 2. Set project root ──────────────────────────────
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

:: ── 3. Virtual environment ───────────────────────────
echo [1/6] Setting up virtual environment...
if not exist "%ROOT%\.venv\Scripts\activate.bat" (
    python -m venv "%ROOT%\.venv"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)
call "%ROOT%\.venv\Scripts\activate.bat"

:: ── 4. Install / upgrade packages ────────────────────
echo [2/6] Installing backend dependencies...
pip install -q -e "%ROOT%\backend"
if %errorlevel% neq 0 (
    echo [ERROR] Backend install failed.
    pause
    exit /b 1
)

echo [3/6] Installing SAGE CLI...
pip install -q -e "%ROOT%\cli"
if %errorlevel% neq 0 (
    echo [ERROR] CLI install failed.
    pause
    exit /b 1
)

:: ── 4b. Ensure huggingface_hub is available for model downloads ──
pip install -q "huggingface_hub[cli]>=0.23.0"

:: ── 5. Model check + download ────────────────────────
echo [4/6] Checking model files...
echo.

:: Model 1: Qwen3-8B (primary — reasoning/general)
set "QWEN_FILE=%ROOT%\models\Qwen3-8B-Q4_K_M.gguf"
if exist "%QWEN_FILE%" (
    echo   [OK]  Qwen3-8B-Q4_K_M.gguf found ^(primary reasoning/general model^)
) else (
    echo   [DL]  Qwen3-8B-Q4_K_M.gguf not found - downloading from HuggingFace...
    echo         Repo: Qwen/Qwen3-8B-GGUF  ~6 GB  ^(this will take a while^)
    huggingface-cli download Qwen/Qwen3-8B-GGUF --include "*Q4_K_M*" --local-dir "%ROOT%\models"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to download Qwen3-8B. Check your internet connection.
        echo         In air-gap mode: manually copy Qwen3-8B-Q4_K_M.gguf to .\models\
        pause
        exit /b 1
    )
    echo   [OK]  Qwen3-8B download complete.
)

:: Model 2: Gemma 4 12B IT (specialist — coding/vision)
set "GEMMA_FILE=%ROOT%\models\gemma-4-12b-it-Q4_K_M.gguf"
if exist "%GEMMA_FILE%" (
    echo   [OK]  gemma-4-12b-it-Q4_K_M.gguf found ^(specialist coding/vision model^)
) else (
    echo   [DL]  gemma-4-12b-it-Q4_K_M.gguf not found - downloading from HuggingFace...
    echo         Repo: unsloth/gemma-4-12b-it-GGUF  ~8 GB  ^(this will take a while^)
    huggingface-cli download unsloth/gemma-4-12b-it-GGUF --include "*Q4_K_M*" --local-dir "%ROOT%\models"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to download Gemma 4 12B. Check your internet connection.
        echo         In air-gap mode: manually copy gemma-4-12b-it-Q4_K_M.gguf to .\models\
        echo         Continuing without specialist model ^(coding/vision tasks will fall back to Qwen3^)
        echo.
        :: Non-fatal — SAGE can still run with just the primary model
        goto SKIP_GEMMA_CHECK
    )
    echo   [OK]  Gemma 4 12B download complete.
)
:SKIP_GEMMA_CHECK

echo.

:: ── 6. Optional: Docker services (skip gracefully if Docker absent) ──
where docker >nul 2>nul
if %errorlevel% equ 0 (
    echo [5/6] Starting Docker services ^(PostgreSQL + Redis^)...
    docker compose -f "%ROOT%\docker-compose.dev.yml" up -d postgres redis >nul 2>nul
    if %errorlevel% neq 0 (
        echo [WARN] Docker services did not start - continuing without them.
        echo        ^(Run 'docker compose up -d postgres redis' manually if needed^)
    ) else (
        echo       Waiting 8 s for services to become healthy...
        timeout /t 8 /nobreak >nul
    )
) else (
    echo [5/6] Docker not found - skipping Postgres/Redis start.
    echo       ^(Fine for local/model-only usage^)
)

:: ── 7. Launch backend in a separate window ───────────
echo [6/6] Launching SAGE backend on http://localhost:8000 ...
echo       ^(qwen3-8b will auto-start; if it fails gemma-4-12b activates as fallback^)
start "SAGE Backend" cmd /k "call "%ROOT%\.venv\Scripts\activate.bat" && cd /d "%ROOT%\backend" && uvicorn sage.main:app --host 0.0.0.0 --port 8000 --loop asyncio"

:: ── 8. Wait for backend to accept connections ─────────
echo.
echo Waiting for backend to become ready...
set /a TRIES=0
:WAIT_LOOP
timeout /t 2 /nobreak >nul
python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >nul 2>nul
if %errorlevel% equ 0 goto BACKEND_UP
set /a TRIES+=1
if %TRIES% lss 15 goto WAIT_LOOP
echo [WARN] Backend did not respond after 30 s - launching CLI anyway.
goto LAUNCH_CLI

:BACKEND_UP
echo Backend is up.

:: ── 9. Drop into the SAGE CLI ─────────────────────────
:LAUNCH_CLI
echo.
echo ===================================================
echo  SAGE is ready.
echo.
echo  Backend : http://localhost:8000
echo  API docs: http://localhost:8000/docs
echo.
echo  Model stack ^(RTX 5060 / 8 GB VRAM^):
echo    [PRIMARY]    Qwen3-8B       ^(~6 GB^) - reasoning/general  - auto-starts
echo    [FALLBACK]   Gemma 4 12B   ^(~8 GB^) - coding/vision/general - auto-activates if Qwen3 fails
echo    ^(Only ONE model loaded at a time - router swaps automatically^)
echo    ^(If Qwen3-8B fails to load or crashes, Gemma-4-12B is activated automatically^)
echo.
echo  CLI commands:
echo    sage health                           - check backend + model status
echo    sage ask "your prompt"               - run an agent task ^(auto-routes^)
echo    sage ask "..." --profile coder       - force coding profile ^(Gemma 4^)
echo    sage ask "..." --profile analyst     - analysis profile ^(Qwen3^)
echo    sage ask "..." --profile inspector   - inspection profile
echo    sage ask "..." --profile general     - general purpose ^(Qwen3^)
echo ===================================================
echo.

:: Run health check so the user sees model/service status immediately
sage health

:: Keep the window open for interactive CLI use
echo.
echo Type 'sage ask "..."' to start chatting, or any other sage command.
echo Type 'exit' to quit.
echo.
cmd /k "call "%ROOT%\.venv\Scripts\activate.bat""

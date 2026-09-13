import os
import pytest
from pathlib import Path
import asyncio

from sage.config import settings
from sage.sandbox.sandbox_manager import SandboxManager

@pytest.fixture
def sandbox():
    # Setup test workspace
    old_runs = settings.SANDBOX_RUNS_DIR
    old_workspace = settings.WORKSPACE_DIR
    
    settings.WORKSPACE_DIR = "./test_workspace"
    settings.SANDBOX_RUNS_DIR = "./test_workspace/sandbox_runs"
    
    Path(settings.WORKSPACE_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.SANDBOX_RUNS_DIR).mkdir(parents=True, exist_ok=True)
    
    manager = SandboxManager()
    yield manager
    
    # Teardown
    import shutil
    shutil.rmtree("./test_workspace", ignore_errors=True)
    settings.SANDBOX_RUNS_DIR = old_runs
    settings.WORKSPACE_DIR = old_workspace

@pytest.mark.asyncio
async def test_execute_python_code(sandbox):
    code = "print('Hello from sandbox!')"
    result = await sandbox.execute_code(code, language="python")
    
    assert result.success is True
    assert result.exit_code == 0
    assert "Hello from sandbox!" in result.stdout
    assert result.stderr == ""
    assert result.sandbox_id is not None
    assert result.duration_ms > 0

@pytest.mark.asyncio
async def test_execute_python_code_error(sandbox):
    code = "1 / 0"
    result = await sandbox.execute_code(code, language="python")
    
    assert result.success is False
    assert result.exit_code != 0
    assert "ZeroDivisionError" in result.stderr

@pytest.mark.asyncio
async def test_execute_command(sandbox):
    # Test executing a simple shell command
    # Windows-friendly command
    command = "echo Hello Sandbox"
    result = await sandbox.execute_command(command)
    
    assert result.success is True
    assert result.exit_code == 0
    assert "Hello Sandbox" in result.stdout

@pytest.mark.asyncio
async def test_run_script(sandbox):
    script_path = Path(settings.WORKSPACE_DIR) / "test_script.py"
    script_path.write_text("print('Executing file!')", encoding="utf-8")
    
    result = await sandbox.run_script("test_script.py")
    
    assert result.success is True
    assert result.exit_code == 0
    assert "Executing file!" in result.stdout

@pytest.mark.asyncio
async def test_sandbox_cancellation(sandbox):
    # Run a long-running process
    code = "import time; time.sleep(5); print('Done')"
    
    # Start execution as a task
    task = asyncio.create_task(sandbox.execute_code(code, language="python"))
    
    # Give it a moment to start and get the sandbox_id
    await asyncio.sleep(0.5)
    
    # Cancel it
    sandbox_ids = list(sandbox._running.keys())
    assert len(sandbox_ids) > 0
    sandbox_id = sandbox_ids[0]
    
    cancelled = await sandbox.cancel(sandbox_id)
    assert cancelled is True
    
    result = await task
    # The process should have been killed, resulting in failure
    assert result.success is False
    assert result.exit_code != 0

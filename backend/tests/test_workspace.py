import pytest
import os
import shutil
import tempfile
from pathlib import Path
from sage.workspace.manager import WorkspaceManager
from sage.core.exceptions import WorkspaceInvalidError

@pytest.fixture
def temp_workspace_env():
    # Setup
    test_dir = Path(tempfile.mkdtemp())
    default_ws = test_dir / "default_workspace"
    default_ws.mkdir()
    state_file = test_dir / "state.json"
    
    manager = WorkspaceManager(
        default_workspace=str(default_ws),
        state_file=state_file
    )
    yield manager, test_dir
    
    # Teardown
    shutil.rmtree(test_dir, ignore_errors=True)

def test_manager_init(temp_workspace_env):
    manager, test_dir = temp_workspace_env
    info = manager.get_workspace_info()
    
    assert info.mode == "default"
    assert info.exists is True
    assert Path(info.active_workspace).name == "default_workspace"

def test_set_active_workspace(temp_workspace_env):
    manager, test_dir = temp_workspace_env
    new_ws = test_dir / "custom_workspace"
    new_ws.mkdir()
    
    info = manager.set_active_workspace(str(new_ws))
    assert info.mode == "custom"
    assert info.active_workspace == str(new_ws.resolve())
    
    # Check if recent list updated
    recent = manager.get_recent_workspaces()
    assert str(new_ws.resolve()) in recent

def test_invalid_workspace(temp_workspace_env):
    manager, test_dir = temp_workspace_env
    invalid_ws = test_dir / "does_not_exist"
    
    with pytest.raises(WorkspaceInvalidError):
        manager.set_active_workspace(str(invalid_ws))

def test_path_resolution_and_containment(temp_workspace_env):
    manager, test_dir = temp_workspace_env
    
    # Resolves within active
    active = Path(manager.get_active_workspace())
    resolved = manager.resolve_path("uploads/test.txt")
    assert resolved == active / "uploads" / "test.txt"
    
    # Traversal should fail
    with pytest.raises(PermissionError):
        manager.resolve_path("../outside.txt")
        
    with pytest.raises(PermissionError):
        manager.resolve_path("/absolute/path/outside.txt")

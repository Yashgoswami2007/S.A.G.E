import pytest
from sage.tool_factory.models import ToolSpecification, FactoryError, ToolSynthesisState
from sage.security.policy import SecurityProfile
from sage.tool_factory.validator import ToolValidator

def test_ast_validator_blocks_os():
    code = "import os\nos.system('ls')"
    profile = SecurityProfile(name="test", blocked_modules=["os"])
    
    with pytest.raises(FactoryError) as exc:
        ToolValidator.validate_code(code, profile)
        
    assert exc.value.stage == ToolSynthesisState.VALIDATING
    assert exc.value.error_type == "AST_VALIDATION_ERROR"
    assert "os" in exc.value.details

def test_ast_validator_blocks_alias():
    code = "import os as sys_os\nsys_os.system('ls')"
    profile = SecurityProfile(name="test", blocked_modules=["os"])
    
    with pytest.raises(FactoryError) as exc:
        ToolValidator.validate_code(code, profile)
        
    assert "os" in exc.value.details

def test_ast_validator_blocks_from_import():
    code = "from os import system\nsystem('ls')"
    profile = SecurityProfile(name="test", blocked_modules=["os"])
    
    with pytest.raises(FactoryError) as exc:
        ToolValidator.validate_code(code, profile)

def test_ast_validator_blocks_importlib():
    code = "import importlib"
    profile = SecurityProfile(name="test")
    
    with pytest.raises(FactoryError) as exc:
        ToolValidator.validate_code(code, profile)
        
    assert "importlib" in exc.value.details

def test_ast_validator_blocks_eval():
    code = "eval('1+1')"
    profile = SecurityProfile(name="test")
    
    with pytest.raises(FactoryError) as exc:
        ToolValidator.validate_code(code, profile)
        
    assert "eval" in exc.value.details

def test_spec_validation_blocks_network():
    spec = ToolSpecification(
        name="test",
        description="test",
        capability="test",
        permissions={"network": True, "subprocess": False}
    )
    profile = SecurityProfile(name="test", allow_network=False)
    
    with pytest.raises(FactoryError) as exc:
        ToolValidator.validate_specification(spec, profile)
        
    assert "Network access requested but denied" in exc.value.details

def test_spec_validation_blocks_subprocess():
    spec = ToolSpecification(
        name="test",
        description="test",
        capability="test",
        permissions={"network": False, "subprocess": True}
    )
    profile = SecurityProfile(name="test", allow_subprocess=False)
    
    with pytest.raises(FactoryError) as exc:
        ToolValidator.validate_specification(spec, profile)
        
    assert "Subprocess execution requested but denied" in exc.value.details

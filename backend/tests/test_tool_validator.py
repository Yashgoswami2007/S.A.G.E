"""Unit tests for tool_factory validator."""
import pytest
from sage.tool_factory.validator import ToolValidator, ASTValidator
from sage.tool_factory.models import ToolSpecification, PermissionRequest
from sage.security.policy import SecurityProfile


@pytest.fixture
def safe_profile():
    return SecurityProfile(
        name="SAFE",
        allow_network=False,
        allow_subprocess=False,
        allow_filesystem_read=True,
        allow_filesystem_write=True,
        blocked_modules=["os", "sys", "subprocess", "socket", "ctypes", "importlib", "pickle", "shutil"],
        execution_timeout=60
    )


class TestASTValidation:
    def test_clean_code_passes(self, safe_profile):
        code = '''
import json
import math

def compute(x):
    return math.sqrt(x)
'''
        is_valid, errors = ToolValidator.validate_code(code, safe_profile)
        assert is_valid
        assert errors == []

    def test_blocked_import_os(self, safe_profile):
        code = '''
import os
print(os.listdir("."))
'''
        is_valid, errors = ToolValidator.validate_code(code, safe_profile)
        assert not is_valid
        assert any("os" in e for e in errors)

    def test_blocked_import_from_subprocess(self, safe_profile):
        code = '''
from subprocess import run
run(["ls"])
'''
        is_valid, errors = ToolValidator.validate_code(code, safe_profile)
        assert not is_valid
        assert any("subprocess" in e for e in errors)

    def test_blocked_eval_call(self, safe_profile):
        code = '''
result = eval("1+1")
'''
        is_valid, errors = ToolValidator.validate_code(code, safe_profile)
        assert not is_valid
        assert any("eval" in e for e in errors)

    def test_blocked_exec_call(self, safe_profile):
        code = '''
exec("print('hello')")
'''
        is_valid, errors = ToolValidator.validate_code(code, safe_profile)
        assert not is_valid
        assert any("exec" in e for e in errors)

    def test_syntax_error(self, safe_profile):
        code = '''
def broken(
    pass
'''
        is_valid, errors = ToolValidator.validate_code(code, safe_profile)
        assert not is_valid
        assert any("Syntax error" in e for e in errors)

    def test_allowed_standard_library(self, safe_profile):
        code = '''
import json
import csv
import re
import math
import datetime
data = json.dumps({"key": "value"})
'''
        is_valid, errors = ToolValidator.validate_code(code, safe_profile)
        assert is_valid
        assert errors == []


class TestSpecificationValidation:
    def test_valid_spec_passes(self, safe_profile):
        spec = ToolSpecification(
            name="test_tool",
            description="A test tool",
            capability="testing",
            permissions=PermissionRequest(network=False, subprocess=False)
        )
        is_valid, errors = ToolValidator.validate_specification(spec, safe_profile)
        assert is_valid
        assert errors == []

    def test_network_denied(self, safe_profile):
        spec = ToolSpecification(
            name="net_tool",
            description="Needs network",
            capability="network_op",
            permissions=PermissionRequest(network=True, subprocess=False)
        )
        is_valid, errors = ToolValidator.validate_specification(spec, safe_profile)
        assert not is_valid
        assert any("Network" in e for e in errors)

    def test_subprocess_denied(self, safe_profile):
        spec = ToolSpecification(
            name="proc_tool",
            description="Needs subprocess",
            capability="run_cmd",
            permissions=PermissionRequest(network=False, subprocess=True)
        )
        is_valid, errors = ToolValidator.validate_specification(spec, safe_profile)
        assert not is_valid
        assert any("Subprocess" in e for e in errors)

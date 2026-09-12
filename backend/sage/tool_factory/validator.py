import ast
from typing import List, Tuple
from sage.tool_factory.models import ToolSpecification, FactoryError, ToolSynthesisState
from sage.security.policy import SecurityProfile

class ASTValidator(ast.NodeVisitor):
    def __init__(self, profile: SecurityProfile):
        self.profile = profile
        self.errors: List[str] = []
        self.disallowed_functions = {"eval", "exec", "globals", "locals", "compile", "__import__"}
        
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            base_module = alias.name.split('.')[0]
            if base_module in self.profile.blocked_modules or base_module == "importlib":
                self.errors.append(f"Unauthorized import: '{alias.name}' is blocked by security policy.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            base_module = node.module.split('.')[0]
            if base_module in self.profile.blocked_modules or base_module == "importlib":
                self.errors.append(f"Unauthorized import from: '{node.module}' is blocked by security policy.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            if node.func.id in self.disallowed_functions:
                self.errors.append(f"Unauthorized function call: '{node.func.id}' is not allowed.")
        self.generic_visit(node)


class ToolValidator:
    """Validates generated tool specifications and code."""
    
    @staticmethod
    def validate_code(code: str, profile: SecurityProfile) -> bool:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise FactoryError(
                stage=ToolSynthesisState.VALIDATING,
                error_type="SYNTAX_ERROR",
                message="Syntax error in generated code.",
                details=str(e),
                repairable=True
            )
        
        visitor = ASTValidator(profile)
        visitor.visit(tree)
        
        if visitor.errors:
            raise FactoryError(
                stage=ToolSynthesisState.VALIDATING,
                error_type="AST_VALIDATION_ERROR",
                message="Code contains unauthorized operations.",
                details="\n".join(visitor.errors),
                repairable=True
            )
        return True

    @staticmethod
    def validate_specification(spec: ToolSpecification, profile: SecurityProfile) -> bool:
        errors = []
        
        # Check Network
        if spec.permissions.network and not profile.allow_network:
            errors.append("Network access requested but denied by profile policy.")
            
        # Check Subprocess
        if spec.permissions.subprocess and not profile.allow_subprocess:
            errors.append("Subprocess execution requested but denied by profile policy.")
            
        if errors:
            raise FactoryError(
                stage=ToolSynthesisState.VALIDATING,
                error_type="SPEC_VALIDATION_ERROR",
                message="Tool specification violates security profile.",
                details="\n".join(errors),
                repairable=False # Can't easily repair spec requirements, reject it.
            )
        return True

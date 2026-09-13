import ast
import os
from pydantic import BaseModel
from typing import List
from sage.tools.base import BaseTool, ToolResult

class ReviewFinding(BaseModel):
    line: int
    severity: str
    issue_type: str
    message: str

class ReviewResult(BaseModel):
    findings: List[ReviewFinding]

class CodeReviewVisitor(ast.NodeVisitor):
    def __init__(self):
        self.findings = []
        self.imported_names = set()
        self.used_names = set()
    
    def visit_Import(self, node):
        for alias in node.names:
            self.imported_names.add((alias.asname or alias.name, node.lineno))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            self.imported_names.add((alias.asname or alias.name, node.lineno))
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.And, ast.Or, ast.ExceptHandler)):
                complexity += 1
        if complexity > 10:
            self.findings.append(ReviewFinding(
                line=node.lineno,
                severity="WARNING",
                issue_type="Complexity",
                message=f"Function '{node.name}' is overly complex (approx cyclomatic complexity: {complexity})"
            ))
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id in ['eval', 'exec']:
                self.findings.append(ReviewFinding(
                    line=node.lineno,
                    severity="ERROR",
                    issue_type="Dangerous Operation",
                    message=f"Usage of dangerous built-in '{node.func.id}'"
                ))
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr == 'system' and isinstance(node.func.value, ast.Name) and node.func.value.id == 'os':
                self.findings.append(ReviewFinding(
                    line=node.lineno,
                    severity="ERROR",
                    issue_type="Dangerous Operation",
                    message="Usage of 'os.system' is dangerous and prone to shell injection. Use 'subprocess' instead."
                ))
            elif node.func.attr == 'Popen' and isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess':
                for kw in node.keywords:
                    if kw.arg == 'shell' and getattr(kw.value, 'value', False) is True:
                        self.findings.append(ReviewFinding(
                            line=node.lineno,
                            severity="ERROR",
                            issue_type="Dangerous Operation",
                            message="Usage of 'subprocess.Popen(shell=True)' is dangerous and prone to shell injection."
                        ))
        self.generic_visit(node)

    def visit_For(self, node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.For, ast.While)):
                self.findings.append(ReviewFinding(
                    line=child.lineno,
                    severity="WARNING",
                    issue_type="Performance",
                    message="Nested loop detected. This may cause performance issues."
                ))
        self.generic_visit(node)

    def visit_Try(self, node):
        if not node.handlers and not node.finalbody:
            self.findings.append(ReviewFinding(
                line=node.lineno,
                severity="WARNING",
                issue_type="Error Handling",
                message="Try block has no except or finally clauses."
            ))
        else:
            for handler in node.handlers:
                if handler.type is None:
                    self.findings.append(ReviewFinding(
                        line=handler.lineno,
                        severity="WARNING",
                        issue_type="Error Handling",
                        message="Bare except clause caught. Specify exception type."
                    ))
                elif isinstance(handler.type, ast.Name) and handler.type.id == 'Exception':
                    self.findings.append(ReviewFinding(
                        line=handler.lineno,
                        severity="INFO",
                        issue_type="Error Handling",
                        message="Catching base Exception can mask errors. Consider being more specific."
                    ))
        self.generic_visit(node)


class PythonCodeReviewTool(BaseTool):
    name = "python_code_review"
    description = "Analyzes a Python source file for syntax errors, unused imports, overly complex functions, missing error handling, dangerous operations, and obvious performance issues. Returns structured findings with severity levels."
    parameters = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Absolute path to the Python file to analyze"
        }
    },
    "required": ["path"]
    }
    async def execute(self, path: str) -> ToolResult:
        if not os.path.exists(path):
            return ToolResult(success=False, output=f"File not found: {path}")
            
        try:
            with open(path, 'r', encoding='utf-8') as f:
                source = f.read()
        except Exception as e:
            return ToolResult(success=False, output=f"Error reading file: {e}")
            
        findings = []
        
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as e:
            findings.append(ReviewFinding(
                line=e.lineno or 1,
                severity="ERROR",
                issue_type="Syntax Error",
                message=str(e)
            ))
            return ToolResult(success=True, output=ReviewResult(findings=findings).model_dump_json(indent=2))
            
        visitor = CodeReviewVisitor()
        visitor.visit(tree)
        
        for imp, lineno in visitor.imported_names:
            if imp not in visitor.used_names:
                visitor.findings.append(ReviewFinding(
                    line=lineno,
                    severity="INFO",
                    issue_type="Unused Import",
                    message=f"Imported name '{imp}' is not used in the file."
                ))
                
        visitor.findings.sort(key=lambda x: x.line)
        
        output = ReviewResult(findings=visitor.findings).model_dump_json(indent=2)
        return ToolResult(success=True, output=output)

"""
SAGE Calculator Tool — safe mathematical expression evaluator.

Uses a restricted AST-based evaluator instead of eval() for safety.
Supports arithmetic, trig, log, and common math functions.
"""

import ast
import math
import operator
from typing import Any, Dict

from sage.tools.base import BaseTool, ToolPermission, ToolResult


# Allowed operators for safe evaluation
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Allowed math functions
SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "int": int,
    "float": float,
    # Trigonometry
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "radians": math.radians,
    "degrees": math.degrees,
    # Logarithmic
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    # Power & roots
    "sqrt": math.sqrt,
    "pow": math.pow,
    "ceil": math.ceil,
    "floor": math.floor,
    # Constants
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
}


class SafeEvaluator(ast.NodeVisitor):
    """AST-based safe expression evaluator. No arbitrary code execution."""

    def visit(self, node: ast.AST) -> Any:
        return super().visit(node)

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        return SAFE_OPERATORS[op_type](left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        return SAFE_OPERATORS[op_type](operand)

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        func_name = node.func.id
        if func_name not in SAFE_FUNCTIONS:
            raise ValueError(
                f"Unknown function: {func_name}. "
                f"Available: {', '.join(sorted(SAFE_FUNCTIONS.keys()))}"
            )
        func = SAFE_FUNCTIONS[func_name]
        if callable(func):
            args = [self.visit(arg) for arg in node.args]
            return func(*args)
        return func  # For constants like pi, e

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in SAFE_FUNCTIONS:
            val = SAFE_FUNCTIONS[node.id]
            if not callable(val):
                return val  # Constants
            raise ValueError(f"'{node.id}' is a function, use it with parentheses: {node.id}()")
        raise ValueError(
            f"Unknown name: '{node.id}'. "
            f"Available constants: pi, e, tau, inf"
        )

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        return tuple(self.visit(el) for el in node.elts)

    def visit_List(self, node: ast.List) -> Any:
        return [self.visit(el) for el in node.elts]

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def safe_eval(expression: str) -> Any:
    """Safely evaluate a mathematical expression."""
    tree = ast.parse(expression, mode="eval")
    evaluator = SafeEvaluator()
    return evaluator.visit(tree)


class CalculatorTool(BaseTool):
    """Safely evaluate mathematical expressions."""

    name = "calculator"
    description = (
        "CRITICAL: The expression must contain ONLY numeric values, mathematical "
"operators, parentheses, and supported mathematical functions/constants. "
"NEVER pass semantic labels, variable names, field names, units, natural-"
"language text, or placeholders such as 'Latest', 'Commissioning', "
"'temperature', 'vibration', 'current', 'flow', etc. "
"Before calling this tool, extract the actual numeric values from the "
"available data and substitute them directly into the expression. "
"If a required numeric value is missing, do NOT call the calculator; "
"report that the calculation cannot be performed. "
"Example: use '((6.0 - 2.5) / 2.5) * 100' instead of "
"'((Latest - Commissioning) / Commissioning) * 100'. "
"Only performs numerical calculations; do not provide or execute "
"arbitrary Python code, variables, strings, or non-mathematical operations."
    )
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Mathematical expression to evaluate (e.g. 'sqrt(2) * pi', '(3 + 4) ** 2')",
            },
        },
        "required": ["expression"],
    }

    async def execute(self, expression: str) -> ToolResult:
        try:
            result = safe_eval(expression)
            output = f"Expression: {expression}\nResult: {result}"
            return ToolResult(
                success=True,
                output=output,
                data={"expression": expression, "result": result},
            )
        except (ValueError, SyntaxError, TypeError, ZeroDivisionError) as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Calculation error: {str(e)}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error: {str(e)}",
            )

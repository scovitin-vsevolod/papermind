"""Tool definitions for Claude's tool_use API.

Three tools are available in PaperMind:

- ``web_search``  — Anthropic's server-side tool (`web_search_20260209`).
  Claude calls it on Anthropic's infra; we just enable it in the request.
- ``web_fetch``   — Anthropic's server-side tool (`web_fetch_20260209`).
  Same shape as web_search; Claude fetches a URL and uses the content.
- ``calculator``  — A *custom* (client-side) tool we run ourselves. Claude
  emits a ``tool_use`` block, we evaluate the expression safely, and feed
  the numeric result back in the next turn. This is the educational
  counterpart that exercises the multi-turn tool loop.

Why split server-side vs client-side
------------------------------------
Server tools are "free" — Anthropic handles them inside one ``messages.create``
call, no Python loop needed. Custom tools require us to:
1. Inspect ``response.content`` for ``tool_use`` blocks,
2. Execute the tool,
3. Send the result back as a ``tool_result`` block in a follow-up call.

Implementing one of each (web_search server-side, calculator client-side)
covers both patterns in the same RAG endpoint.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

# ── Server-side tool definitions ─────────────────────────────────────────────
# These are added to the ``tools`` list on messages.create and need no
# Python implementation — Anthropic runs them.

SERVER_SIDE_TOOLS: list[dict[str, Any]] = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
]


# ── Custom tool: calculator ──────────────────────────────────────────────────
# Schema matches Anthropic's custom-tool definition format.

CALCULATOR_TOOL: dict[str, Any] = {
    "name": "calculator",
    "description": (
        "Evaluate a numeric expression. Supports +, -, *, /, %, **, "
        "parentheses, and unary minus. Input must be a single math "
        "expression with no variable names or function calls."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "A math expression, e.g. '12 * (3 + 4) / 2'",
            }
        },
        "required": ["expression"],
    },
}


# Whitelisted AST node types for the safe evaluator. Anything else raises.
_ALLOWED_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}
_ALLOWED_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculatorError(ValueError):
    """Raised when the calculator can't safely evaluate an expression."""


def evaluate_expression(expression: str) -> float:
    """Safely evaluate a numeric expression.

    Uses the ``ast`` module to walk the parse tree and only execute
    whitelisted operators. Refuses anything that smells like code
    execution (names, calls, attribute access, comprehensions, etc.).
    Much safer than ``eval()``.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"invalid syntax: {exc}") from exc
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise CalculatorError(f"only numeric constants allowed; got {type(node.value).__name__}")
    if isinstance(node, ast.BinOp):
        op = _ALLOWED_BIN_OPS.get(type(node.op))
        if op is None:
            raise CalculatorError(f"operator not allowed: {type(node.op).__name__}")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_UNARY_OPS.get(type(node.op))
        if op is None:
            raise CalculatorError(f"unary operator not allowed: {type(node.op).__name__}")
        return op(_eval_node(node.operand))
    raise CalculatorError(f"node not allowed: {type(node).__name__}")


def execute_custom_tool(name: str, tool_input: dict[str, Any]) -> str:
    """Run a client-side custom tool and return its result as a string.

    Anthropic's ``tool_result`` blocks accept arbitrary text; we render
    numeric output as text so the model can use it directly.
    """
    if name == "calculator":
        try:
            value = evaluate_expression(tool_input["expression"])
        except CalculatorError as exc:
            return f"ERROR: {exc}"
        # Format clean integers without the trailing ".0"
        if value.is_integer():
            return str(int(value))
        return str(value)
    raise ValueError(f"unknown custom tool: {name!r}")


# ── Convenience: full tool list ──────────────────────────────────────────────

ALL_TOOLS: list[dict[str, Any]] = [*SERVER_SIDE_TOOLS, CALCULATOR_TOOL]

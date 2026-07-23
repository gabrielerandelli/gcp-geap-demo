"""FastMCP server exposing add / sub / multiply / divide for the GEAP math-agent demo."""

from __future__ import annotations

import os

from fastmcp import FastMCP

mcp = FastMCP("math-mcp")


@mcp.tool(annotations={"title": "Add", "readOnlyHint": True, "idempotentHint": True})
def add(a: float, b: float) -> float:
    """Return the sum a + b."""
    return a + b


@mcp.tool(annotations={"title": "Subtract", "readOnlyHint": True, "idempotentHint": True})
def sub(a: float, b: float) -> float:
    """Return the difference a - b."""
    return a - b


@mcp.tool(annotations={"title": "Multiply", "readOnlyHint": True, "idempotentHint": True})
def multiply(a: float, b: float) -> float:
    """Return the product a * b."""
    return a * b


@mcp.tool(annotations={"title": "Divide", "readOnlyHint": True, "idempotentHint": True})
def divide(a: float, b: float) -> float:
    """Return the quotient a / b. Raises ValueError when b == 0."""
    if b == 0:
        raise ValueError("Cannot divide by zero.")
    return a / b


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        path="/mcp",
    )

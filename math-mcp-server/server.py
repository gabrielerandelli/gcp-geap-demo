"""FastMCP server exposing add / sub / multiply / divide for the GEAP math-agent demo.

Emits OpenTelemetry spans following the GEAP MCP tracing schema documented at
https://docs.cloud.google.com/mcp/monitor-mcp-tool-use-with-cloud-trace so the
Agent Registry Observability tab (request count, p95 latency, per-tool traces)
lights up for this server.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp import types as mt
from opentelemetry import propagate, trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.starlette import StarletteInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from json_logger import log_intent_outcome, setup_structured_logging
from pii_scrubber import PiiScrubber

setup_structured_logging()
logger = logging.getLogger(__name__)

# --- OpenTelemetry setup ---------------------------------------------------

MCP_PROTOCOL_VERSION = "2024-11-05"
JSONRPC_PROTOCOL_VERSION = "2.0"
SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "math-mcp")


def _configure_tracing() -> None:
    """Register a global TracerProvider with a Cloud Trace exporter and the
    W3C traceparent propagator. Safe to call when GOOGLE_CLOUD_PROJECT is
    unset — falls back to a no-op provider so local runs still work.
    """
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        logger.info(
            "GOOGLE_CLOUD_PROJECT not set; skipping Cloud Trace exporter setup."
        )
        return

    # Resource attributes required for the GEAP MCP observability schema.
    resource_attrs: dict[str, Any] = {
        "service.name": SERVICE_NAME,
        "cloud.provider": "gcp",
        "cloud.account.id": project_id,
        "gcp.project_id": project_id,
    }
    # `gcp.mcp.server.id` = URN of the MCP server per the GEAP MCP-tracing
    # docs. In Agent Registry that value is the `mcpServerId` field returned
    # by `gcloud alpha agent-registry mcp-servers describe …` (format
    # `urn:mcp:projects-{num}:projects:{num}:locations:{loc}:agentregistry:services:{id}`),
    # NOT the `name` field.
    mcp_server_urn = os.environ.get("MCP_SERVER_URN")
    if mcp_server_urn:
        resource_attrs["gcp.mcp.server.id"] = mcp_server_urn

    provider = TracerProvider(resource=Resource.create(resource_attrs))
    provider.add_span_processor(
        BatchSpanProcessor(CloudTraceSpanExporter(project_id=project_id))
    )
    trace.set_tracer_provider(provider)

    # GEAP tracing docs: only W3C traceparent headers are honoured.
    propagate.set_global_textmap(TraceContextTextMapPropagator())


_configure_tracing()

_tracer = trace.get_tracer("math-mcp")


# --- FastMCP middleware ----------------------------------------------------

class GeapMcpTracingMiddleware(Middleware):
    """Emits one span per tools/call with the GEAP-required attributes and structured logging."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        tool_name = context.message.name
        raw_arguments = getattr(context.message, "arguments", {}) or {}
        scrubbed_args = PiiScrubber.scrub_data(raw_arguments)

        intent = {
            "mcp_method": "tools/call",
            "tool_name": tool_name,
            "arguments": scrubbed_args,
        }

        with _tracer.start_as_current_span(
            f"tools/call {tool_name}",
            kind=SpanKind.SERVER,
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": tool_name,
                "mcp.method.name": "tools/call",
                "mcp.protocol.version": MCP_PROTOCOL_VERSION,
                "jsonrpc.protocol.version": JSONRPC_PROTOCOL_VERSION,
            },
        ) as span:
            if context.fastmcp_context is not None:
                try:
                    span.set_attribute(
                        "jsonrpc.request.id", context.fastmcp_context.request_id
                    )
                except Exception:
                    pass
            try:
                res = await call_next(context)
                outcome = {
                    "status": "success",
                    "result_type": type(res).__name__,
                }
                log_intent_outcome(
                    logger=logger,
                    level=logging.INFO,
                    message=f"MCP tool '{tool_name}' call executed successfully",
                    intent=intent,
                    outcome=outcome,
                    event_type="mcp_tool_execution",
                )
                return res
            except Exception as exc:
                outcome = {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
                log_intent_outcome(
                    logger=logger,
                    level=logging.ERROR,
                    message=f"MCP tool '{tool_name}' call execution failed",
                    intent=intent,
                    outcome=outcome,
                    event_type="mcp_tool_execution",
                )
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                raise


# --- Pydantic Tool Schemas --------------------------------------------------

from pydantic import BaseModel, Field


class MathOpInput(BaseModel):
    """Input model for binary arithmetic operations."""

    a: float = Field(..., description="The first operand number (addend, minuend, or multiplicand).")
    b: float = Field(..., description="The second operand number (addend, subtrahend, or multiplier).")


class DivideInput(BaseModel):
    """Input model for division operation."""

    a: float = Field(..., description="The dividend number to be divided.")
    b: float = Field(..., description="The divisor number to divide by.")


class MathOpOutput(BaseModel):
    """Output model for binary arithmetic operations."""

    status: str = Field(..., description="Execution status: 'success' or 'error'.")
    result: float | None = Field(None, description="The numerical result of the calculation.")
    error: str | None = Field(None, description="Error message if the operation failed.")
    recovery_instruction: str | None = Field(
        None, description="Guided recovery advice for the LLM if an error occurred."
    )


class DivideOutput(BaseModel):
    """Output model for division operation."""

    status: str = Field(..., description="Execution status: 'success' or 'error'.")
    result: float | None = Field(None, description="The quotient result of the division.")
    error: str | None = Field(None, description="Error message if division failed (e.g. division by zero).")
    recovery_instruction: str | None = Field(
        None, description="Guided recovery advice for the LLM if an error occurred."
    )


# --- FastMCP server + tools ------------------------------------------------

mcp = FastMCP("math-mcp")
mcp.add_middleware(GeapMcpTracingMiddleware())


@mcp.tool(annotations={"title": "Add", "readOnlyHint": True, "idempotentHint": True})
def add(a: float, b: float) -> MathOpOutput:
    """Calculate the sum of two numbers a and b.

    Args:
        a (float): The first number (addend) to add.
        b (float): The second number (addend) to add.

    Returns:
        MathOpOutput: Pydantic model containing calculation status, numerical result, error details, and recovery instructions.
    """
    intent = {"tool": "add", "a": a, "b": b}
    try:
        res = MathOpOutput(status="success", result=a + b)
        log_intent_outcome(
            logger=logger,
            level=logging.INFO,
            message="Math operation 'add' succeeded",
            intent=intent,
            outcome=res.model_dump(),
        )
        return res
    except Exception as exc:
        res = MathOpOutput(
            status="error",
            result=None,
            error=f"Arithmetic error during addition: {exc}",
            recovery_instruction=(
                "Inform the student that an arithmetic error occurred, and ask them to verify their input numbers."
            ),
        )
        log_intent_outcome(
            logger=logger,
            level=logging.WARNING,
            message="Math operation 'add' failed",
            intent=intent,
            outcome=res.model_dump(),
        )
        return res


@mcp.tool(annotations={"title": "Subtract", "readOnlyHint": True, "idempotentHint": True})
def sub(a: float, b: float) -> MathOpOutput:
    """Calculate the difference a - b.

    Args:
        a (float): The minuend number to subtract from.
        b (float): The subtrahend number to subtract.

    Returns:
        MathOpOutput: Pydantic model containing calculation status, numerical result, error details, and recovery instructions.
    """
    intent = {"tool": "sub", "a": a, "b": b}
    try:
        res = MathOpOutput(status="success", result=a - b)
        log_intent_outcome(
            logger=logger,
            level=logging.INFO,
            message="Math operation 'sub' succeeded",
            intent=intent,
            outcome=res.model_dump(),
        )
        return res
    except Exception as exc:
        res = MathOpOutput(
            status="error",
            result=None,
            error=f"Arithmetic error during subtraction: {exc}",
            recovery_instruction=(
                "Inform the student that an arithmetic error occurred, and ask them to verify their input numbers."
            ),
        )
        log_intent_outcome(
            logger=logger,
            level=logging.WARNING,
            message="Math operation 'sub' failed",
            intent=intent,
            outcome=res.model_dump(),
        )
        return res


@mcp.tool(annotations={"title": "Multiply", "readOnlyHint": True, "idempotentHint": True})
def multiply(a: float, b: float) -> MathOpOutput:
    """Calculate the product of a multiplied by b.

    Args:
        a (float): The first multiplier number.
        b (float): The second multiplier number.

    Returns:
        MathOpOutput: Pydantic model containing calculation status, numerical result, error details, and recovery instructions.
    """
    intent = {"tool": "multiply", "a": a, "b": b}
    try:
        res = MathOpOutput(status="success", result=a * b)
        log_intent_outcome(
            logger=logger,
            level=logging.INFO,
            message="Math operation 'multiply' succeeded",
            intent=intent,
            outcome=res.model_dump(),
        )
        return res
    except Exception as exc:
        res = MathOpOutput(
            status="error",
            result=None,
            error=f"Arithmetic error during multiplication: {exc}",
            recovery_instruction=(
                "Inform the student that an arithmetic error occurred, and ask them to try with smaller numbers."
            ),
        )
        log_intent_outcome(
            logger=logger,
            level=logging.WARNING,
            message="Math operation 'multiply' failed",
            intent=intent,
            outcome=res.model_dump(),
        )
        return res


@mcp.tool(annotations={"title": "Divide", "readOnlyHint": True, "idempotentHint": True})
def divide(a: float, b: float) -> DivideOutput:
    """Calculate the quotient of a divided by b. Handles division by zero gracefully.

    Args:
        a (float): The dividend number to divide.
        b (float): The divisor number to divide by.

    Returns:
        DivideOutput: Pydantic model containing either the calculation result or a
            guided recovery instruction if b is zero or an error occurs.
    """
    intent = {"tool": "divide", "a": a, "b": b}
    if b == 0:
        res = DivideOutput(
            status="error",
            result=None,
            error="Division by zero is mathematically undefined.",
            recovery_instruction=(
                "Gently explain to the primary school student that dividing by zero "
                "is impossible in mathematics (you cannot share items among zero people), "
                "and encourage them to try with a number greater than zero."
            ),
        )
        log_intent_outcome(
            logger=logger,
            level=logging.WARNING,
            message="Math operation 'divide' division by zero",
            intent=intent,
            outcome=res.model_dump(),
        )
        return res
    try:
        res = DivideOutput(status="success", result=a / b)
        log_intent_outcome(
            logger=logger,
            level=logging.INFO,
            message="Math operation 'divide' succeeded",
            intent=intent,
            outcome=res.model_dump(),
        )
        return res
    except Exception as exc:
        res = DivideOutput(
            status="error",
            result=None,
            error=f"Arithmetic error during division: {exc}",
            recovery_instruction=(
                "Inform the student that an arithmetic error occurred, and ask if they would like to re-enter the numbers."
            ),
        )
        log_intent_outcome(
            logger=logger,
            level=logging.WARNING,
            message="Math operation 'divide' failed",
            intent=intent,
            outcome=res.model_dump(),
        )
        return res



if __name__ == "__main__":
    # Wrap the ASGI app with the Starlette OTel instrumentor so incoming
    # HTTP `traceparent` headers become the parent context of our spans.
    http_app = mcp.http_app(path="/mcp", transport="http")
    StarletteInstrumentor.instrument_app(http_app)

    import uvicorn

    uvicorn.run(
        http_app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )

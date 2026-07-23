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
    """Emits one span per tools/call with the GEAP-required attributes."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        tool_name = context.message.name
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
            try:
                return await call_next(context)
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                raise


# --- FastMCP server + tools ------------------------------------------------

mcp = FastMCP("math-mcp")
mcp.add_middleware(GeapMcpTracingMiddleware())


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

# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from urllib.parse import urlparse

from dotenv import load_dotenv

# .env must load before we read env vars — app/__init__.py imports this module,
# which runs before fast_api_app.py's own load_dotenv(). No-op in production
# where the runtime sets env vars directly.
load_dotenv()

import logging

import httpx

import google.auth
import google.auth.transport.requests
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.auth.auth_tool import AuthConfig
from google.adk.auth.credential_manager import CredentialManager
from google.adk.integrations.agent_identity import (
    GcpAuthProvider,
    GcpAuthProviderScheme,
)
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.models import Gemini
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.authenticated_function_tool import AuthenticatedFunctionTool
from google.adk.tools.load_memory_tool import LoadMemoryTool
from google.auth import impersonated_credentials
from google.cloud import modelarmor_v1
from google.genai import types
from google.oauth2 import id_token

_logger = logging.getLogger(__name__)

_PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
_REGISTRY_LOCATION = os.environ.get("AGENT_REGISTRY_LOCATION", "us-central1")
_MCP_SERVER_NAME = os.environ["MATH_MCP_SERVER_NAME"]
_MA_TEMPLATE = os.environ["MODEL_ARMOR_TEMPLATE"]
# Local-dev only: user ADC can't mint audience-scoped ID tokens. Set this to an SA
# that has run.invoker on the MCP service and grants token-creator to the current
# user. Ignored on Agent Runtime / Cloud Run / GCE where the metadata server can
# mint audience-scoped ID tokens natively for the attached SA (checked via the
# GCE metadata env var Agent Runtime sets on every container).
_IMPERSONATE_SA = os.environ.get("MATH_MCP_IMPERSONATE_SA")
if _IMPERSONATE_SA and os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID"):
    _IMPERSONATE_SA = None


def _extract_mcp_endpoint(mcp_details: dict) -> str:
    """Pull the JSONRPC/HTTP_JSON URI out of an Agent Registry MCP server response.

    The response has an `interfaces` list; each interface has `protocolBinding`
    and `uri`. Older shapes may use `endpoints` — try both.
    """
    for key in ("interfaces", "endpoints"):
        for item in mcp_details.get(key, []) or []:
            if item.get("protocolBinding") in ("JSONRPC", "HTTP_JSON"):
                uri = item.get("uri") or item.get("url")
                if uri:
                    return uri
    raise RuntimeError(
        f"No JSONRPC/HTTP_JSON URI in MCP server details for {_MCP_SERVER_NAME}: "
        f"{mcp_details!r}"
    )


# 1. Discover MCP endpoint via Agent Registry, then mint ID tokens audience-scoped to it.
_registry_bootstrap = AgentRegistry(
    project_id=_PROJECT, location=_REGISTRY_LOCATION
)
_mcp_details = _registry_bootstrap.get_mcp_server(_MCP_SERVER_NAME)
_endpoint = _extract_mcp_endpoint(_mcp_details)
_p = urlparse(_endpoint)
_MCP_AUDIENCE = f"{_p.scheme}://{_p.netloc}"


if _IMPERSONATE_SA:
    _source_creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    _id_token_creds = impersonated_credentials.IDTokenCredentials(
        target_credentials=impersonated_credentials.Credentials(
            source_credentials=_source_creds,
            target_principal=_IMPERSONATE_SA,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        ),
        target_audience=_MCP_AUDIENCE,
        include_email=True,
    )

    def _mint_id_token() -> str:
        _id_token_creds.refresh(google.auth.transport.requests.Request())
        return _id_token_creds.token
else:

    def _mint_id_token() -> str:
        return id_token.fetch_id_token(
            google.auth.transport.requests.Request(), _MCP_AUDIENCE
        )


def _header_provider(context):
    return {"Authorization": f"Bearer {_mint_id_token()}"}


# 2. Build the real registry with the header_provider wired in, then get the toolset.
registry = AgentRegistry(
    project_id=_PROJECT,
    location=_REGISTRY_LOCATION,
    header_provider=_header_provider,
)
math_toolset = registry.get_mcp_toolset(mcp_server_name=_MCP_SERVER_NAME)


# 2b. Agent Identity — register the GCP provider so ADK's CredentialManager can
# resolve GcpAuthProviderScheme references on AuthenticatedFunctionTool /
# McpToolset. The runtime SA needs `roles/agentidentity.user`.
CredentialManager.register_auth_provider(GcpAuthProvider())

_CURRENCY_AUTH_PROVIDER = (
    f"projects/{_PROJECT}/locations/{_REGISTRY_LOCATION}"
    "/authProviders/currency-freeapi"
)


async def _convert_currency(
    amount: float, base: str, target: str, credential=None
) -> dict:
    """Convert a monetary amount using freecurrencyapi.com. The `credential`
    kwarg is auto-injected by AuthenticatedFunctionTool from the Agent Identity
    AuthProvider named by `_CURRENCY_AUTH_PROVIDER`; its `.http.credentials.token`
    holds the API key.
    """
    if credential is None or credential.http is None:
        return {
            "error": "credential unavailable — Agent Identity token retrieval failed"
        }
    # ApiKey AuthProviders return the key via `additional_headers` (both under
    # the provider-defined header name AND under `X-GOOG-API-KEY`). Bearer
    # tokens land in `credentials.token`. Support both shapes.
    api_key = credential.http.credentials.token
    if not api_key and credential.http.additional_headers:
        api_key = next(iter(credential.http.additional_headers.values()), None)
    if not api_key:
        return {"error": "credential unavailable — no token/api-key returned"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "https://api.freecurrencyapi.com/v1/latest",
            params={
                "base_currency": base.upper(),
                "currencies": target.upper(),
            },
            headers={"apikey": api_key},
        )
        r.raise_for_status()
        rate = r.json()["data"][target.upper()]
    return {
        "converted": amount * rate,
        "rate": rate,
        "base": base.upper(),
        "target": target.upper(),
    }


currency_tool = AuthenticatedFunctionTool(
    func=_convert_currency,
    auth_config=AuthConfig(
        auth_scheme=GcpAuthProviderScheme(name=_CURRENCY_AUTH_PROVIDER),
    ),
)

# 3. Model Armor callbacks.
# REST transport avoids gRPC-through-HTTP-proxy failures in restricted networks.
# Regional endpoint required — the default `us` multi-region has different IAM.
_MA_LOCATION = _MA_TEMPLATE.split("/")[3]  # projects/P/locations/L/templates/T
_MA_CLIENT = modelarmor_v1.ModelArmorClient(
    transport="rest",
    client_options={"api_endpoint": f"modelarmor.{_MA_LOCATION}.rep.googleapis.com"},
)


def _extract_last_user_text(llm_request):
    for content in reversed(llm_request.contents or []):
        if content.role == "user":
            for part in content.parts or []:
                if getattr(part, "text", None):
                    return part.text
    return None


def _extract_response_text(llm_response):
    if not llm_response.content or not llm_response.content.parts:
        return None
    return "".join(
        p.text for p in llm_response.content.parts if getattr(p, "text", None)
    )


def _blocked_response(reason: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text=f"[blocked by Model Armor: {reason}]")],
        )
    )


def _model_armor_before(callback_context, llm_request):
    text = _extract_last_user_text(llm_request)
    if not text:
        return None
    resp = _MA_CLIENT.sanitize_user_prompt(
        request={
            "name": _MA_TEMPLATE,
            "user_prompt_data": {"text": text},
        }
    )
    if (
        resp.sanitization_result.filter_match_state
        == modelarmor_v1.FilterMatchState.MATCH_FOUND
    ):
        return _blocked_response("input")
    return None


def _model_armor_after(callback_context, llm_response):
    text = _extract_response_text(llm_response)
    if not text:
        return None
    resp = _MA_CLIENT.sanitize_model_response(
        request={
            "name": _MA_TEMPLATE,
            "model_response_data": {"text": text},
        }
    )
    if (
        resp.sanitization_result.filter_match_state
        == modelarmor_v1.FilterMatchState.MATCH_FOUND
    ):
        return _blocked_response("output")
    return None


# 4. Memory Bank: on-demand recall + generation at end of each turn.
# NOTE: We pass `wait_for_completion=True` so the underlying VertexAiMemoryBankService
# takes the synchronous `memories.generate` path (see its docstring). Without it,
# the default `ingest_events` path is buffered/asynchronous and does not generate
# facts on its own — memories never appear.
async def _add_events_to_memory(callback_context: CallbackContext) -> None:
    """Persist ALL events of the current session to Memory Bank synchronously.

    Calls the memory service directly so we can pass ``wait_for_completion=True``,
    which routes VertexAiMemoryBankService to ``memories.generate`` (extracts
    facts immediately) instead of the buffered ``ingest_events`` default. Any
    failure is logged and swallowed — memory persistence must never fail a user
    response.
    """
    try:
        invocation = callback_context._invocation_context
        memory_service = invocation.memory_service
        session = invocation.session
        if memory_service is None or not session.events:
            return
        await memory_service.add_events_to_memory(
            app_name=session.app_name,
            user_id=session.user_id,
            events=session.events,
            custom_metadata={"wait_for_completion": True},
        )
        _logger.warning(
            "Memory Bank generate OK for user=%s events=%d",
            session.user_id,
            len(session.events),
        )
    except Exception as exc:
        _logger.warning(
            "Memory Bank generate failed: %s", exc, exc_info=True
        )


# 5. Preserve Agent + App exports.
root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are a math assistant. For any arithmetic request, call the "
        "appropriate arithmetic tool available to you rather than computing "
        "yourself. You can also convert currency amounts by calling the "
        "`_convert_currency` tool with (amount, base currency code, target "
        "currency code) — combine it freely with arithmetic tools "
        "(e.g. 'convert 100 USD to EUR then divide by 3'). "
        "Refuse anything unrelated to arithmetic or currency conversion. "
        "When the user references earlier calculations or asks for a summary "
        "of past operations, call the `load_memory` tool with a concise "
        "natural-language query describing what they're asking about."
    ),
    tools=[math_toolset, LoadMemoryTool(), currency_tool],
    before_model_callback=_model_armor_before,
    after_model_callback=_model_armor_after,
    after_agent_callback=_add_events_to_memory,
)

app = App(
    root_agent=root_agent,
    name="app",
)

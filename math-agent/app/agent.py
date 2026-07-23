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

import google.auth
import google.auth.transport.requests
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.models import Gemini
from google.adk.models.llm_response import LlmResponse
from google.auth import impersonated_credentials
from google.cloud import modelarmor_v1
from google.genai import types
from google.oauth2 import id_token

_PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
_REGISTRY_LOCATION = os.environ.get("AGENT_REGISTRY_LOCATION", "us-central1")
_MCP_SERVER_NAME = os.environ["MATH_MCP_SERVER_NAME"]
_MA_TEMPLATE = os.environ["MODEL_ARMOR_TEMPLATE"]
# Local-dev only: user ADC can't mint audience-scoped ID tokens. Set this to an SA
# that has run.invoker on the MCP service and grants token-creator to the current
# user. On Agent Runtime this is unset — the metadata server mints tokens natively.
_IMPERSONATE_SA = os.environ.get("MATH_MCP_IMPERSONATE_SA")


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


# 4. Preserve Agent + App exports.
root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are a math assistant. For any arithmetic request, call the "
        "appropriate arithmetic tool available to you rather than computing "
        "yourself. Refuse anything unrelated to arithmetic."
    ),
    tools=[math_toolset],
    before_model_callback=_model_armor_before,
    after_model_callback=_model_armor_after,
)

app = App(
    root_agent=root_agent,
    name="app",
)

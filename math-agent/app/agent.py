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


# 5. Gamification Tool: Funny Cartoon Reward Badge Generator.
def generate_funny_reward_image(
    title: str, joke_punchline: str, theme: str = "star"
) -> dict:
    """Generate a vibrant, funny cartoon reward badge card for a primary school student.

    Args:
        title: Celebratory badge title (e.g. 'Math Superstar!', 'Owl-some Job!',
          'Math Wizard!').
        joke_punchline: A funny kid-friendly math joke or riddle punchline.
        theme: Theme of the badge ('star', 'trophy', 'owl', 'puppy', 'rocket').

    Returns:
        dict with badge details and an embedded SVG cartoon reward badge.
    """
    badge_icons = {
        "star": "⭐",
        "trophy": "🏆",
        "owl": "🦉",
        "puppy": "🐶",
        "rocket": "🚀",
    }
    icon = badge_icons.get(theme.lower(), "⭐")

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 300" width="100%" height="auto">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FF6B6B" />
      <stop offset="50%" stop-color="#4ECDC4" />
      <stop offset="100%" stop-color="#FFE66D" />
    </linearGradient>
    <filter id="shadow">
      <feDropShadow dx="2" dy="4" stdDeviation="4" flood-opacity="0.3"/>
    </filter>
  </defs>
  <rect width="480" height="280" x="10" y="10" rx="20" ry="20" fill="url(#bgGrad)" stroke="#FFFFFF" stroke-width="4" filter="url(#shadow)" />
  <rect width="450" height="250" x="25" y="25" rx="15" ry="15" fill="#FFFFFF" fill-opacity="0.9" />
  
  <text x="250" y="70" font-family="'Comic Sans MS', 'Chalkboard SE', cursive, sans-serif" font-size="28" font-weight="bold" fill="#2B2D42" text-anchor="middle">
    {icon} {title} {icon}
  </text>
  
  <circle cx="250" cy="130" r="35" fill="#FFE66D" stroke="#FF6B6B" stroke-width="3" />
  <text x="250" y="142" font-size="40" text-anchor="middle">{icon}</text>
  
  <rect width="400" height="65" x="50" y="185" rx="10" ry="10" fill="#F7FFF7" stroke="#4ECDC4" stroke-width="2" />
  <text x="250" y="212" font-family="sans-serif" font-size="14" font-weight="bold" fill="#1A535C" text-anchor="middle">
    🎉 FUN MATH JOKE PUNCHLINE 🎉
  </text>
  <text x="250" y="235" font-family="sans-serif" font-size="15" font-style="italic" fill="#2B2D42" text-anchor="middle">
    "{joke_punchline}"
  </text>
</svg>"""

    return {
        "status": "success",
        "title": title,
        "joke_punchline": joke_punchline,
        "theme": theme,
        "badge_svg": svg_content,
        "badge_markdown": f"![{title}](data:image/svg+xml;utf8,{svg_content})",
    }


# 6. Define Multi-Agent System (MAS) Sub-Agents.

math_calculator_agent = Agent(
    name="math_calculator_agent",
    description=(
        "Specialist sub-agent for solving, verifying, and explaining primary school "
        "arithmetic operations (addition, subtraction, multiplication, division) "
        "and currency word problems step-by-step."
    ),
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are the Math Calculator Specialist for primary school students. "
        "For any arithmetic computation, ALWAYS call the appropriate MCP tool "
        "(add, sub, multiply, divide) rather than calculating yourself. "
        "For currency conversion word problems, call `_convert_currency`. "
        "When checking a student's answer, confirm if they are correct or "
        "explain step-by-step where the mistake is in a simple, friendly, "
        "encouraging tone suitable for elementary school kids."
    ),
    tools=[math_toolset, currency_tool],
)

reward_fun_agent = Agent(
    name="reward_fun_agent",
    description=(
        "Specialist sub-agent for rewarding primary school students when they get "
        "a math problem right. Tells hilarious kid-friendly math jokes and "
        "generates funny cartoon reward badges/images."
    ),
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are the Fun Reward Specialist! When a primary school student solves a "
        "math problem correctly, celebrate their success enthusiastically! "
        "Tell a funny, clean, age-appropriate math joke or riddle, and ALWAYS call "
        "`generate_funny_reward_image` to create a colorful cartoon reward badge."
    ),
    tools=[generate_funny_reward_image],
)

# 7. Root MAS Coordinator Agent ("Sparky the Math Mascot").
root_agent = Agent(
    name="root_agent",
    description="Primary School Math Tutor MAS Root Coordinator Agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are 'Sparky', an encouraging, enthusiastic, and friendly Primary School "
        "Math Tutor AI! You coordinate a team of specialized agents: "
        "`math_calculator_agent` (math solving & answer verification) and "
        "`reward_fun_agent` (funny jokes & cartoon reward badge images).\n\n"
        "Guidelines for tutoring primary school students:\n"
        "1. When the student asks a math question or submits an answer, delegate "
        "the calculation / answer verification to `math_calculator_agent`.\n"
        "2. If `math_calculator_agent` confirms the student got the answer RIGHT: "
        "delegate to `reward_fun_agent` to celebrate their achievement with a "
        "hilarious math joke and a funny cartoon reward badge image!\n"
        "3. If the answer is INCORRECT: gently encourage them, give a fun hint, "
        "and guide them step-by-step without giving away the final answer immediately.\n"
        "4. When the student asks about past operations or topics they mastered, "
        "call `load_memory` to recall their profile and progress history.\n"
        "5. Keep all language warm, patient, positive, and elementary school friendly."
    ),
    sub_agents=[math_calculator_agent, reward_fun_agent],
    tools=[LoadMemoryTool()],
    before_model_callback=_model_armor_before,
    after_model_callback=_model_armor_after,
    after_agent_callback=_add_events_to_memory,
)

app = App(
    root_agent=root_agent,
    name="app",
)


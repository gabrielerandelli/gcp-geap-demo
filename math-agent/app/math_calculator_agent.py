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

import logging
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv()

import httpx
import google.auth
import google.auth.transport.requests
from google.adk.agents import Agent
from google.adk.auth.auth_tool import AuthConfig
from google.adk.auth.credential_manager import CredentialManager
from google.adk.integrations.agent_identity import (
    GcpAuthProvider,
    GcpAuthProviderScheme,
)
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.models import Gemini
from google.adk.tools.authenticated_function_tool import AuthenticatedFunctionTool
from google.auth import impersonated_credentials
from google.genai import types
from google.oauth2 import id_token
from pydantic import BaseModel, Field

_logger = logging.getLogger(__name__)

_PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
_REGISTRY_LOCATION = os.environ.get("AGENT_REGISTRY_LOCATION", "us-central1")
_MCP_SERVER_NAME = os.environ["MATH_MCP_SERVER_NAME"]
_IMPERSONATE_SA = os.environ.get("MATH_MCP_IMPERSONATE_SA")
if _IMPERSONATE_SA and os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID"):
    _IMPERSONATE_SA = None


def _extract_mcp_endpoint(mcp_details: dict) -> str:
    """Pull the JSONRPC/HTTP_JSON URI out of an Agent Registry MCP server response."""
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


# Discover MCP endpoint via Agent Registry, then mint ID tokens audience-scoped to it.
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


registry = AgentRegistry(
    project_id=_PROJECT,
    location=_REGISTRY_LOCATION,
    header_provider=_header_provider,
)
math_toolset = registry.get_mcp_toolset(mcp_server_name=_MCP_SERVER_NAME)

CredentialManager.register_auth_provider(GcpAuthProvider())

_CURRENCY_AUTH_PROVIDER = (
    f"projects/{_PROJECT}/locations/{_REGISTRY_LOCATION}"
    "/authProviders/currency-freeapi"
)


class CurrencyConvertInput(BaseModel):
    """Input parameters for currency conversion."""

    amount: float = Field(..., description="Monetary amount to convert.")
    base: str = Field(..., description="Three-letter base currency code (e.g., 'USD', 'EUR').")
    target: str = Field(..., description="Three-letter target currency code (e.g., 'EUR', 'GBP').")


class CurrencyConvertOutput(BaseModel):
    """Output results for currency conversion."""

    status: str = Field(..., description="Execution status: 'success' or 'error'.")
    converted: float | None = Field(None, description="Converted monetary amount.")
    rate: float | None = Field(None, description="Exchange rate applied.")
    base: str | None = Field(None, description="Base currency code.")
    target: str | None = Field(None, description="Target currency code.")
    error: str | None = Field(None, description="Error message if conversion failed.")
    recovery_instruction: str | None = Field(
        None, description="Guided recovery advice for the LLM if an error occurred."
    )


async def _convert_currency(
    amount: float, base: str, target: str, credential=None
) -> CurrencyConvertOutput:
    """Convert a monetary amount from a base currency to a target currency.

    The `credential` kwarg is auto-injected by AuthenticatedFunctionTool from the Agent Identity
    AuthProvider named by `_CURRENCY_AUTH_PROVIDER`.

    Args:
        amount (float): The monetary value to convert.
        base (str): The 3-letter currency code to convert from (e.g., 'USD').
        target (str): The 3-letter currency code to convert to (e.g., 'EUR').
        credential (Any, optional): Auto-injected Agent Identity credential object. Defaults to None.

    Returns:
        CurrencyConvertOutput: Pydantic model containing converted amount, exchange rate, base, target, status, and guided recovery instruction if conversion fails.
    """
    if credential is None or credential.http is None:
        return CurrencyConvertOutput(
            status="error",
            error="Credential unavailable — Agent Identity token retrieval failed",
            recovery_instruction=(
                "Explain politely to the student that live currency exchange rate "
                "data is currently offline, but you can help with regular math!"
            ),
        )
    api_key = credential.http.credentials.token
    if not api_key and credential.http.additional_headers:
        api_key = next(iter(credential.http.additional_headers.values()), None)
    if not api_key:
        return CurrencyConvertOutput(
            status="error",
            error="Credential unavailable — no token/api-key returned",
            recovery_instruction=(
                "Explain politely to the student that live currency exchange rate "
                "data is currently offline, but you can help with regular math!"
            ),
        )
    try:
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
            data = r.json().get("data", {})
            if target.upper() not in data:
                return CurrencyConvertOutput(
                    status="error",
                    error=f"Invalid or unsupported currency code: {target}",
                    recovery_instruction=(
                        f"Inform the student that '{target}' is an unrecognized currency code, "
                        "and ask them to check the 3-letter currency symbol (like USD, EUR, or GBP)."
                    ),
                )
            rate = data[target.upper()]
        return CurrencyConvertOutput(
            status="success",
            converted=round(amount * rate, 2),
            rate=rate,
            base=base.upper(),
            target=target.upper(),
        )
    except Exception as exc:
        _logger.warning("Currency conversion network error: %s", exc)
        return CurrencyConvertOutput(
            status="error",
            error=f"Currency service error: {exc}",
            recovery_instruction=(
                "Advise the student that the exchange rate service had a temporary network glitch, "
                "and ask if they would like to try another calculation or a different problem."
            ),
        )


currency_tool = AuthenticatedFunctionTool(
    func=_convert_currency,
    auth_config=AuthConfig(
        auth_scheme=GcpAuthProviderScheme(name=_CURRENCY_AUTH_PROVIDER),
    ),
)


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

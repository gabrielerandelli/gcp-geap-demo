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

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.genai import types

MCP_URL = os.environ.get("MATH_MCP_URL", "http://localhost:8080/mcp")
_auth_header = os.environ.get("MATH_MCP_AUTH_HEADER")  # "Bearer <id_token>" when remote
_headers = {"Authorization": _auth_header} if _auth_header else None

math_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=MCP_URL, headers=_headers),
    tool_filter=["add", "sub", "multiply", "divide"],
)


def _model_armor_before(callback_context, llm_request):
    # STUB: real Model Armor sanitize_user_prompt wired in Part 2.
    return None


def _model_armor_after(callback_context, llm_response):
    # STUB: real Model Armor sanitize_model_response wired in Part 2.
    return None


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are a math assistant. For any arithmetic request, call the "
        "appropriate MCP tool (add, sub, multiply, divide) rather than "
        "computing yourself. Refuse anything unrelated to arithmetic."
    ),
    tools=[math_toolset],
    before_model_callback=_model_armor_before,
    after_model_callback=_model_armor_after,
)

app = App(
    root_agent=root_agent,
    name="app",
)

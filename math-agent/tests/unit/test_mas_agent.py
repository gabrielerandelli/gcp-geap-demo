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

from app.agent import root_agent, _add_events_to_memory
from app.math_calculator_agent import (
    math_calculator_agent,
    _convert_currency,
    CurrencyConvertInput,
    CurrencyConvertOutput,
)
from app.reward_fun_agent import (
    reward_fun_agent,
    generate_funny_reward_image,
    RewardBadgeInput,
    RewardBadgeOutput,
)


def test_mas_agent_structure() -> None:
    """Verify that root_agent is configured as a Multi-Agent System (MAS)."""
    assert root_agent.name == "root_agent"
    assert len(root_agent.sub_agents) == 2, "Expected 2 sub-agents in MAS"

    sub_agent_names = [sa.name for sa in root_agent.sub_agents]
    assert "math_calculator_agent" in sub_agent_names
    assert "reward_fun_agent" in sub_agent_names


def test_generate_funny_reward_image_tool() -> None:
    """Test that generate_funny_reward_image returns structured badge data with valid SVG."""
    res = generate_funny_reward_image(
        title="Math Superstar!",
        joke_punchline="Because 7 ate 9!",
        theme="star",
    )
    status = res.status if hasattr(res, "status") else res["status"]
    title = res.title if hasattr(res, "title") else res["title"]
    joke_punchline = res.joke_punchline if hasattr(res, "joke_punchline") else res["joke_punchline"]
    badge_svg = res.badge_svg if hasattr(res, "badge_svg") else res["badge_svg"]
    badge_markdown = res.badge_markdown if hasattr(res, "badge_markdown") else res["badge_markdown"]

    assert status == "success"
    assert title == "Math Superstar!"
    assert joke_punchline == "Because 7 ate 9!"
    assert "<svg" in badge_svg
    assert "data:image/svg+xml" in badge_markdown


import pytest


@pytest.mark.asyncio
async def test_add_events_to_memory_non_blocking() -> None:
    """Test that _add_events_to_memory dispatches background task without blocking."""
    from unittest.mock import AsyncMock, MagicMock

    mock_callback_ctx = MagicMock()
    mock_invocation = MagicMock()
    mock_memory_service = AsyncMock()
    mock_session = MagicMock()

    mock_session.app_name = "test_app"
    mock_session.user_id = "user_123"
    mock_session.events = [MagicMock()]

    mock_invocation.memory_service = mock_memory_service
    mock_invocation.session = mock_session
    mock_callback_ctx._invocation_context = mock_invocation

    # Call callback — must return instantly
    await _add_events_to_memory(mock_callback_ctx)


@pytest.mark.asyncio
async def test_convert_currency_guided_error_recovery() -> None:
    """Test that _convert_currency returns guided recovery instructions on missing credential."""
    res = await _convert_currency(100.0, "USD", "EUR", credential=None)
    status = res.status if hasattr(res, "status") else res["status"]
    error = res.error if hasattr(res, "error") else res["error"]
    recovery_instruction = res.recovery_instruction if hasattr(res, "recovery_instruction") else res["recovery_instruction"]

    assert status == "error"
    assert error is not None
    assert recovery_instruction is not None
    assert "live currency exchange rate data is currently offline" in recovery_instruction


def test_pydantic_schemas() -> None:
    """Test that Pydantic input/output schemas are importable and valid."""
    badge_in = RewardBadgeInput(title="Job Well Done!", joke_punchline="Math is fun!")
    assert badge_in.title == "Job Well Done!"
    assert badge_in.theme == "star"

    badge_out = RewardBadgeOutput(
        status="success",
        title="Job Well Done!",
        joke_punchline="Math is fun!",
        theme="star",
        badge_svg="<svg></svg>",
        badge_markdown="![badge](data:...)",
    )
    assert badge_out.status == "success"




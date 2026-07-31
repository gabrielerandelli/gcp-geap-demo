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

"""Unit tests for Strategic Model Routing and Human-In-The-Loop (HITL) Guardrails."""

import pytest

from app.agent import root_agent
from app.hitl_hooks import HitlGuard, VALID_APPROVAL_CODE
from app.math_calculator_agent import math_calculator_agent, _convert_currency
from app.reward_fun_agent import reward_fun_agent, generate_funny_reward_image


def test_strategic_model_routing_assignments():
    """Verify tiered Gemini model assignments across agent hierarchy."""
    assert root_agent.model.model == "gemini-2.5-pro"
    assert math_calculator_agent.model.model == "gemini-2.5-flash"
    assert reward_fun_agent.model.model == "gemini-2.5-flash-lite"


def test_hitl_currency_conversion_threshold():
    """Verify high-stakes currency conversions (> $1000 USD) require approval."""
    # Under $1,000 threshold -> No approval needed
    under_res = HitlGuard.check_currency_hitl(amount=500.0, base="USD", target="EUR")
    assert not under_res.requires_approval

    # Over $1,000 threshold without approval code -> Approval required
    over_res = HitlGuard.check_currency_hitl(amount=1500.0, base="USD", target="EUR")
    assert over_res.requires_approval
    assert "High-stakes financial calculation" in over_res.message
    assert "TEACHER_APPROVED" in over_res.recovery_instruction

    # Over $1,000 threshold with valid approval code -> Approval granted
    approved_res = HitlGuard.check_currency_hitl(
        amount=1500.0,
        base="USD",
        target="EUR",
        teacher_approval_code=VALID_APPROVAL_CODE,
    )
    assert not approved_res.requires_approval


@pytest.mark.asyncio
async def test_convert_currency_hitl_interception():
    """Verify _convert_currency tool intercepts high-stakes conversions without credential call."""
    res = await _convert_currency(
        amount=2500.0,
        base="USD",
        target="EUR",
    )
    assert res.status == "pending_human_approval"
    assert "High-stakes financial calculation" in res.error
    assert "TEACHER_APPROVED" in res.recovery_instruction


def test_hitl_reward_badge_approval():
    """Verify special trophy/grandmaster award badges require approval."""
    # Standard star badge -> No approval needed
    star_res = HitlGuard.check_reward_hitl(title="Math Superstar!", theme="star")
    assert not star_res.requires_approval

    # Grandmaster Trophy badge without approval code -> Approval required
    trophy_res = HitlGuard.check_reward_hitl(title="Grandmaster Champion", theme="trophy")
    assert trophy_res.requires_approval
    assert "TEACHER_APPROVED" in trophy_res.recovery_instruction

    # Grandmaster Trophy badge with valid approval code -> Granted
    approved_trophy = generate_funny_reward_image(
        title="Grandmaster Champion",
        joke_punchline="Math rulez!",
        theme="trophy",
        teacher_approval_code=VALID_APPROVAL_CODE,
    )
    assert approved_trophy.status == "success"
    assert approved_trophy.title == "Grandmaster Champion"

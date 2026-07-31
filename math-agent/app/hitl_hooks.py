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

"""Human-In-The-Loop (HITL) Guardrails module for high-stakes agent actions."""

from __future__ import annotations

import logging
from typing import Any

from app.json_logger import log_intent_outcome

_logger = logging.getLogger(__name__)

# Default financial threshold for high-stakes currency conversion
HIGH_STAKES_CURRENCY_THRESHOLD_USD = 1000.0
VALID_APPROVAL_CODE = "TEACHER_APPROVED"


class HitlGuardResult:
    """Structure representing the evaluation outcome of an HITL guardrail check."""

    def __init__(
        self,
        requires_approval: bool,
        message: str | None = None,
        recovery_instruction: str | None = None,
    ) -> None:
        self.requires_approval = requires_approval
        self.message = message
        self.recovery_instruction = recovery_instruction


class HitlGuard:
    """Guardrail evaluator for intercepting high-stakes tool invocations."""

    @classmethod
    def check_currency_hitl(
        cls,
        amount: float,
        base: str,
        target: str,
        teacher_approval_code: str | None = None,
    ) -> HitlGuardResult:
        """Evaluate whether a currency conversion exceeds high-stakes threshold.

        Args:
            amount (float): Monetary value.
            base (str): Base currency code.
            target (str): Target currency code.
            teacher_approval_code (str, optional): Approval token provided by human.

        Returns:
            HitlGuardResult: Approval evaluation result.
        """
        # Exceeds threshold check (simplified USD comparison or base amount)
        if amount >= HIGH_STAKES_CURRENCY_THRESHOLD_USD:
            if teacher_approval_code == VALID_APPROVAL_CODE:
                log_intent_outcome(
                    logger=_logger,
                    level=logging.INFO,
                    message="High-stakes currency conversion HITL approval granted",
                    intent={
                        "action": "high_stakes_currency_conversion",
                        "amount": amount,
                        "base": base,
                        "target": target,
                    },
                    outcome={"status": "approved", "approval_code": teacher_approval_code},
                    event_type="hitl_approval_granted",
                )
                return HitlGuardResult(requires_approval=False)

            log_intent_outcome(
                logger=_logger,
                level=logging.WARNING,
                message="High-stakes currency conversion HITL approval required",
                intent={
                    "action": "high_stakes_currency_conversion",
                    "amount": amount,
                    "base": base,
                    "target": target,
                },
                outcome={
                    "status": "pending_human_approval",
                    "threshold_usd": HIGH_STAKES_CURRENCY_THRESHOLD_USD,
                },
                event_type="hitl_approval_required",
            )
            return HitlGuardResult(
                requires_approval=True,
                message=(
                    f"High-stakes financial calculation ({amount:.2f} {base}) "
                    f"exceeds the ${HIGH_STAKES_CURRENCY_THRESHOLD_USD:.2f} USD threshold "
                    "and requires human/teacher approval before execution."
                ),
                recovery_instruction=(
                    "Ask the teacher or supervisor to confirm approval by providing "
                    "the confirmation parameter teacher_approval_code='TEACHER_APPROVED'."
                ),
            )

        return HitlGuardResult(requires_approval=False)

    @classmethod
    def check_reward_hitl(
        cls,
        title: str,
        theme: str,
        teacher_approval_code: str | None = None,
    ) -> HitlGuardResult:
        """Evaluate whether a high-stakes award/certificate badge requires HITL approval.

        Args:
            title (str): Badge title.
            theme (str): Badge theme.
            teacher_approval_code (str, optional): Approval token provided by human.

        Returns:
            HitlGuardResult: Approval evaluation result.
        """
        is_grandmaster_badge = (
            "grandmaster" in title.lower()
            or "certificate" in title.lower()
            or theme.lower() == "trophy"
        )

        if is_grandmaster_badge:
            if teacher_approval_code == VALID_APPROVAL_CODE:
                log_intent_outcome(
                    logger=_logger,
                    level=logging.INFO,
                    message="High-stakes reward badge HITL approval granted",
                    intent={"action": "high_stakes_badge_generation", "title": title, "theme": theme},
                    outcome={"status": "approved", "approval_code": teacher_approval_code},
                    event_type="hitl_approval_granted",
                )
                return HitlGuardResult(requires_approval=False)

            log_intent_outcome(
                logger=_logger,
                level=logging.WARNING,
                message="High-stakes reward badge HITL approval required",
                intent={"action": "high_stakes_badge_generation", "title": title, "theme": theme},
                outcome={"status": "pending_human_approval"},
                event_type="hitl_approval_required",
            )
            return HitlGuardResult(
                requires_approval=True,
                message=(
                    f"Issuing a high-stakes award badge ('{title}') requires explicit "
                    "teacher or supervisor authorization."
                ),
                recovery_instruction=(
                    "Ask the teacher to confirm this award by providing "
                    "teacher_approval_code='TEACHER_APPROVED'."
                ),
            )

        return HitlGuardResult(requires_approval=False)

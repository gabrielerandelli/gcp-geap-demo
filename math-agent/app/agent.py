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

import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.load_memory_tool import LoadMemoryTool
from google.cloud import modelarmor_v1
from google.genai import types

from app.json_logger import log_intent_outcome, setup_structured_logging
from app.pii_scrubber import PiiScrubber

# Import single sub-agents from their dedicated modules
from app.math_calculator_agent import math_calculator_agent
from app.reward_fun_agent import reward_fun_agent

setup_structured_logging()
_logger = logging.getLogger(__name__)

_PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
_MA_TEMPLATE = os.environ["MODEL_ARMOR_TEMPLATE"]


# Model Armor callbacks.
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

    # Scrub PII from text before checking Model Armor & logging intent
    scrubbed_text = PiiScrubber.scrub_text(text)
    intent = {
        "action": "model_armor_user_prompt_sanitization",
        "template": _MA_TEMPLATE,
        "raw_prompt_length": len(text),
        "prompt_snippet": scrubbed_text[:100],
    }

    resp = _MA_CLIENT.sanitize_user_prompt(
        request={
            "name": _MA_TEMPLATE,
            "user_prompt_data": {"text": scrubbed_text},
        }
    )

    is_blocked = (
        resp.sanitization_result.filter_match_state
        == modelarmor_v1.FilterMatchState.MATCH_FOUND
    )
    outcome = {
        "filter_match_state": str(resp.sanitization_result.filter_match_state),
        "is_blocked": is_blocked,
        "action_taken": "blocked" if is_blocked else "allowed",
    }

    log_intent_outcome(
        logger=_logger,
        level=logging.WARNING if is_blocked else logging.INFO,
        message="Model Armor prompt sanitization evaluated",
        intent=intent,
        outcome=outcome,
        event_type="model_armor_input_guardrail",
    )

    if is_blocked:
        return _blocked_response("input")
    return None


def _model_armor_after(callback_context, llm_response):
    text = _extract_response_text(llm_response)
    if not text:
        return None

    scrubbed_text = PiiScrubber.scrub_text(text)
    intent = {
        "action": "model_armor_response_sanitization",
        "template": _MA_TEMPLATE,
        "raw_response_length": len(text),
        "response_snippet": scrubbed_text[:100],
    }

    resp = _MA_CLIENT.sanitize_model_response(
        request={
            "name": _MA_TEMPLATE,
            "model_response_data": {"text": scrubbed_text},
        }
    )

    is_blocked = (
        resp.sanitization_result.filter_match_state
        == modelarmor_v1.FilterMatchState.MATCH_FOUND
    )
    outcome = {
        "filter_match_state": str(resp.sanitization_result.filter_match_state),
        "is_blocked": is_blocked,
        "action_taken": "blocked" if is_blocked else "allowed",
    }

    log_intent_outcome(
        logger=_logger,
        level=logging.WARNING if is_blocked else logging.INFO,
        message="Model Armor response sanitization evaluated",
        intent=intent,
        outcome=outcome,
        event_type="model_armor_output_guardrail",
    )

    if is_blocked:
        return _blocked_response("output")
    return None


# Memory Bank: non-blocking asynchronous ingestion in background with active PII scrubbing.
async def _add_events_to_memory(callback_context: CallbackContext) -> None:
    """Persist session events to Memory Bank asynchronously after scrubbing PII."""
    try:
        invocation = callback_context._invocation_context
        memory_service = invocation.memory_service
        session = invocation.session
        if memory_service is None or not session.events:
            return

        intent = {
            "action": "memory_bank_ingestion",
            "user_id": session.user_id,
            "app_name": session.app_name,
            "event_count": len(session.events),
        }

        # Active PII scrubbing on events prior to persisting in Memory Bank
        scrubbed_events = []
        for event in session.events:
            if hasattr(event, "content") and event.content:
                # If event has text content parts, scrub them
                if hasattr(event.content, "parts") and event.content.parts:
                    for part in event.content.parts:
                        if getattr(part, "text", None):
                            part.text = PiiScrubber.scrub_text(part.text)
            scrubbed_events.append(event)

        await memory_service.add_events_to_memory(
            app_name=session.app_name,
            user_id=session.user_id,
            events=scrubbed_events,
            custom_metadata={"wait_for_completion": True},
        )

        outcome = {
            "status": "success",
            "ingested_event_count": len(scrubbed_events),
            "pii_scrubbing_applied": True,
        }
        log_intent_outcome(
            logger=_logger,
            level=logging.INFO,
            message="Memory Bank events successfully scrubbed and ingested",
            intent=intent,
            outcome=outcome,
            event_type="memory_bank_sync",
        )
    except Exception as exc:
        outcome = {
            "status": "error",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
        log_intent_outcome(
            logger=_logger,
            level=logging.WARNING,
            message="Memory Bank event ingestion failed",
            intent=intent if "intent" in locals() else {"action": "memory_bank_ingestion"},
            outcome=outcome,
            event_type="memory_bank_sync",
        )


_ROOT_MODEL = os.environ.get("ROOT_AGENT_MODEL", "gemini-2.5-pro")

# Root MAS Coordinator Agent ("Sparky the Math Mascot").
root_agent = Agent(
    name="root_agent",
    description="Primary School Math Tutor MAS Root Coordinator Agent",
    model=Gemini(
        model=_ROOT_MODEL,
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

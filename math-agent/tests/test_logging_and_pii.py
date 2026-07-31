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

"""Unit tests for active PII scrubbing, structured JSON logging, and intent vs outcome tracking."""

import io
import json
import logging
import pytest

from app.json_logger import JsonFormatter, log_intent_outcome
from app.pii_scrubber import PiiScrubber
from app.reward_fun_agent import generate_funny_reward_image


def test_pii_scrubber_text():
    """Verify that email, phone, SSN, credit card, and key patterns are redacted."""
    raw_text = (
        "Contact me at alice.smith@example.com or call +1-555-867-5309. "
        "SSN is 123-45-6789 and card is 4111-1111-1111-1111. "
        "API key is apikey: secret_token_12345"
    )
    scrubbed = PiiScrubber.scrub_text(raw_text)

    assert "alice.smith@example.com" not in scrubbed
    assert "[EMAIL_REDACTED]" in scrubbed

    assert "+1-555-867-5309" not in scrubbed
    assert "[PHONE_REDACTED]" in scrubbed

    assert "123-45-6789" not in scrubbed
    assert "[SENSITIVE_ID_REDACTED]" in scrubbed

    assert "4111-1111-1111-1111" not in scrubbed
    assert "[CREDIT_CARD_REDACTED]" in scrubbed

    assert "secret_token_12345" not in scrubbed
    assert "[KEY_REDACTED]" in scrubbed


def test_pii_scrubber_nested_data():
    """Verify recursive scrubbing across dicts and lists."""
    data = {
        "user_email": "user@domain.com",
        "contacts": ["555-123-4567", "other@domain.org"],
        "metadata": {"key": "secret password: mypassword123"},
    }
    scrubbed = PiiScrubber.scrub_data(data)

    assert scrubbed["user_email"] == "[EMAIL_REDACTED]"
    assert scrubbed["contacts"][0] == "[PHONE_REDACTED]"
    assert scrubbed["contacts"][1] == "[EMAIL_REDACTED]"
    assert "[KEY_REDACTED]" in scrubbed["metadata"]["key"]


def test_json_formatter_intent_and_outcome():
    """Verify JsonFormatter outputs valid JSON containing timestamp, severity, intent, outcome, and scrubbed text."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("test_structured_logger")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    intent = {"action": "test_request", "email": "test@example.com"}
    outcome = {"status": "success", "result": "done for phone 555-000-1111"}

    log_intent_outcome(
        logger=logger,
        level=logging.INFO,
        message="Execution completed for user user@example.com",
        intent=intent,
        outcome=outcome,
        event_type="unit_test_event",
    )

    output = stream.getvalue().strip()
    parsed = json.loads(output)

    assert parsed["severity"] == "INFO"
    assert parsed["event_type"] == "unit_test_event"
    assert "[EMAIL_REDACTED]" in parsed["message"]
    assert parsed["intent"]["email"] == "[EMAIL_REDACTED]"
    assert parsed["outcome"]["result"] == "done for phone [PHONE_REDACTED]"


def test_reward_badge_tool_structured_execution():
    """Verify generate_funny_reward_image returns valid output."""
    res = generate_funny_reward_image(
        title="Math Wizard!",
        joke_punchline="Because 7 ate 9!",
        theme="star",
    )
    assert res.status == "success"
    assert res.title == "Math Wizard!"
    assert "<svg" in res.badge_svg
    assert "data:image/svg+xml" in res.badge_markdown

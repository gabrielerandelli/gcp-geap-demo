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

"""Structured JSON Logging module with Intent vs Outcome support and PII scrubbing."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.pii_scrubber import PiiScrubber


class JsonFormatter(logging.Formatter):
    """Logging Formatter that outputs single-line JSON records formatted for GCP Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a python LogRecord into a JSON string with PII scrubbing.

        Args:
            record (logging.LogRecord): The log record to format.

        Returns:
            str: Single-line JSON representation of the log entry.
        """
        message = record.getMessage()
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)

        if record.exc_text:
            if message:
                message = f"{message}\n{record.exc_text}"
            else:
                message = record.exc_text

        # Base log fields compatible with GCP Cloud Logging severity & structure
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": PiiScrubber.scrub_text(message),
        }

        # Intent vs Outcome metadata support
        if hasattr(record, "intent") and record.intent is not None:
            log_payload["intent"] = PiiScrubber.scrub_data(record.intent)
        if hasattr(record, "outcome") and record.outcome is not None:
            log_payload["outcome"] = PiiScrubber.scrub_data(record.outcome)
        if hasattr(record, "event_type") and record.event_type:
            log_payload["event_type"] = record.event_type

        # Include additional extra dict context if passed in record
        if hasattr(record, "context") and isinstance(record.context, dict):
            log_payload["context"] = PiiScrubber.scrub_data(record.context)

        return json.dumps(log_payload, ensure_ascii=False)


def setup_structured_logging(level: int = logging.INFO) -> None:
    """Configure the root logger to use structured JSON output on stdout.

    Args:
        level (int): Minimum logging level (e.g. logging.INFO).
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove pre-existing default handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)


def log_intent_outcome(
    logger: logging.Logger,
    level: int,
    message: str,
    intent: Any,
    outcome: Any,
    event_type: str = "execution_cycle",
    context: dict[str, Any] | None = None,
) -> None:
    """Helper utility to log structured Intent vs Outcome events.

    Args:
        logger (logging.Logger): Python logger instance.
        level (int): Logging level (e.g., logging.INFO, logging.WARNING).
        message (str): High-level event summary.
        intent (Any): Data structure detailing the intended goal/request.
        outcome (Any): Data structure detailing the actual result/outcome.
        event_type (str, optional): Event categorization tag.
        context (dict, optional): Additional contextual metadata.
    """
    extra = {
        "intent": intent,
        "outcome": outcome,
        "event_type": event_type,
    }
    if context:
        extra["context"] = context
    logger.log(level, message, extra=extra)

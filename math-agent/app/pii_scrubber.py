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

"""PII Redaction and Data Scrubbing utility for GEAP agents and tools."""

from __future__ import annotations

import re
from typing import Any

# Regular expression patterns for common PII types
_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE
)
_PHONE_PATTERN = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
)
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
_AUTH_TOKEN_PATTERN = re.compile(
    r"\b(?:bearer|token|apikey|api_key|password|secret)\s*[:=]\s*[^\s,;']+",
    re.IGNORECASE,
)


class PiiScrubber:
    """Active PII scrubber for text, dicts, lists, and log payloads."""

    @classmethod
    def scrub_text(cls, text: str) -> str:
        """Scrub PII from a plain string.

        Args:
            text (str): Input text that may contain PII.

        Returns:
            str: Sanitized text with sensitive patterns replaced.
        """
        if not text or not isinstance(text, str):
            return text

        scrubbed = _EMAIL_PATTERN.sub("[EMAIL_REDACTED]", text)
        scrubbed = _PHONE_PATTERN.sub("[PHONE_REDACTED]", scrubbed)
        scrubbed = _SSN_PATTERN.sub("[SENSITIVE_ID_REDACTED]", scrubbed)
        scrubbed = _CREDIT_CARD_PATTERN.sub("[CREDIT_CARD_REDACTED]", scrubbed)
        scrubbed = _AUTH_TOKEN_PATTERN.sub("[KEY_REDACTED]", scrubbed)
        return scrubbed

    @classmethod
    def scrub_data(cls, data: Any) -> Any:
        """Recursively scrub PII from nested dictionaries, lists, or primitive values.

        Args:
            data (Any): Arbitrary python object (dict, list, str, primitive).

        Returns:
            Any: Cleaned object with all string fields scrubbed.
        """
        if isinstance(data, str):
            return cls.scrub_text(data)
        if isinstance(data, dict):
            return {
                str(key): cls.scrub_data(val) for key, val in data.items()
            }
        if isinstance(data, list):
            return [cls.scrub_data(item) for item in data]
        if isinstance(data, tuple):
            return tuple(cls.scrub_data(item) for item in data)
        return data

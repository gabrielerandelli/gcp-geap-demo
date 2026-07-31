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
from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types
from pydantic import BaseModel, Field

from app.json_logger import log_intent_outcome

_logger = logging.getLogger(__name__)


class RewardBadgeInput(BaseModel):
    """Input parameters for generating a funny reward badge card."""

    title: str = Field(
        ...,
        description="Celebratory title on the reward badge (e.g., 'Math Superstar!', 'Owl-some Job!').",
    )
    joke_punchline: str = Field(
        ...,
        description="A funny kid-friendly math joke or riddle punchline to display on the badge.",
    )
    theme: str = Field(
        "star",
        description="Theme style for the badge. Options: 'star', 'trophy', 'owl', 'puppy', 'rocket'.",
    )


class RewardBadgeOutput(BaseModel):
    """Output structure for the generated cartoon reward badge."""

    status: str = Field(..., description="Execution status: 'success' or 'error'.")
    title: str = Field(..., description="Title displayed on the badge.")
    joke_punchline: str = Field(..., description="Joke punchline displayed on the badge.")
    theme: str = Field(..., description="Applied badge theme name.")
    badge_svg: str = Field("", description="Complete SVG string representing the cartoon badge card.")
    badge_markdown: str = Field("", description="Embedded Markdown data URI string for instant UI rendering.")
    error: str | None = Field(None, description="Error message if badge generation failed.")
    recovery_instruction: str | None = Field(
        None, description="Guided recovery advice for the LLM if an error occurred."
    )


def generate_funny_reward_image(
    title: str, joke_punchline: str, theme: str = "star"
) -> RewardBadgeOutput:
    """Generate a vibrant, funny cartoon reward badge card for a primary school student.

    Args:
        title (str): Celebratory badge title (e.g. 'Math Superstar!', 'Owl-some Job!', 'Math Wizard!').
        joke_punchline (str): A funny kid-friendly math joke or riddle punchline.
        theme (str): Theme of the badge. Supported options are 'star', 'trophy', 'owl', 'puppy', 'rocket' (defaults to 'star').

    Returns:
        RewardBadgeOutput: Pydantic model containing status, title, joke_punchline, theme, raw badge_svg, embedded badge_markdown, and recovery instructions if an error occurs.
    """
    intent = {
        "action": "generate_reward_badge_image",
        "title": title,
        "theme": theme,
        "joke_punchline": joke_punchline,
    }
    try:
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

        output = RewardBadgeOutput(
            status="success",
            title=title,
            joke_punchline=joke_punchline,
            theme=theme,
            badge_svg=svg_content,
            badge_markdown=f"![{title}](data:image/svg+xml;utf8,{svg_content})",
        )
        log_intent_outcome(
            logger=_logger,
            level=logging.INFO,
            message="Reward badge generation succeeded",
            intent=intent,
            outcome={
                "status": "success",
                "title": title,
                "theme": theme,
                "svg_bytes": len(svg_content),
            },
            event_type="reward_tool_execution",
        )
        return output
    except Exception as exc:
        output = RewardBadgeOutput(
            status="error",
            title=title,
            joke_punchline=joke_punchline,
            theme=theme,
            badge_svg="",
            badge_markdown="",
            error=f"Badge generation failed: {exc}",
            recovery_instruction=(
                "Tell the student you are super proud of their success and share the joke, "
                "even though the cartoon badge artwork could not be rendered this time!"
            ),
        )
        log_intent_outcome(
            logger=_logger,
            level=logging.WARNING,
            message="Reward badge generation failed",
            intent=intent,
            outcome=output.model_dump(),
            event_type="reward_tool_execution",
        )
        return output


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

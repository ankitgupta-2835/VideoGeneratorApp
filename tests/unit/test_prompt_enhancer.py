"""Prompt-enhancer agent: detailed prompts with a deterministic fallback."""

from __future__ import annotations

import json

from src.agents.prompt_enhancer import (
    PromptEnhanceInput,
    PromptEnhancerAgent,
    fallback_prompt,
)
from src.llm.client import FakeLLMClient


def _payload() -> PromptEnhanceInput:
    return PromptEnhanceInput(
        title="The Rise of Local LLMs",
        category="ai_tech",
        narration="A small model runs on a laptop in a quiet apartment.",
        on_screen_text="Local AI",
    )


def test_llm_prompt_is_returned():
    fake = FakeLLMClient([json.dumps({"prompt": "A detailed cinematic scene."})])
    result = PromptEnhancerAgent(fake).run(_payload())

    assert result.status == "ok"
    assert result.data.prompt == "A detailed cinematic scene."
    assert "Local AI" in fake.calls[0]["prompt"]


def test_invalid_reply_falls_back_to_deterministic_prompt():
    fake = FakeLLMClient(["not json at all"])
    result = PromptEnhancerAgent(fake).run(_payload())

    assert result.status == "ok"
    assert result.data.prompt == fallback_prompt(_payload())
    assert "Wide 16:9" in result.data.prompt


def test_empty_prompt_falls_back():
    fake = FakeLLMClient([json.dumps({"prompt": ""})])
    result = PromptEnhancerAgent(fake).run(_payload())

    assert result.status == "ok"
    assert result.data.prompt == fallback_prompt(_payload())

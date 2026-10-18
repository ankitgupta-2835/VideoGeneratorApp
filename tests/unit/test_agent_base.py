"""Task 1.3 tests: Agent contract, retries, and Supervisor."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from src.agents.base import Agent, AgentResult, Supervisor
from src.errors import AgentError


class Out(BaseModel):
    value: int


class Inp(BaseModel):
    prompt: str


class EchoAgent(Agent):
    name = "echo"
    input_model = Inp
    output_model = Out

    def _run(self, payload: Inp) -> AgentResult:
        return AgentResult("ok", data={"value": len(payload.prompt)})


class FlakyAgent(Agent):
    name = "flaky"
    max_retries = 1

    def __init__(self) -> None:
        self.calls = 0

    def _run(self, payload) -> AgentResult:
        self.calls += 1
        if self.calls < 2:
            return AgentResult("fail", notes=["transient"])
        return AgentResult("ok", data={"done": True})


class AlwaysFailAgent(Agent):
    name = "always_fail"
    max_retries = 2

    def __init__(self) -> None:
        self.calls = 0

    def _run(self, payload) -> AgentResult:
        self.calls += 1
        return AgentResult("fail")


class BadOutputAgent(Agent):
    name = "bad_output"
    output_model = Out

    def _run(self, payload) -> AgentResult:
        return AgentResult("ok", data={"wrong": "field"})


def test_valid_input_and_output():
    result = EchoAgent().run({"prompt": "hello"})
    assert result.status == "ok"
    assert result.data.value == 5  # validated into the output model


def test_invalid_input_raises():
    with pytest.raises(AgentError, match="invalid input"):
        EchoAgent().run({"nope": 1})


def test_retries_until_success():
    agent = FlakyAgent()
    result = agent.run({})
    assert result.status == "ok"
    assert result.attempts == 2
    assert agent.calls == 2


def test_fail_safe_after_retries():
    agent = AlwaysFailAgent()
    result = agent.run({})
    assert result.status == "fail"
    assert result.attempts == 3
    assert agent.calls == 3


def test_output_contract_violation_raises():
    with pytest.raises(AgentError, match="invalid output"):
        BadOutputAgent().run({})


def test_supervisor_runs_registered_agent():
    sup = Supervisor()
    sup.register(EchoAgent())
    assert sup.run("echo", {"prompt": "hi"}).status == "ok"


def test_supervisor_unknown_agent_raises():
    with pytest.raises(AgentError, match="no agent registered"):
        Supervisor().run("ghost", {})

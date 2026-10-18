"""Agent base class, result contract, and supervisor.

Every pipeline task is a small :class:`Agent` with a declared input/output
contract. The :class:`Supervisor` runs agents and logs their hand-offs. A
``rework`` result is returned to the caller (a gate decides what to do); a
``fail`` result is retried up to ``max_retries`` and then returned as a
fail-safe so the pipeline never blocks.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from src.errors import AgentError
from src.logging_setup import get_logger
from src.store.db import Database

__all__ = ["Agent", "AgentResult", "Supervisor"]

Status = Literal["ok", "rework", "fail"]


@dataclass
class AgentResult:
    status: Status
    data: Any = None
    notes: list[str] = field(default_factory=list)
    attempts: int = 1


class Agent(ABC):
    """A bounded, single-responsibility step with JSON contracts."""

    name: str = "agent"
    max_retries: int = 0
    input_model: type[BaseModel] | None = None
    output_model: type[BaseModel] | None = None

    def run(self, payload: Any) -> AgentResult:
        validated = self._validate(payload, self.input_model, "input")
        last: AgentResult | None = None
        for attempt in range(self.max_retries + 1):
            result = self._run(validated)
            if not isinstance(result, AgentResult):  # defensive contract check
                raise AgentError(f"{self.name} returned a non-AgentResult")
            if result.status == "ok":
                result.data = self._validate(result.data, self.output_model, "output")
                result.attempts = attempt + 1
                return result
            result.attempts = attempt + 1
            last = result
        assert last is not None
        return last

    def _validate(self, data: Any, model: type[BaseModel] | None, kind: str) -> Any:
        if model is None:
            return data
        if isinstance(data, model):
            return data
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise AgentError(f"{self.name}: invalid {kind}: {exc}") from exc

    @abstractmethod
    def _run(self, payload: Any) -> AgentResult:
        """Do the work. Must return an :class:`AgentResult`."""


class Supervisor:
    """Registers agents and runs them by name (logging each hand-off)."""

    def __init__(self, *, db: Database | None = None, logger: logging.Logger | None = None) -> None:
        self.db = db
        self.log = logger or get_logger("supervisor")
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise AgentError(f"no agent registered as {name!r}") from exc

    def run(self, name: str, payload: Any) -> AgentResult:
        agent = self.get(name)
        result = agent.run(payload)
        self.log.info(
            "agent %s -> %s (attempts=%d, notes=%d)",
            name,
            result.status,
            result.attempts,
            len(result.notes),
        )
        return result

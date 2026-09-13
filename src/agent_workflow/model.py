from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping

CodeAction = Callable[[dict[str, Any]], Any]
CodeCheck = Callable[[dict[str, Any], Any], bool]


@dataclass(frozen=True)
class AgentAction:
    agent: str
    task: str
    session: str | None = None
    new_session: bool = False


Action = CodeAction | str | AgentAction
Check = CodeCheck | str | AgentAction


class RecoveryAction(str, Enum):
    RETRY = "retry"
    TAKE_OVER = "take_over"
    ABORT = "abort"


@dataclass(frozen=True)
class RecoveryPolicy:
    agent: str
    task: str = "Diagnose the failed step and choose a recovery action."
    allow: tuple[RecoveryAction, ...] = (
        RecoveryAction.RETRY,
        RecoveryAction.TAKE_OVER,
        RecoveryAction.ABORT,
    )
    max_attempts: int = 1
    session: str | None = None
    takeover_task: str = "Take over and complete the failed step."

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("RecoveryPolicy.max_attempts must be >= 1")


@dataclass(frozen=True)
class Step:
    id: str
    run: Action
    check: Check | None = None
    on_failure: RecoveryPolicy | None = None
    repeat: int = 1
    until: Check | None = None
    max_iterations: int | None = None

    def __post_init__(self) -> None:
        if self.repeat < 1:
            raise ValueError("Step.repeat must be >= 1")
        if self.until is not None and self.max_iterations is None:
            raise ValueError("Step.max_iterations is required when until is set")
        if self.max_iterations is not None and self.max_iterations < 1:
            raise ValueError("Step.max_iterations must be >= 1")
        if self.until is not None and self.repeat != 1:
            raise ValueError("Use either repeat or until, not both")


@dataclass(frozen=True)
class Workflow:
    steps: list[Step]
    name: str = "workflow"


@dataclass
class StepResult:
    id: str
    success: bool
    attempts: int = 0
    iterations: int = 0
    output: Any = None
    error: str | None = None
    recovery_action: RecoveryAction | None = None


@dataclass
class WorkflowResult:
    success: bool
    steps: list[StepResult]
    context: dict[str, Any]
    failed_step: str | None = None
    error: str | None = None
    recovery_action: RecoveryAction | None = None

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without extra
    raise ImportError("YAML support requires PyYAML: pip install agent-workflow[yaml]") from exc

from .model import AgentAction, RecoveryAction, RecoveryPolicy, Step, Workflow


def _load_source(source: str | Path) -> dict[str, Any]:
    if isinstance(source, Path):
        text = source.read_text()
    elif "\n" not in source and Path(source).exists():
        text = Path(source).read_text()
    else:
        text = source
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("workflow YAML must be a mapping")
    return data


def _parse_action(value: Any) -> Any:
    if isinstance(value, str) or callable(value):
        return value
    if not isinstance(value, dict):
        raise ValueError(f"action must be a function name or agent mapping, got {type(value).__name__}")
    if "agent" not in value:
        raise ValueError("agent action mapping requires 'agent'")
    if "task" not in value:
        raise ValueError("agent action mapping requires 'task'")
    return AgentAction(
        agent=str(value["agent"]),
        task=str(value["task"]),
        session=value.get("session"),
        new_session=bool(value.get("new_session", False)),
    )


def _parse_recovery(value: Any) -> RecoveryPolicy | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("on_failure must be a mapping")
    if "agent" not in value:
        raise ValueError("on_failure requires 'agent'")
    raw_allow = value.get("allow", ["retry", "take_over", "abort"])
    try:
        allow = tuple(RecoveryAction(str(item)) for item in raw_allow)
    except ValueError as exc:
        raise ValueError(f"invalid recovery action in allow: {raw_allow}") from exc
    return RecoveryPolicy(
        agent=str(value["agent"]),
        task=str(value.get("task", "Diagnose the failed step and choose a recovery action.")),
        allow=allow,
        max_attempts=int(value.get("max_attempts", 1)),
        session=value.get("session"),
        takeover_task=str(value.get("takeover_task", "Take over and complete the failed step.")),
    )


def _parse_step(raw: Any, index: int) -> Step:
    if not isinstance(raw, dict):
        raise ValueError(f"steps[{index}] must be a mapping")
    step_id = raw.get("id")
    if not step_id:
        raise ValueError(f"steps[{index}] requires 'id'")

    if "run" in raw:
        run = _parse_action(raw["run"])
    elif "agent" in raw:
        if "task" not in raw:
            raise ValueError(f"agent step '{step_id}' requires 'task'")
        run = AgentAction(
            agent=str(raw["agent"]),
            task=str(raw["task"]),
            session=raw.get("session"),
            new_session=bool(raw.get("new_session", False)),
        )
    else:
        raise ValueError(f"step '{step_id}' requires 'run' or 'agent'")

    check = _parse_action(raw["check"]) if "check" in raw and raw["check"] is not None else None
    until = _parse_action(raw["until"]) if "until" in raw and raw["until"] is not None else None

    return Step(
        id=str(step_id),
        run=run,
        check=check,
        on_failure=_parse_recovery(raw.get("on_failure")),
        repeat=int(raw.get("repeat", 1)),
        until=until,
        max_iterations=int(raw["max_iterations"]) if raw.get("max_iterations") is not None else None,
    )


def load_yaml(source: str | Path) -> Workflow:
    """Load YAML into the same runtime model used by Python-authored workflows."""
    data = _load_source(source)
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("workflow YAML requires a 'steps' list")
    return Workflow(
        steps=[_parse_step(raw, i) for i, raw in enumerate(raw_steps)],
        name=str(data.get("name", "workflow")),
    )

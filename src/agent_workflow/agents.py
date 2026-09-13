from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence


@dataclass
class AgentRequest:
    kind: str
    task: str
    context: dict[str, Any]
    result: Any = None
    error: str | None = None
    session: str | None = None
    resume_session_id: str | None = None
    new_session: bool = False


@dataclass
class AgentResponse:
    success: bool
    output: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    error: str | None = None


class Agent(Protocol):
    def run(self, request: AgentRequest) -> AgentResponse: ...


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


def _default_process_runner(cmd: Sequence[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def _build_prompt(request: AgentRequest) -> str:
    payload = {
        "kind": request.kind,
        "task": request.task,
        "context": _jsonable(request.context),
        "previous_result": _jsonable(request.result),
        "error": request.error,
    }
    base = (
        "You are one step inside a deterministic workflow. Work only on this step.\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, default=repr)
    )

    if request.kind == "recovery":
        return base + (
            "\nReturn ONLY JSON with this shape: "
            '{"action":"retry|take_over|abort","reason":"..."}. '
            "Choose retry if you repaired the environment/code and the original step should run again; "
            "take_over if an agent should complete the step directly; abort if it cannot be safely recovered."
        )
    if request.kind in {"check", "until"}:
        return base + '\nReturn ONLY JSON: {"pass":true|false,"reason":"..."}.'
    return base + '\nReturn ONLY JSON: {"success":true|false,"result":...,"reason":"..."}.'


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_model_data(text: str) -> dict[str, Any]:
    candidate = _strip_code_fence(text)
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {"result": value}


class ClaudeCodeAgent:
    """Claude Code adapter using non-interactive print mode."""

    def __init__(
        self,
        executable: str = "claude",
        *,
        cwd: str | Path | None = None,
        extra_args: Sequence[str] = (),
        process_runner: ProcessRunner = _default_process_runner,
    ) -> None:
        self.executable = executable
        self.cwd = str(cwd) if cwd is not None else None
        self.extra_args = list(extra_args)
        self.process_runner = process_runner

    def run(self, request: AgentRequest) -> AgentResponse:
        prompt = _build_prompt(request)
        cmd = [self.executable, "-p", prompt, "--output-format", "json"]
        if request.resume_session_id:
            cmd += ["--resume", request.resume_session_id]
        cmd += self.extra_args

        completed = self.process_runner(cmd, cwd=self.cwd)
        if completed.returncode != 0:
            return AgentResponse(success=False, error=completed.stderr.strip() or f"exit {completed.returncode}")

        try:
            outer = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return AgentResponse(success=False, output=completed.stdout, error=f"invalid Claude JSON: {exc}")

        text = str(outer.get("result", ""))
        data = _parse_model_data(text)
        model_success = data.get("success")
        success = not bool(outer.get("is_error", False))
        if model_success is False:
            success = False
        return AgentResponse(
            success=success,
            output=text,
            data=data,
            session_id=outer.get("session_id"),
            error=outer.get("error") if not success else None,
        )


class CodexAgent:
    """Codex CLI adapter using `codex exec --json` JSONL output."""

    def __init__(
        self,
        executable: str = "codex",
        *,
        cwd: str | Path | None = None,
        extra_args: Sequence[str] = (),
        process_runner: ProcessRunner = _default_process_runner,
    ) -> None:
        self.executable = executable
        self.cwd = str(cwd) if cwd is not None else None
        self.extra_args = list(extra_args)
        self.process_runner = process_runner

    def run(self, request: AgentRequest) -> AgentResponse:
        prompt = _build_prompt(request)
        cmd = [self.executable, "exec", "--json"]
        cmd += self.extra_args
        if request.resume_session_id:
            cmd += ["resume", request.resume_session_id]
        cmd += [prompt]

        completed = self.process_runner(cmd, cwd=self.cwd)
        if completed.returncode != 0:
            return AgentResponse(success=False, error=completed.stderr.strip() or f"exit {completed.returncode}")

        session_id: str | None = None
        text = ""
        parse_errors = 0
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            if event.get("type") == "thread.started":
                session_id = event.get("thread_id") or session_id
            if event.get("type") == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    text = str(item.get("text", ""))

        if not text and parse_errors:
            return AgentResponse(success=False, output=completed.stdout, error="invalid Codex JSONL output")

        data = _parse_model_data(text)
        success = data.get("success", True) is not False
        return AgentResponse(
            success=success,
            output=text,
            data=data,
            session_id=session_id,
            error=data.get("reason") if not success else None,
        )

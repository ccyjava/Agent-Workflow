from __future__ import annotations

from typing import Any, Callable, Mapping

from .agents import Agent, AgentRequest, AgentResponse
from .model import (
    Action,
    AgentAction,
    Check,
    RecoveryAction,
    RecoveryPolicy,
    Step,
    StepResult,
    Workflow,
    WorkflowResult,
)


class Runner:
    def __init__(
        self,
        functions: Mapping[str, Callable[..., Any]] | None = None,
        agents: Mapping[str, Agent] | None = None,
    ) -> None:
        self.functions = dict(functions or {})
        self.agents = dict(agents or {})
        self._sessions: dict[tuple[str, str], str] = {}

    def run(self, workflow: Workflow, context: dict[str, Any] | None = None) -> WorkflowResult:
        ctx = context if context is not None else {}
        step_results: list[StepResult] = []

        for step in workflow.steps:
            step_result = self._run_step(step, ctx)
            step_results.append(step_result)
            if not step_result.success:
                return WorkflowResult(
                    success=False,
                    steps=step_results,
                    context=ctx,
                    failed_step=step.id,
                    error=step_result.error,
                    recovery_action=step_result.recovery_action,
                )

        return WorkflowResult(success=True, steps=step_results, context=ctx)

    def _run_step(self, step: Step, ctx: dict[str, Any]) -> StepResult:
        out = StepResult(id=step.id, success=False)
        iteration_limit = step.max_iterations if step.until is not None else step.repeat
        assert iteration_limit is not None

        for _ in range(iteration_limit):
            out.iterations += 1
            success, value, error, attempts, recovery_action = self._execute_iteration(step, ctx)
            out.attempts += attempts
            out.output = value
            out.recovery_action = recovery_action
            if not success:
                out.error = error
                return out

            if step.until is not None:
                try:
                    done = self._evaluate_check(step.until, ctx, value, step.id, kind="until")
                except Exception as exc:  # checker failures are workflow failures
                    out.error = f"until check failed: {exc}"
                    return out
                if done:
                    out.success = True
                    return out

        if step.until is not None:
            out.error = f"max_iterations exhausted for step '{step.id}'"
            return out

        out.success = True
        return out

    def _execute_iteration(
        self, step: Step, ctx: dict[str, Any]
    ) -> tuple[bool, Any, str | None, int, RecoveryAction | None]:
        run_attempts = 0
        recovery_attempts = 0
        last_value: Any = None
        last_error: str | None = None
        last_recovery: RecoveryAction | None = None
        run_original = True

        while True:
            if run_original:
                run_attempts += 1
                try:
                    last_value = self._execute_action(step.run, ctx, step.id, kind="run")
                    passed = True if step.check is None else self._evaluate_check(
                        step.check, ctx, last_value, step.id, kind="check"
                    )
                    if passed:
                        return True, last_value, None, run_attempts, last_recovery
                    last_error = f"check failed for step '{step.id}'"
                except Exception as exc:
                    last_error = f"step '{step.id}' failed: {exc}"

            policy = step.on_failure
            if policy is None:
                return False, last_value, last_error, run_attempts, last_recovery
            if recovery_attempts >= policy.max_attempts:
                return False, last_value, last_error or "recovery exhausted", run_attempts, last_recovery

            recovery_attempts += 1
            action = self._recover(policy, step, ctx, last_value, last_error)
            last_recovery = action

            if action == RecoveryAction.ABORT:
                return False, last_value, last_error or "aborted by recovery agent", run_attempts, action

            if action == RecoveryAction.RETRY:
                run_original = True
                continue

            # TAKE_OVER runs the agent implementation in place of the original code.
            # If validation still fails, ask recovery again without silently rerunning code.
            run_original = False
            try:
                last_value = self._take_over(policy, step, ctx, last_value, last_error)
                passed = True if step.check is None else self._evaluate_check(
                    step.check, ctx, last_value, step.id, kind="check"
                )
                if passed:
                    return True, last_value, None, run_attempts, action
                last_error = f"check failed after agent take-over for step '{step.id}'"
            except Exception as exc:
                last_error = f"agent take-over failed for step '{step.id}': {exc}"

    def _recover(
        self,
        policy: RecoveryPolicy,
        step: Step,
        ctx: dict[str, Any],
        result: Any,
        error: str | None,
    ) -> RecoveryAction:
        response = self._call_agent_with_session(
            agent_name=policy.agent,
            request=AgentRequest(
                kind="recovery",
                task=policy.task,
                context=ctx,
                result=result,
                error=error,
                session=policy.session,
            ),
        )
        if not response.success:
            return RecoveryAction.ABORT
        raw = response.data.get("action", "abort")
        try:
            action = RecoveryAction(str(raw).lower())
        except ValueError:
            return RecoveryAction.ABORT
        if action not in policy.allow:
            return RecoveryAction.ABORT
        return action

    def _take_over(
        self,
        policy: RecoveryPolicy,
        step: Step,
        ctx: dict[str, Any],
        result: Any,
        error: str | None,
    ) -> Any:
        response = self._call_agent_with_session(
            agent_name=policy.agent,
            request=AgentRequest(
                kind="take_over",
                task=policy.takeover_task,
                context=ctx,
                result=result,
                error=error,
                session=policy.session,
            ),
        )
        if not response.success:
            raise RuntimeError(response.error or "agent reported take-over failure")
        return response.data.get("result", response.output)

    def _execute_action(self, action: Action, ctx: dict[str, Any], step_id: str, kind: str) -> Any:
        if isinstance(action, AgentAction):
            response = self._call_agent_action(action, ctx, kind=kind)
            if not response.success:
                raise RuntimeError(response.error or f"agent '{action.agent}' failed")
            return response.data.get("result", response.output)

        fn = self._resolve_function(action)
        return fn(ctx)

    def _evaluate_check(
        self,
        check: Check,
        ctx: dict[str, Any],
        result: Any,
        step_id: str,
        kind: str,
    ) -> bool:
        if isinstance(check, AgentAction):
            response = self._call_agent_action(check, ctx, kind=kind, result=result)
            if not response.success:
                return False
            if "pass" in response.data:
                return bool(response.data["pass"])
            if "success" in response.data:
                return bool(response.data["success"])
            return response.output.strip().lower() in {"pass", "passed", "true", "yes", "ok"}

        fn = self._resolve_function(check)
        return bool(fn(ctx, result))

    def _resolve_function(self, action: Callable[..., Any] | str) -> Callable[..., Any]:
        if callable(action):
            return action
        try:
            return self.functions[action]
        except KeyError as exc:
            raise KeyError(f"No function registered as '{action}'") from exc

    def _call_agent_action(
        self,
        action: AgentAction,
        ctx: dict[str, Any],
        kind: str,
        result: Any = None,
    ) -> AgentResponse:
        return self._call_agent_with_session(
            action.agent,
            AgentRequest(
                kind=kind,
                task=action.task,
                context=ctx,
                result=result,
                session=action.session,
                new_session=action.new_session,
            ),
        )

    def _call_agent_with_session(self, agent_name: str, request: AgentRequest) -> AgentResponse:
        if request.session and not request.new_session and request.resume_session_id is None:
            request.resume_session_id = self._sessions.get((agent_name, request.session))
        response = self._call_agent(agent_name, request)
        if request.session and not request.new_session and response.session_id:
            self._sessions[(agent_name, request.session)] = response.session_id
        return response

    def _call_agent(self, agent_name: str, request: AgentRequest) -> AgentResponse:
        try:
            agent = self.agents[agent_name]
        except KeyError as exc:
            raise KeyError(f"No agent registered as '{agent_name}'") from exc
        return agent.run(request)

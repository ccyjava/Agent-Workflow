from dataclasses import dataclass

from agent_workflow import (
    AgentAction,
    AgentResponse,
    RecoveryAction,
    RecoveryPolicy,
    Runner,
    Step,
    Workflow,
)


@dataclass
class ScriptedAgent:
    responses: list[AgentResponse]

    def __post_init__(self):
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


def test_runs_code_step_and_check():
    events = []

    def launch(ctx):
        events.append("launch")
        ctx["ready"] = True
        return "started"

    def ready(ctx, result):
        return ctx["ready"] and result == "started"

    workflow = Workflow([Step("launch", run=launch, check=ready)])
    result = Runner().run(workflow)

    assert result.success is True
    assert events == ["launch"]
    assert result.steps[0].attempts == 1


def test_failed_check_without_recovery_fails_workflow():
    workflow = Workflow([Step("bad", run=lambda ctx: 1, check=lambda ctx, result: False)])

    result = Runner().run(workflow)

    assert result.success is False
    assert result.failed_step == "bad"
    assert "check failed" in result.error.lower()


def test_recovery_agent_can_repair_then_retry_original_code_step():
    calls = {"run": 0}

    def run_step(ctx):
        calls["run"] += 1
        return None

    def check(ctx, result):
        return ctx.get("fixed", False)

    class RepairAgent(ScriptedAgent):
        def run(self, request):
            self.requests.append(request)
            if request.kind == "recovery":
                request.context["fixed"] = True
            return AgentResponse(success=True, data={"action": "retry"})

    agent = RepairAgent([])
    workflow = Workflow([
        Step(
            "repairable",
            run=run_step,
            check=check,
            on_failure=RecoveryPolicy(agent="claude", max_attempts=2),
        )
    ])

    result = Runner(agents={"claude": agent}).run(workflow)

    assert result.success is True
    assert calls["run"] == 2
    assert [r.kind for r in agent.requests] == ["recovery"]


def test_recovery_agent_can_take_over_step_and_result_is_checked_again():
    class TakeoverAgent(ScriptedAgent):
        def run(self, request):
            self.requests.append(request)
            if request.kind == "recovery":
                return AgentResponse(success=True, data={"action": "take_over"})
            if request.kind == "take_over":
                request.context["done"] = True
                return AgentResponse(success=True, output="agent completed")
            raise AssertionError(request.kind)

    agent = TakeoverAgent([])
    workflow = Workflow([
        Step(
            "do_work",
            run=lambda ctx: "code result",
            check=lambda ctx, result: ctx.get("done", False),
            on_failure=RecoveryPolicy(agent="claude", max_attempts=1),
        )
    ])

    result = Runner(agents={"claude": agent}).run(workflow)

    assert result.success is True
    assert [r.kind for r in agent.requests] == ["recovery", "take_over"]


def test_recovery_abort_stops_workflow():
    agent = ScriptedAgent([AgentResponse(success=True, data={"action": "abort"})])
    workflow = Workflow([
        Step(
            "first",
            run=lambda ctx: None,
            check=lambda ctx, result: False,
            on_failure=RecoveryPolicy(agent="claude", max_attempts=1),
        ),
        Step("never", run=lambda ctx: (_ for _ in ()).throw(AssertionError("must not run"))),
    ])

    result = Runner(agents={"claude": agent}).run(workflow)

    assert result.success is False
    assert result.failed_step == "first"
    assert result.recovery_action == RecoveryAction.ABORT


def test_repeat_runs_step_exact_number_of_times():
    def inc(ctx):
        ctx["count"] = ctx.get("count", 0) + 1
        return ctx["count"]

    result = Runner().run(Workflow([Step("inc", run=inc, repeat=4)]))

    assert result.success is True
    assert result.context["count"] == 4
    assert result.steps[0].iterations == 4


def test_until_repeats_until_condition_passes():
    def advance(ctx):
        ctx["n"] = ctx.get("n", 0) + 1
        return ctx["n"]

    workflow = Workflow([
        Step(
            "advance",
            run=advance,
            until=lambda ctx, result: result >= 3,
            max_iterations=5,
        )
    ])

    result = Runner().run(workflow)

    assert result.success is True
    assert result.context["n"] == 3
    assert result.steps[0].iterations == 3


def test_until_fails_when_max_iterations_is_exhausted():
    workflow = Workflow([
        Step(
            "never_done",
            run=lambda ctx: None,
            until=lambda ctx, result: False,
            max_iterations=2,
        )
    ])

    result = Runner().run(workflow)

    assert result.success is False
    assert result.failed_step == "never_done"
    assert "max_iterations" in result.error


def test_agent_action_can_be_a_normal_step_and_named_session_is_forwarded():
    agent = ScriptedAgent([AgentResponse(success=True, output="ok", session_id="provider-1")])
    workflow = Workflow([
        Step("play", run=AgentAction(agent="claude", task="play game", session="gameplay"))
    ])

    result = Runner(agents={"claude": agent}).run(workflow)

    assert result.success is True
    assert agent.requests[0].kind == "run"
    assert agent.requests[0].task == "play game"
    assert agent.requests[0].session == "gameplay"


def test_named_agent_session_resumes_provider_session_id_on_next_call():
    agent = ScriptedAgent([
        AgentResponse(success=True, output="one", session_id="provider-session-7"),
        AgentResponse(success=True, output="two", session_id="provider-session-7"),
    ])
    action = AgentAction(agent="claude", task="continue task", session="gameplay")
    workflow = Workflow([Step("one", run=action), Step("two", run=action)])

    result = Runner(agents={"claude": agent}).run(workflow)

    assert result.success is True
    assert agent.requests[0].resume_session_id is None
    assert agent.requests[1].resume_session_id == "provider-session-7"


def test_repeated_take_over_attempts_do_not_rerun_original_code():
    calls = {"code": 0, "takeover": 0}

    def code(ctx):
        calls["code"] += 1
        return "code"

    class TwiceAgent:
        def __init__(self):
            self.requests = []

        def run(self, request):
            self.requests.append(request)
            if request.kind == "recovery":
                return AgentResponse(success=True, data={"action": "take_over"})
            if request.kind == "take_over":
                calls["takeover"] += 1
                if calls["takeover"] == 2:
                    request.context["done"] = True
                return AgentResponse(success=True, output=f"takeover-{calls['takeover']}")
            raise AssertionError(request.kind)

    agent = TwiceAgent()
    workflow = Workflow([
        Step(
            "hard",
            run=code,
            check=lambda ctx, result: ctx.get("done", False),
            on_failure=RecoveryPolicy(agent="claude", max_attempts=2),
        )
    ])

    result = Runner(agents={"claude": agent}).run(workflow)

    assert result.success is True
    assert calls == {"code": 1, "takeover": 2}
    assert [r.kind for r in agent.requests] == ["recovery", "take_over", "recovery", "take_over"]


def test_recovery_and_takeover_share_named_agent_session():
    class SessionAgent:
        def __init__(self):
            self.requests = []

        def run(self, request):
            self.requests.append(request)
            if request.kind == "recovery":
                return AgentResponse(
                    success=True,
                    data={"action": "take_over"},
                    session_id="recovery-provider-session",
                )
            if request.kind == "take_over":
                request.context["done"] = True
                return AgentResponse(success=True, output="done", session_id="recovery-provider-session")
            raise AssertionError(request.kind)

    agent = SessionAgent()
    workflow = Workflow([
        Step(
            "recover",
            run=lambda ctx: None,
            check=lambda ctx, result: ctx.get("done", False),
            on_failure=RecoveryPolicy(agent="claude", session="recovery", max_attempts=1),
        )
    ])

    result = Runner(agents={"claude": agent}).run(workflow)

    assert result.success is True
    assert agent.requests[0].resume_session_id is None
    assert agent.requests[1].resume_session_id == "recovery-provider-session"

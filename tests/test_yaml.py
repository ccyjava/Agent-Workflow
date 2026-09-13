from agent_workflow import (
    AgentAction,
    AgentResponse,
    RecoveryAction,
    Runner,
    Step,
    Workflow,
    load_yaml,
)


class EchoAgent:
    def __init__(self):
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        if request.kind in {"check", "until"}:
            return AgentResponse(success=True, data={"pass": True}, session_id="session-1")
        return AgentResponse(success=True, data={"result": "agent-ok"}, session_id="session-1")


def test_yaml_code_workflow_behaves_like_python_workflow():
    yaml_workflow = load_yaml("""
name: counter
steps:
  - id: increment
    run: increment
    check: positive
    repeat: 3
""")
    python_workflow = Workflow([
        Step("increment", run="increment", check="positive", repeat=3)
    ], name="counter")

    def increment(ctx):
        ctx["n"] = ctx.get("n", 0) + 1
        return ctx["n"]

    def positive(ctx, result):
        return result > 0

    functions = {"increment": increment, "positive": positive}
    yaml_result = Runner(functions=functions).run(yaml_workflow)
    python_result = Runner(functions=functions).run(python_workflow)

    assert yaml_result.success is True
    assert yaml_result.context == python_result.context == {"n": 3}
    assert yaml_result.steps[0].iterations == python_result.steps[0].iterations == 3


def test_yaml_agent_step_and_agent_checker_are_normalized():
    workflow = load_yaml("""
steps:
  - id: play
    run:
      agent: claude
      task: play the game
      session: gameplay
    check:
      agent: claude
      task: verify goal
      session: gameplay
""")

    step = workflow.steps[0]
    assert isinstance(step.run, AgentAction)
    assert isinstance(step.check, AgentAction)
    assert step.run.session == "gameplay"

    agent = EchoAgent()
    result = Runner(agents={"claude": agent}).run(workflow)
    assert result.success is True
    assert agent.requests[1].resume_session_id == "session-1"


def test_yaml_step_level_agent_shorthand_is_supported():
    workflow = load_yaml("""
steps:
  - id: evaluate
    agent: codex
    task: evaluate evidence
    new_session: true
""")
    step = workflow.steps[0]
    assert step.run == AgentAction(agent="codex", task="evaluate evidence", new_session=True)


def test_yaml_recovery_policy_parses_allowed_actions_and_bounds():
    workflow = load_yaml("""
steps:
  - id: launch
    run: launch
    check: ready
    on_failure:
      agent: claude
      task: repair launch
      allow: [retry, take_over]
      max_attempts: 3
      takeover_task: finish launch yourself
""")
    policy = workflow.steps[0].on_failure
    assert policy is not None
    assert policy.max_attempts == 3
    assert policy.allow == (RecoveryAction.RETRY, RecoveryAction.TAKE_OVER)
    assert policy.takeover_task == "finish launch yourself"


def test_yaml_until_requires_a_bound():
    try:
        load_yaml("""
steps:
  - id: loop
    run: advance
    until: done
""")
    except ValueError as exc:
        assert "max_iterations" in str(exc)
    else:
        raise AssertionError("expected ValueError")

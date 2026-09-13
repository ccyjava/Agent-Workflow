from agent_workflow import AgentResponse, Runner, load_yaml


class DemoAgent:
    def __init__(self):
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        if request.kind == "recovery":
            request.context["ready"] = True
            return AgentResponse(
                success=True,
                data={"action": "retry"},
                session_id="recovery-session",
            )
        if request.kind == "run":
            request.context["played"] = True
            return AgentResponse(
                success=True,
                data={"result": "played"},
                session_id="game-session",
            )
        if request.kind == "check":
            return AgentResponse(
                success=True,
                data={"pass": bool(request.context.get("played"))},
                session_id="game-session",
            )
        raise AssertionError(request.kind)


def test_yaml_end_to_end_code_recovery_agent_step_and_agent_check():
    workflow = load_yaml("""
name: demo
steps:
  - id: launch
    run: launch
    check: ready
    on_failure:
      agent: claude
      session: launch-recovery
      max_attempts: 2
      allow: [retry, abort]

  - id: play
    run:
      agent: claude
      task: play game
      session: gameplay
    check:
      agent: claude
      task: verify game objective
      session: gameplay

  - id: save
    run: save
""")

    def launch(ctx):
        ctx["launch_calls"] = ctx.get("launch_calls", 0) + 1
        return "started"

    def ready(ctx, result):
        return ctx.get("ready", False)

    def save(ctx):
        ctx["saved"] = True
        return "saved"

    agent = DemoAgent()
    result = Runner(
        functions={"launch": launch, "ready": ready, "save": save},
        agents={"claude": agent},
    ).run(workflow)

    assert result.success is True
    assert result.context == {
        "launch_calls": 2,
        "ready": True,
        "played": True,
        "saved": True,
    }
    assert [r.kind for r in agent.requests] == ["recovery", "run", "check"]
    assert agent.requests[2].resume_session_id == "game-session"

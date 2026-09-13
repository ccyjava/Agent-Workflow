from agent_workflow import AgentResponse, RecoveryPolicy, Runner, Step, Workflow


class DemoRecoveryAgent:
    def run(self, request):
        if request.kind == "recovery":
            request.context["ready"] = True
            return AgentResponse(success=True, data={"action": "retry"}, session_id="demo-recovery")
        raise RuntimeError(f"unexpected request: {request.kind}")


def launch(ctx):
    ctx["launch_calls"] = ctx.get("launch_calls", 0) + 1
    return "started"


def ready(ctx, result):
    return ctx.get("ready", False)


workflow = Workflow([
    Step(
        "launch",
        run=launch,
        check=ready,
        on_failure=RecoveryPolicy(agent="demo", max_attempts=2),
    )
])

result = Runner(agents={"demo": DemoRecoveryAgent()}).run(workflow)
print({"success": result.success, "context": result.context})

from pathlib import Path

from agent_workflow import Runner, load_yaml


def increment(ctx):
    ctx["count"] = ctx.get("count", 0) + 1
    return ctx["count"]


def positive(ctx, result):
    return result > 0


workflow = load_yaml(Path(__file__).with_name("workflow.yaml"))
result = Runner(functions={"increment": increment, "positive": positive}).run(workflow)
print({"success": result.success, "context": result.context})

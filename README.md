# Agent Workflow

A small Python runtime for workflows that mix **deterministic code** with **agent intelligence**.

The idea is simple:

```text
Workflow owns control.
Code handles deterministic work.
Agents handle uncertainty.
```

Instead of giving an agent a large Markdown workflow and asking it to remember and execute everything, make the workflow executable and call an agent only at the places that actually need reasoning, judgment, adaptation, or recovery.

## Core model

Every step can have three things:

```text
run -> check -> on_failure
```

- `run`: Python function or agent task
- `check`: Python checker or agent checker
- `on_failure`: optional agent recovery policy

Recovery agents can choose:

- `retry` — repair the environment/code, then rerun the original step
- `take_over` — let the agent complete the step directly
- `abort` — stop the workflow

Loops stay bounded with `repeat` or `until + max_iterations`.

## Architecture

```text
            Workflow
               |
               v
             Runner
               |
       +-------+-------+
       |               |
      Code            Agent
       |               |
       +-------+-------+
               |
             Check
               |
        Pass / Recover
               |
            Next Step
```

The runner is intentionally thin. There is no DAG engine, scheduler, database, vector store, or agent framework in v1.

## Install

```bash
pip install -e .
```

For real agent calls, install and authenticate the CLI you want to use separately:

- Claude Code (`claude`)
- OpenAI Codex CLI (`codex`)

## Python workflow

Python and YAML are two authoring forms for the same runtime model.

```python
from agent_workflow import (
    AgentAction,
    ClaudeCodeAgent,
    CodexAgent,
    RecoveryAction,
    RecoveryPolicy,
    Runner,
    Step,
    Workflow,
)


def launch_game(ctx):
    ctx["process_started"] = True
    return "started"


def game_ready(ctx, result):
    return ctx.get("process_started", False)


def capture_evidence(ctx):
    return {"screenshot": "result.png"}


workflow = Workflow([
    Step(
        "launch",
        run=launch_game,
        check=game_ready,
        on_failure=RecoveryPolicy(
            agent="claude",
            session="launch-recovery",
            max_attempts=2,
        ),
    ),
    Step(
        "play",
        run=AgentAction(
            agent="claude",
            task="Complete the gameplay objective.",
            session="gameplay",
        ),
        check=AgentAction(
            agent="claude",
            task="Verify that the gameplay objective is complete.",
            session="gameplay",
        ),
    ),
    Step("evidence", run=capture_evidence),
    Step(
        "evaluate",
        run=AgentAction(
            agent="codex",
            task="Independently evaluate the collected evidence.",
            new_session=True,
        ),
    ),
])

runner = Runner(
    agents={
        "claude": ClaudeCodeAgent(cwd="."),
        "codex": CodexAgent(cwd="."),
    }
)

result = runner.run(workflow)
print(result.success)
```

A code step can also be referenced by string when you want the same workflow shape as YAML:

```python
runner = Runner(functions={
    "launch_game": launch_game,
    "game_ready": game_ready,
})

workflow = Workflow([
    Step("launch", run="launch_game", check="game_ready"),
])
```

## Equivalent YAML

```yaml
name: gameplay-evaluation

steps:
  - id: launch
    run: launch_game
    check: game_ready
    on_failure:
      agent: claude
      session: launch-recovery
      max_attempts: 2
      allow: [retry, take_over, abort]

  - id: play
    run:
      agent: claude
      task: Complete the gameplay objective.
      session: gameplay
    check:
      agent: claude
      task: Verify that the gameplay objective is complete.
      session: gameplay

  - id: evidence
    run: capture_evidence

  - id: evaluate
    agent: codex
    task: Independently evaluate the collected evidence.
    new_session: true
```

Load it with the same runner:

```python
from agent_workflow import Runner, load_yaml

workflow = load_yaml("workflow.yaml")
result = Runner(
    functions={
        "launch_game": launch_game,
        "game_ready": game_ready,
        "capture_evidence": capture_evidence,
    },
    agents={"claude": claude, "codex": codex},
).run(workflow)
```

## Failure -> agent recovery

A deterministic step can fail either because execution raises an exception or because its check returns false.

```python
Step(
    "launch",
    run=launch_game,
    check=game_ready,
    on_failure=RecoveryPolicy(
        agent="claude",
        allow=(
            RecoveryAction.RETRY,
            RecoveryAction.TAKE_OVER,
            RecoveryAction.ABORT,
        ),
        max_attempts=3,
    ),
)
```

The recovery loop is:

```text
code step
   |
 check
 /   \
PASS FAIL
 |     |
next  agent recovery
      /    |      \
   retry takeover abort
     |      |
     +------+----> check again
```

Only `retry` reruns the original code. `take_over` asks the agent to complete the step directly, then validates the result again.

## Loops

Fixed repetition:

```python
Step("sample", run=collect_sample, repeat=5)
```

Condition loop:

```python
Step(
    "solve",
    run=AgentAction("claude", "Make progress toward the goal", session="solve"),
    until=AgentAction("claude", "Is the goal complete?", session="solve"),
    max_iterations=5,
)
```

YAML:

```yaml
- id: solve
  run:
    agent: claude
    task: Make progress toward the goal
    session: solve
  until:
    agent: claude
    task: Is the goal complete?
    session: solve
  max_iterations: 5
```

All loops are bounded.

## Sessions

Named sessions preserve continuity inside one coherent agent task:

```python
AgentAction(
    agent="claude",
    task="Continue the gameplay task",
    session="gameplay",
)
```

When the provider returns a session/thread id, the runner stores it under `(provider, session)` and explicitly resumes it on the next call.

Use `new_session=True` when responsibility should be isolated, such as an independent evaluator.

## Claude Code adapter

The adapter uses non-interactive print mode and JSON output:

```text
claude -p <prompt> --output-format json
claude -p <prompt> --output-format json --resume <session-id>
```

Extra CLI flags can be supplied with `extra_args`.

## Codex adapter

The adapter uses JSONL `exec` mode:

```text
codex exec --json <prompt>
codex exec --json resume <thread-id> <prompt>
```

Extra CLI flags can be supplied with `extra_args`.

## What belongs in code vs an agent?

A useful default:

**Code**
- launch / stop
- wait / retry
- API calls
- file operations
- known checks
- logging
- known recovery

**Agent**
- reasoning
- UI understanding
- open-ended tasks
- semantic evaluation
- unknown failures
- adaptive recovery

If an agent solution repeats often enough, turn it into code.

## Development

```bash
python -m pytest
python -m compileall -q src
```

See `examples/` for fully local examples that use fake agents, so the workflow mechanics can be tested without provider credentials.

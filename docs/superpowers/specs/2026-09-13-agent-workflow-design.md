# Agent Workflow Design

## Goal
Build a small Python workflow runtime that keeps deterministic control flow in code while calling agents only where reasoning, validation, or recovery is needed.

## Core model
A workflow is an ordered set of `Step`s. Each step has:
- `run`: a Python/code action or an agent action.
- `check`: optional code/agent validation of the run result.
- `on_failure`: optional agent recovery policy that may return `retry`, `take_over`, or `abort`.
- looping: exact `repeat`, or `until` with a required bound.

The runner is intentionally thin: `run -> check -> recover -> repeat/next`.

## Two equivalent authoring forms
- Python: construct `Workflow` / `Step` objects directly and pass Python callables or agent actions.
- YAML: declare the same model; string code actions resolve through a function registry.

Both normalize to the same runtime objects. YAML is optional and is not a second engine.

## Agent interface
Provide one `Agent` protocol and two subprocess adapters:
- Claude Code: `claude -p ... --output-format json`, with explicit `--resume <session_id>` when resuming.
- Codex CLI: `codex exec --json ...`, with `codex exec resume <session_id> --json ...` when resuming.

Agent sessions may be named. The runtime remembers a provider session id per named session and reuses it across calls. `new_session: true` bypasses stored session state.

## Recovery semantics
A failed run (exception / unsuccessful agent call) or failed check may invoke recovery.
The recovery agent returns one of:
- `retry`: the agent may repair environment/code, then the original step runs again.
- `take_over`: the runner asks the agent to complete the current step; the result is checked again.
- `abort`: stop the workflow.

Recovery is bounded by `max_attempts`.

## Loop semantics
- `repeat: N`: execute the full step N times.
- `until: <checker>` + `max_iterations: N`: execute until the condition passes or the bound is reached.

Agent actions and agent checkers work inside loops exactly like code actions/checkers.

## Non-goals for v1
No DAG scheduler, distributed execution, persistence database, vector database, plugin marketplace, background workers, or dynamic code generation framework.

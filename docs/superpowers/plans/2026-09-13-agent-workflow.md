# Agent Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build and verify a compact Python package for deterministic workflows with agent steps, agent checks, bounded loops, and agent-assisted recovery, authored in Python or YAML.

**Architecture:** `Workflow` contains `Step`s. `Runner` executes each step via a unified action resolver, validates results, applies optional recovery decisions, and controls bounded repetition. Claude Code and Codex are adapters behind a shared `Agent` interface; YAML only parses into the same Python model.

**Tech Stack:** Python 3.10+, stdlib (`dataclasses`, `subprocess`, `json`), optional PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-agent-workflow-design.md`

## Global Constraints
- Keep the runner small and provider-agnostic.
- Python and YAML normalize to the same model.
- All retries and loops are bounded.
- No production code before its behavior has a failing test.
- Claude Code and Codex support explicit session resume.

---

### Task 1: Core model and runner
**Files:** `tests/test_runner.py`, `src/agent_workflow/model.py`, `src/agent_workflow/runner.py`, `src/agent_workflow/__init__.py`

**Interfaces:**
- Produces `Workflow`, `Step`, `AgentAction`, `RecoveryPolicy`, `RecoveryAction`, `RunResult`, `Runner`.
- `Runner.run(workflow, context=None) -> WorkflowResult`.

- [x] Write failing tests for code step success, check failure, bounded retry, take-over, abort, repeat, and until.
- [x] Run tests and confirm they fail because runtime is absent.
- [x] Implement the minimal model and runner.
- [x] Run tests and make them pass.

### Task 2: Agent protocol and subprocess adapters
**Files:** `tests/test_agents.py`, `src/agent_workflow/agents.py`

**Interfaces:**
- Produces `AgentRequest`, `AgentResponse`, `Agent` protocol, `ClaudeCodeAgent`, `CodexAgent`.
- Named runtime sessions resume with provider session ids.

- [x] Write failing tests for command construction, JSON parsing, session extraction, and explicit resume for both providers.
- [x] Run tests and confirm expected failures.
- [x] Implement adapters using injected subprocess runner for testability.
- [x] Run tests and make them pass.

### Task 3: YAML normalization
**Files:** `tests/test_yaml.py`, `src/agent_workflow/yaml_loader.py`

**Interfaces:**
- Produces `load_yaml(text_or_path) -> Workflow`.
- YAML code action names are resolved by `Runner` from a function registry.

- [x] Write failing tests showing YAML and Python produce equivalent runtime behavior.
- [x] Run tests and confirm expected failures.
- [x] Implement minimal YAML parsing and validation.
- [x] Run tests and make them pass.

### Task 4: Public API, examples, package metadata
**Files:** `README.md`, `pyproject.toml`, `examples/python_workflow.py`, `examples/workflow.yaml`, `examples/yaml_workflow.py`

**Interfaces:**
- `pip install -e .` installs the package.
- README documents Python/YAML parity and Claude/Codex usage.

- [x] Add packaging and runnable examples.
- [x] Run examples with fake agents / local functions.
- [x] Run full test suite.
- [x] Run compile/import smoke checks.
- [x] Commit the verified repository.

import json
import subprocess

from agent_workflow import AgentRequest
from agent_workflow.agents import ClaudeCodeAgent, CodexAgent


class FakeProcessRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, cmd, *, cwd=None):
        self.calls.append((cmd, cwd))
        stdout, returncode = self.outputs.pop(0)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="boom" if returncode else "")


def request(**kwargs):
    defaults = dict(kind="run", task="do the thing", context={"x": 1})
    defaults.update(kwargs)
    return AgentRequest(**defaults)


def test_claude_code_builds_print_json_command_and_parses_session_and_model_json():
    outer = {
        "type": "result",
        "is_error": False,
        "result": '{"success": true, "result": "done"}',
        "session_id": "claude-session-1",
    }
    proc = FakeProcessRunner([(json.dumps(outer), 0)])
    agent = ClaudeCodeAgent(process_runner=proc, cwd="/work")

    response = agent.run(request())

    cmd, cwd = proc.calls[0]
    assert cmd[:2] == ["claude", "-p"]
    assert "--output-format" in cmd and "json" in cmd
    assert "do the thing" in cmd[2]
    assert cwd == "/work"
    assert response.success is True
    assert response.session_id == "claude-session-1"
    assert response.data["result"] == "done"


def test_claude_code_resume_uses_explicit_session_id():
    outer = {"is_error": False, "result": "ok", "session_id": "s-1"}
    proc = FakeProcessRunner([(json.dumps(outer), 0)])
    agent = ClaudeCodeAgent(process_runner=proc)

    agent.run(request(resume_session_id="s-1"))

    cmd = proc.calls[0][0]
    assert "--resume" in cmd
    assert cmd[cmd.index("--resume") + 1] == "s-1"


def test_claude_code_nonzero_exit_is_failure():
    proc = FakeProcessRunner([("", 2)])
    response = ClaudeCodeAgent(process_runner=proc).run(request())
    assert response.success is False
    assert "boom" in response.error


def test_codex_exec_parses_jsonl_thread_and_agent_message():
    stdout = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-9"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": '{"pass": true}'}}),
        json.dumps({"type": "turn.completed"}),
    ])
    proc = FakeProcessRunner([(stdout, 0)])
    agent = CodexAgent(process_runner=proc, cwd="/repo")

    response = agent.run(request(kind="check"))

    cmd, cwd = proc.calls[0]
    assert cmd[:3] == ["codex", "exec", "--json"]
    assert "do the thing" in cmd[-1]
    assert cwd == "/repo"
    assert response.success is True
    assert response.session_id == "thread-9"
    assert response.data["pass"] is True


def test_codex_resume_uses_exec_resume_with_explicit_thread_id():
    stdout = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-9"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "continued"}}),
    ])
    proc = FakeProcessRunner([(stdout, 0)])
    agent = CodexAgent(process_runner=proc)

    agent.run(request(resume_session_id="thread-9"))

    cmd = proc.calls[0][0]
    assert cmd[:3] == ["codex", "exec", "--json"]
    assert cmd[3:5] == ["resume", "thread-9"]


def test_recovery_prompt_requires_machine_readable_action():
    stdout = json.dumps({
        "is_error": False,
        "result": '{"action":"retry","reason":"fixed"}',
        "session_id": "s",
    })
    proc = FakeProcessRunner([(stdout, 0)])
    agent = ClaudeCodeAgent(process_runner=proc)

    response = agent.run(request(kind="recovery", error="not ready"))

    prompt = proc.calls[0][0][2]
    assert "retry" in prompt and "take_over" in prompt and "abort" in prompt
    assert response.data["action"] == "retry"

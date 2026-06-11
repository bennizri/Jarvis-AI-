import json

from jarvis.config import CONFIG
from jarvis.dispatch import SPOKEN_TAG, build_cmd, extract_spoken, parse_line


def test_build_cmd_default_profile_uses_allowed_tools():
    cmd = build_cmd("list files")
    assert cmd[0] == "claude"
    assert cmd[1] == "-p"
    assert "list files" in cmd[2]
    assert SPOKEN_TAG in cmd[2]  # spoken-summary instruction appended
    assert "--output-format" in cmd and "stream-json" in cmd
    assert "--allowedTools" in cmd
    assert "--dangerously-skip-permissions" not in cmd


def test_build_cmd_yolo_profile():
    CONFIG.permission_profile = "yolo"
    try:
        assert "--dangerously-skip-permissions" in build_cmd("x")
    finally:
        CONFIG.permission_profile = "default"


def test_parse_line_tool_use():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}]}})
    assert parse_line(line) == [{"kind": "tool", "name": "Bash", "detail": "ls -la"}]


def test_parse_line_text_block():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "checking files"}]}})
    assert parse_line(line) == [{"kind": "text", "text": "checking files"}]


def test_parse_line_result():
    line = json.dumps({"type": "result", "subtype": "success", "result": "done",
                       "session_id": "s-123"})
    assert parse_line(line) == [{"kind": "result", "ok": True, "text": "done",
                                 "session": "s-123"}]


def test_build_cmd_resume_session():
    cmd = build_cmd("continue", session_id="s-123")
    i = cmd.index("--resume")
    assert cmd[i + 1] == "s-123"


def test_build_cmd_no_resume_without_session():
    assert "--resume" not in build_cmd("x")


def test_parse_line_garbage_and_irrelevant():
    assert parse_line("not json{") == []
    assert parse_line(json.dumps({"type": "system", "subtype": "init"})) == []


def test_extract_spoken():
    text = "Did the thing.\nDetails here.\nSPOKEN: All done, three files changed."
    clean, spoken = extract_spoken(text)
    assert spoken == "All done, three files changed."
    assert "SPOKEN:" not in clean
    assert "Details here." in clean


def test_extract_spoken_missing():
    clean, spoken = extract_spoken("no tag here")
    assert clean == "no tag here" and spoken == ""


def test_build_cmd_model_flag():
    cmd = build_cmd("hi", model="haiku")
    i = cmd.index("--model")
    assert cmd[i + 1] == "haiku"
    assert "--model" not in build_cmd("hi")


def test_run_task_on_proc_callback(monkeypatch):
    import jarvis.dispatch as d

    class FakeProc:
        stdout = iter(())
        stderr = None
        returncode = 0
        def wait(self):
            return 0

    captured = []
    monkeypatch.setattr(d.subprocess, "Popen", lambda *a, **k: FakeProc())
    d.run_task("x", on_proc=captured.append)
    assert isinstance(captured[0], FakeProc)

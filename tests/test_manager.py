from jarvis.manager import AgentManager


def test_local_task_lifecycle():
    m = AgentManager()
    m.local_started("t1", "create hello.txt")
    assert m.snapshot()[0]["status"] == "running"
    m.local_finished("t1", ok=True, summary="done")
    snap = m.snapshot()[0]
    assert snap["status"] == "done" and snap["kind"] == "local"


def test_cloud_merge_and_attention_on_fail():
    m = AgentManager()
    m.cloud_update([{"id": "trig_1", "name": "HIApply daily agent",
                     "enabled": True, "next_run_at": "2026-06-12T06:23:00Z",
                     "purpose": "daily review"}])
    m.report_update([{"msg_id": "m1", "agent": "HIApply daily agent",
                      "status": "FAIL", "summary": "repo denied"}])
    snap = {a["id"]: a for a in m.snapshot()}
    assert snap["trig_1"]["status"] == "needs_attention"
    assert snap["trig_1"]["last_report"] == "repo denied"


def test_ok_report_clears_attention():
    m = AgentManager()
    m.cloud_update([{"id": "trig_1", "name": "A", "enabled": True}])
    m.report_update([{"msg_id": "m1", "agent": "A", "status": "FAIL", "summary": "x"}])
    m.report_update([{"msg_id": "m2", "agent": "A", "status": "OK", "summary": "fine"}])
    assert m.snapshot()[0]["status"] == "scheduled"


def test_attention_list():
    m = AgentManager()
    m.cloud_update([{"id": "t1", "name": "A", "enabled": True},
                    {"id": "t2", "name": "B", "enabled": True}])
    m.report_update([{"msg_id": "m1", "agent": "B", "status": "FAIL", "summary": "x"}])
    assert [a["name"] for a in m.attention()] == ["B"]

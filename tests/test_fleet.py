from jarvis.fleet import merge_registry


def test_merge_adds_purpose_from_registry():
    agents = [{"id": "trig_1", "name": "A", "enabled": True,
               "cron": "0 9 * * *", "next_run_at": ""}]
    registry = {"trig_1": {"purpose": "daily code review", "repo": "org/x"}}
    merged = merge_registry(agents, registry)
    assert merged[0]["purpose"] == "daily code review"


def test_merge_unknown_agent_gets_empty_purpose():
    agents = [{"id": "trig_2", "name": "B"}]
    assert merge_registry(agents, {})[0]["purpose"] == ""


def test_merge_handles_missing_id():
    agents = [{"name": "no-id"}]
    assert merge_registry(agents, {"x": {"purpose": "p"}})[0]["purpose"] == ""

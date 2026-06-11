import json

from jarvis.digest import compose_digest


def test_compose_counts_and_failures():
    fleet_msg = json.dumps({"type": "fleet", "agents": [
        {"name": "A", "enabled": True}, {"name": "B", "enabled": False}]})
    reports_msg = json.dumps({"type": "reports", "reports": [
        {"agent": "A", "status": "FAIL", "summary": "boom"},
        {"agent": "A", "status": "OK", "summary": "fine"}]})
    text = compose_digest(fleet_msg, reports_msg)
    assert "2 agents" in text and "1 disabled" in text and "A failed" in text


def test_compose_no_data():
    assert compose_digest(None, None) == ""

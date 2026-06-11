import json

from jarvis.cli import parse_json_array


def wrap(result: str) -> str:
    return json.dumps({"type": "result", "result": result})


def test_parse_plain_array():
    items = [{"a": 1}]
    assert parse_json_array(wrap(json.dumps(items))) == items


def test_parse_fenced_array():
    items = [{"a": 1}]
    fenced = "```json\n" + json.dumps(items) + "\n```"
    assert parse_json_array(wrap(fenced)) == items


def test_parse_empty():
    assert parse_json_array(wrap("[]")) == []


def test_parse_garbage_returns_none():
    assert parse_json_array("not json") is None
    assert parse_json_array(wrap("sorry, no tool")) is None
    assert parse_json_array(wrap('{"not": "list"}')) is None

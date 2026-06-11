from jarvis.reports import diff_new

OLD = [{"agent": "hiapply", "status": "OK", "summary": "all good",
        "msg_id": "m1"}]


def test_diff_new_returns_only_unseen():
    new = OLD + [{"agent": "leads", "status": "FAIL", "summary": "crash",
                  "msg_id": "m2"}]
    fresh = diff_new(new, {"m1"})
    assert [r["msg_id"] for r in fresh] == ["m2"]


def test_diff_new_handles_missing_msg_id():
    fresh = diff_new([{"agent": "x", "status": "OK", "summary": ""}], set())
    assert fresh == []  # no msg_id -> can't dedupe -> drop


def test_diff_new_empty():
    assert diff_new([], {"m1"}) == []

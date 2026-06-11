from jarvis.quality import accept


def test_wake_accepts_decent_confidence():
    assert accept("did you finish the task", conf=0.5, woke=True)
    assert accept("hello", conf=0.3, woke=True)


def test_wake_rejects_pure_noise():
    assert not accept("Aí me está me vindo a ti", conf=0.08, woke=True)
    assert not accept("", conf=0.9, woke=True)


def test_followup_moderate_bar():
    assert accept("did you finish the task for high apply", conf=0.4, woke=False)
    assert not accept("you", conf=0.9, woke=False)            # too short
    assert not accept("so anyway whatever then", conf=0.15, woke=False)  # noise

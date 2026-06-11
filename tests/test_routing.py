from jarvis.routing import classify


def test_short_question_is_chat():
    assert classify("what time is it") == "chat"
    assert classify("מה השעה") == "chat"
    assert classify("do you hear me") == "chat"


def test_action_verbs_are_work():
    assert classify("create a file called hello.txt") == "work"
    assert classify("תריץ את הטסטים בפרויקט") == "work"
    assert classify("test the high apply project") == "work"
    assert classify("fix the login bug") == "work"


def test_long_sentences_are_work():
    long_q = "can you walk me through everything that changed in the project " \
             "this week and what is still left to finish"
    assert classify(long_q) == "work"

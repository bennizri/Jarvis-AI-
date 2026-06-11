ACTION_WORDS = {
    # en
    "create", "make", "build", "fix", "run", "test", "deploy", "install",
    "delete", "rename", "search", "send", "open", "write", "update", "refactor",
    "check", "review", "start", "stop", "pause", "schedule", "monitor",
    # he
    "תיצור", "תבנה", "תתקן", "תריץ", "תבדוק", "תתקין", "תמחק", "תחפש",
    "תשלח", "תפתח", "תכתוב", "תעדכן", "תעצור", "צור", "בנה", "תקן", "הרץ",
}

MAX_CHAT_WORDS = 9


def classify(text: str) -> str:
    """'chat' -> quick conversational answer, 'work' -> real task."""
    words = text.lower().replace("?", "").replace(".", "").split()
    if len(words) > MAX_CHAT_WORDS:
        return "work"
    if any(w in ACTION_WORDS for w in words):
        return "work"
    return "chat"

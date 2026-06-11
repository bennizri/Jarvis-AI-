MIN_WAKE_CONF = 0.12        # explicit wake = strong intent, low bar
MIN_FOLLOWUP_CONF = 0.30    # mic opened on our initiative, higher bar
MIN_FOLLOWUP_WORDS = 3


def accept(text: str, conf: float, woke: bool) -> bool:
    """Is this transcription a command the user actually meant?

    conf is transcription quality (mean token prob × no-speech damping) from
    Transcriber.transcribe — NOT language certainty, which punishes accents.
    """
    if not text.strip():
        return False
    if woke:
        return conf >= MIN_WAKE_CONF
    return len(text.split()) >= MIN_FOLLOWUP_WORDS and conf >= MIN_FOLLOWUP_CONF

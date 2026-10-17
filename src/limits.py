"""Per-session limits so a public demo cannot be abused or become costly."""

MAX_QUESTIONS_PER_SESSION = 20
MAX_QUESTION_CHARS = 500


def check_question(question: str, questions_asked: int) -> str | None:
    """Return a message explaining why the question is refused, or None if it is allowed."""
    if questions_asked >= MAX_QUESTIONS_PER_SESSION:
        return f"Session limit reached ({MAX_QUESTIONS_PER_SESSION} questions). Reset the conversation to continue."
    if len(question) > MAX_QUESTION_CHARS:
        return f"Question too long ({len(question)} characters, max {MAX_QUESTION_CHARS})."
    return None

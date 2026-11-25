import re
from src.config import DEFAULT_SEARCH_PHRASE


def parse_search_phrase(raw_phrase: str | None) -> str:
    """Validate and normalize the user's input phrase."""
    phrase = (raw_phrase or DEFAULT_SEARCH_PHRASE).strip()
    phrase = re.sub(r"\s+", " ", phrase)
    if not phrase:
        raise ValueError("Search phrase cannot be empty.")
    return phrase
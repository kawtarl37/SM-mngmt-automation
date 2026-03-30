import re
from execution.db import get_connection

def normalize_title(title: str) -> str:
    """Strip adjectives, lowercase, and remove filler words to normalize a title."""
    stop_words = {"best", "easy", "simple", "fluffy", "perfect", "quick", "the", "a", "an", "how", "to", "make"}
    words = title.lower().replace("-", " ").replace("|", " ").split()
    words = [re.sub(r'[^a-z0-9]', '', w) for w in words]
    return " ".join(w for w in words if w and w not in stop_words)

def get_existing_recipes() -> list:
    """Fetch all normalized existing recipe titles from the DB."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT title, title_normalized FROM recipes")
        return [dict(row) for row in cursor.fetchall()]

def is_duplicate(new_title: str, existing_normalized_titles: set) -> bool:
    """
    Check if a proposed title is a semantic duplicate of an existing one.
    Layer 1 check: Normalized Title Match
    """
    norm_new = normalize_title(new_title)
    return norm_new in existing_normalized_titles

def get_existing_recipes_formatted(limit: int = 100) -> str:
    """Return a formatted string of existing titles for the LLM context."""
    recipes = get_existing_recipes()
    # Sort and take latest/most relevant or just a random sample if too large
    # For now, just return all titles joined by newline (up to limit)
    titles = [r['title'] for r in recipes[:limit]]
    return "\n".join(f"- {t}" for t in titles)

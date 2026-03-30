from datetime import datetime, timezone
import dateutil.parser
from execution.db import get_connection
from execution.utils.logger import setup_logger

logger = setup_logger("trend_analyzer")

# General gluten-free keywords to boost relevance
GF_KEYWORDS = {
    "gluten free", "gluten-free", "gf", "celiac", "coeliac", 
    "wheat free", "dairy free", "rice flour", "almond flour", 
    "tapioca", "xanthan gum", "oat flour", "baking", "sourdough",
    "bread", "pasta", "pizza", "substitute", "alternative"
}

def parse_date(date_str: str) -> datetime:
    """Parse SQLite timestamp into timezone-aware datetime."""
    dt = dateutil.parser.isoparse(date_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def compute_relevance(title: str, body: str, score: int, comment_count: int, fetched_at_str: str) -> float:
    """Calculate the relevance score for a public trend topic (0.0 to 1.0)."""
    text = f"{title} {body}".lower()
    
    # 1. Keyword match (max 0.4)
    hits = sum(1 for kw in GF_KEYWORDS if kw in text)
    keyword_score = min(hits / 5.0, 1.0) * 0.4
    
    # 2. Engagement signal (max 0.3)
    engagement = min(score / 500.0, 1.0) * 0.3
    
    # 3. Recency bonus (max 0.2)
    now = datetime.now(timezone.utc)
    try:
        fetched_at = parse_date(fetched_at_str)
        hours_old = (now - fetched_at).total_seconds() / 3600.0
        recency = max(0.0, 1.0 - (hours_old / 72.0)) * 0.2
    except Exception:
        recency = 0.1 # default fallback
        
    # 4. Comment depth (max 0.1)
    comment_score = min(comment_count / 50.0, 1.0) * 0.1
    
    return keyword_score + engagement + recency + comment_score

def rank_trends():
    """Score all unprocessed trends and keep the top ones for the LLM prompt."""
    logger.info("Ranking imported trend topics...")
    
    updates = []
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Get topics that haven't been scored yet (relevance = 0.0)
        cursor.execute("SELECT topic_id, title, body, score, comment_count, fetched_at FROM trend_topics WHERE relevance = 0.0")
        rows = cursor.fetchall()
        
        for row in rows:
            rel_score = compute_relevance(
                row["title"], 
                row["body"] or "", 
                row["score"], 
                row["comment_count"], 
                row["fetched_at"]
            )
            updates.append((rel_score, row["topic_id"]))
            
        if updates:
            cursor.executemany("UPDATE trend_topics SET relevance = ? WHERE topic_id = ?", updates)
            conn.commit()
            
    logger.info(f"Ranked {len(updates)} topics.")

def get_top_trends(limit: int = 10) -> list:
    """Return the top N most relevant trends to feed into the idea generator."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title, score, relevance FROM trend_topics ORDER BY relevance DESC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

if __name__ == "__main__":
    rank_trends()
    top = get_top_trends(3)
    for t in top:
        print(f"[{t['relevance']:.2f}] {t['title']} (Score: {t['score']})")

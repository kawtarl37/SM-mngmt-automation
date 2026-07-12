from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from execution.config import DAILY_PIN_COUNT
from execution.db import get_connection
from execution.utils.logger import setup_logger
from execution.intelligence.duplication_checker import get_existing_recipes, is_duplicate
from execution.editorial.memory import get_recent_topic_memory
from execution.editorial.schema import ensure_editorial_schema
from execution.editorial.scoring import EditorialScorer
from execution.editorial.taxonomy import classify_lane

logger = setup_logger("idea_scorer")

def score_and_select_ideas():
    """Score all unselected ideas, discard duplicates, and select the top 3."""
    logger.info("Starting idea scoring and selection...")
    ensure_editorial_schema()
    batch_date = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Fetch unselected ideas for today
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT idea_id, title, description, content_type, content_lane,
                      angle_type, freshness_hook, source_hint
               FROM content_ideas
               WHERE batch_date = ? AND selected = FALSE""",
            (batch_date,)
        )
        ideas = [dict(row) for row in cursor.fetchall()]

    if not ideas:
        logger.error(f"No unselected ideas exist for {batch_date}.")
        return

    # 2. Get existing recipes for duplication and novelty comparison
    existing = get_existing_recipes()
    existing_normalized = {r["title_normalized"] for r in existing}
    existing_titles = [r["title"] for r in existing]
    
    # Use TF-IDF for novelty comparison (cosine distance against all existing titles)
    vectorizer = TfidfVectorizer(stop_words='english')
    # Fit on both existing and idea titles to ensure vocabulary matches
    all_docs = existing_titles + [i["title"] for i in ideas]
    
    try:
        tfidf_matrix = vectorizer.fit_transform(all_docs)
        existing_matrix = tfidf_matrix[:len(existing_titles)]
        idea_matrix = tfidf_matrix[len(existing_titles):]
    except ValueError:
        # Fallback if corpus is empty
        existing_matrix = None
        idea_matrix = None

    updates = []
    scored_ideas = []
    editorial_scorer = EditorialScorer(memory=get_recent_topic_memory(limit=150))
    
    # 3. Score each idea
    for idx, idea in enumerate(ideas):
        title = idea["title"]
        description = idea["description"] or ""
        content_lane = idea["content_lane"] or classify_lane(f"{title} {description}")
        
        # Layer 1 Deduplication filter
        if is_duplicate(title, existing_normalized):
            logger.info(f"Discarding duplicate idea: {title}")
            # Score it very low 
            updates.append((0.0, 0.0, 0.0, 0.0, 0.0, False, idea["idea_id"]))
            continue
            
        # Novelty (Max 1.0) -> Inverse of max cosine similarity to existing
        novelty_score = 1.0
        if existing_matrix is not None and existing_matrix.shape[0] > 0:
            similarities = cosine_similarity(idea_matrix[idx], existing_matrix)
            max_sim = similarities[0].max() if similarities.size > 0 else 0.0
            novelty_score = max(0.0, 1.0 - float(max_sim))

        editorial_score = editorial_scorer.score(
            title=title,
            details=f"{description} {idea.get('freshness_hook') or ''}",
            requested_lane=content_lane,
        )
        novelty_score = min(novelty_score, editorial_score.novelty)
            
        # SEO Potential (Max 1.0) -> Basic keyword presence
        seo_keywords = [
            "best",
            "compare",
            "review",
            "new",
            "safe",
            "label",
            "restaurant",
            "app",
            "tool",
            "recipe",
            "gluten-free",
            "gluten free",
        ]
        seo_hits = sum(1 for kw in seo_keywords if kw in description.lower() or kw in title.lower())
        seo_score = min(seo_hits / 3.0, 1.0)
        
        # Engagement favors topics that are useful and conversation-worthy, not only recipes.
        engagement_score = min(
            1.0,
            (editorial_score.usefulness * 0.45)
            + (editorial_score.entertainment * 0.30)
            + (editorial_score.freshness * 0.25),
        )
        brand_score = editorial_score.lane_diversity
        
        # Weightings keep novelty and diversity from being drowned out by generic SEO.
        eng_w, nov_w, seo_w, brand_w = 0.24, 0.34, 0.18, 0.24
        total = (
            engagement_score * eng_w
            + novelty_score * nov_w
            + seo_score * seo_w
            + brand_score * brand_w
        )
        
        idea["total_score"] = total
        idea["content_lane"] = content_lane
        scored_ideas.append(idea)
        
        updates.append((
            engagement_score, novelty_score, seo_score, brand_score, total,
            False, # Not selected yet
            idea["idea_id"]
        ))

    # Update DB with scores
    if updates:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """UPDATE content_ideas 
                   SET engagement_score=?, novelty_score=?, seo_score=?, brand_score=?, total_score=?, selected=? 
                   WHERE idea_id=?""",
                updates
            )
            conn.commit()

    # 4. Select Top N ideas with lane diversity where possible
    top_ideas = _select_diverse_top_ideas(scored_ideas, DAILY_PIN_COUNT)
    
    top_ids = [i["idea_id"] for i in top_ideas]
    
    if top_ids:
        # Mark as selected and write stub records to generated_pins table
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Select ideas
            placeholders = ",".join("?" * len(top_ids))
            cursor.execute(f"UPDATE content_ideas SET selected = TRUE WHERE idea_id IN ({placeholders})", top_ids)
            
            # Insert into generated_pins (so caption generator can pick them up)
            for idea in top_ideas:
                cursor.execute(
                    """INSERT INTO generated_pins (idea_id, title, description, batch_date) 
                       VALUES (?, ?, ?, ?)""",
                    (idea["idea_id"], idea["title"], idea["description"], batch_date)
                )
                
            conn.commit()
            
        logger.info(f"Selected Top {len(top_ideas)} ideas for pinning.")
        
    return top_ideas


def _select_diverse_top_ideas(scored_ideas: list[dict], limit: int) -> list[dict]:
    """Pick high-scoring ideas while avoiding one lane taking every slot."""

    scored_ideas.sort(key=lambda x: x["total_score"], reverse=True)
    selected: list[dict] = []
    used_lanes: set[str] = set()

    for idea in scored_ideas:
        lane = idea.get("content_lane") or "unknown"
        if lane in used_lanes and len(used_lanes) < limit:
            continue
        selected.append(idea)
        used_lanes.add(lane)
        if len(selected) == limit:
            return selected

    selected_ids = {idea["idea_id"] for idea in selected}
    for idea in scored_ideas:
        if idea["idea_id"] in selected_ids:
            continue
        selected.append(idea)
        if len(selected) == limit:
            break

    return selected

if __name__ == "__main__":
    score_and_select_ideas()

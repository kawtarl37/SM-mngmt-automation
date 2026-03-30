import re
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from execution.config import DAILY_PIN_COUNT
from execution.db import get_connection
from execution.utils.logger import setup_logger
from execution.intelligence.duplication_checker import get_existing_recipes, normalize_title, is_duplicate

logger = setup_logger("idea_scorer")

def score_and_select_ideas():
    """Score all unselected ideas, discard duplicates, and select the top 3."""
    logger.info("Starting idea scoring and selection...")
    batch_date = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Fetch unselected ideas for today
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT idea_id, title, description, content_type FROM content_ideas WHERE batch_date = ? AND selected = FALSE",
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
    
    # 3. Score each idea
    for idx, idea in enumerate(ideas):
        title = idea["title"]
        
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
            
        # SEO Potential (Max 1.0) -> Basic keyword presence
        seo_keywords = ["easy", "quick", "best", "dinner", "breakfast", "bread", "pancakes"]
        seo_hits = sum(1 for kw in seo_keywords if kw in idea["description"].lower())
        seo_score = min(seo_hits / 3.0, 1.0)
        
        # Engagement & Brand (Max 1.0) -> Proxy scores (LLM did the heavy lifting here)
        # Content types generally perform differently
        engagement_score = 0.9 if idea["content_type"] == "recipe" else 0.7
        brand_score = 1.0 # Assuming LLM prompt enforced this
        
        # Weightings
        eng_w, nov_w, seo_w, brand_w = 0.30, 0.25, 0.25, 0.20
        total = (engagement_score * eng_w) + (novelty_score * nov_w) + (seo_score * seo_w) + (brand_score * brand_w)
        
        idea["total_score"] = total
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

    # 4. Select Top N ideas
    scored_ideas.sort(key=lambda x: x["total_score"], reverse=True)
    top_ideas = scored_ideas[:DAILY_PIN_COUNT]
    
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

if __name__ == "__main__":
    score_and_select_ideas()

import os
from datetime import datetime
from execution.config import PROMPTS_DIR
from execution.db import get_connection
from execution.models import TrendyTopicResponse
from execution.utils.llm_client import LLMClient
from execution.utils.logger import setup_logger

logger = setup_logger("trend_synthesizer")

def get_high_relevance_trends(limit: int = 25) -> list:
    """Fetch recent raw trends ordered by relevance score descending."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT source, subreddit, title, body, score, relevance 
               FROM trend_topics 
               WHERE relevance >= 0.1
               ORDER BY relevance DESC 
               LIMIT ?""",
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

def synthesize_trends() -> TrendyTopicResponse | None:
    """Analyze raw trends using the LLM and generate synthesized topics."""
    logger.info("Starting trend synthesis...")

    # 1. Gather raw trends
    raw_trends = get_high_relevance_trends()
    if not raw_trends:
        logger.warning("No raw trends found with sufficient relevance. Cannot synthesize.")
        return None

    # Format trends for the LLM prompt
    trends_list = []
    for t in raw_trends:
        source_info = f"Reddit r/{t['subreddit']}" if t['source'] == 'reddit' else f"PubMed ({t['subreddit']})"
        trends_list.append(
            f"- SOURCE: {source_info}\n"
            f"  TITLE: {t['title']}\n"
            f"  DETAILS: {t['body'][:300]}..."
        )
    trends_text = "\n\n".join(trends_list)

    # 2. Setup prompts
    try:
        system_prompt = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to load brand system prompt: {e}")
        system_prompt = "You are Claire Bennett, the voice of Easy Gluten Free."

    user_prompt = f"""
Here is a list of raw trending topics, discussions, and medical journal articles recently scraped from celiac/gluten-free spaces:

{trends_text}

---

As the trend analyst for Easy Gluten Free, your job is to read these raw inputs and synthesize them into 5 to 8 distinct, high-interest "Trendy Topics".
Each synthesized topic should represent a current talking point, concern, or discovery that we can write a blog post about.

Requirements for each topic:
1. Title: A short, catchy name for the topic (e.g. "Hidden Gluten in Shared Kitchen Air Fryers" or "Recent Findings on Oatmeal Safety in Celiac Patients").
2. Details: Write a detailed summary of what the discussions are about or what the study found. Write in Claire's voice (witty, relatable, conversational - e.g., acknowledging how exhausting it is to dodge gluten). Explain why readers care and give 1-2 quick pieces of advice. Keep this to 3-5 sentences.
3. Source: Cite the source clearly, e.g. "Reddit (r/celiac)" or "PubMed (Nutrients)".
4. Relevance Score: A score from 0.0 to 1.0 showing how relevant this is for EGF readers.

Please output the response in the requested structured JSON schema.
"""

    # 3. Call LLM
    client = LLMClient()
    try:
        response: TrendyTopicResponse = client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=TrendyTopicResponse,
            task_name="trend_synthesis"
        )
        
        # 4. Save to DB
        saved = save_synthesized_trends(response)
        logger.info(f"Synthesized and saved {saved} trendy topics.")
        return response
    except Exception as e:
        logger.error(f"Failed to synthesize trends: {e}", exc_info=True)
        return None

def save_synthesized_trends(response: TrendyTopicResponse) -> int:
    """Save synthesized trends to the database, ignoring duplicates by title."""
    saved_count = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        for topic in response.topics:
            # Check if this exact title already exists
            cursor.execute("SELECT 1 FROM trendy_topics WHERE title = ?", (topic.title,))
            if cursor.fetchone():
                continue
                
            cursor.execute(
                """INSERT INTO trendy_topics (title, details, source, relevance_score, status)
                   VALUES (?, ?, ?, ?, 'pending')""",
                (topic.title, topic.details, topic.source, topic.relevance_score)
            )
            saved_count += 1
        conn.commit()
    return saved_count

if __name__ == "__main__":
    synthesize_trends()

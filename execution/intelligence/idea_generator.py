from datetime import datetime
from execution.config import PROMPTS_DIR, DAILY_IDEA_GENERATION_COUNT
from execution.db import get_connection
from execution.models import IdeaGenerationResponse
from execution.utils.llm_client import LLMClient
from execution.utils.logger import setup_logger
from execution.intelligence.trend_analyzer import get_top_trends
from execution.intelligence.duplication_checker import get_existing_recipes_formatted

logger = setup_logger("idea_generator")

def generate_ideas() -> IdeaGenerationResponse | None:
    """Generate 20 ideas using the LLM based on trends and existing recipes."""
    logger.info("Starting idea generation...")
    
    # 1. Gather context
    trends = get_top_trends(limit=10)
    if not trends:
        logger.warning("No trending topics found. Will rely purely on general knowledge.")
        trends_text = "No current specific trends available."
    else:
        trends_text = "\n".join(f"- {t['title']} (relevance: {t['relevance']:.2f})" for t in trends)

    existing_titles = get_existing_recipes_formatted(limit=150)
    if not existing_titles:
        existing_titles = "No existing recipes."
        
    # 2. Load Prompts
    try:
        with open(PROMPTS_DIR / "brand_system_prompt.txt", "r", encoding="utf-8") as f:
            system_prompt = f.read()
            
        with open(PROMPTS_DIR / "idea_generation.txt", "r", encoding="utf-8") as f:
            user_prompt_template = f.read()
    except Exception as e:
        logger.error(f"Failed to load prompt templates: {e}")
        return None
        
    user_prompt = user_prompt_template.format(
        trending_topics=trends_text,
        existing_titles=existing_titles
    )
    
    # 3. Call LLM
    client = LLMClient()
    try:
        response = client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=IdeaGenerationResponse,
            task_name="idea_generation"
        )
        
        # 4. Save to DB
        save_ideas_to_db(response)
        return response
        
    except Exception as e:
        logger.error(f"Error during idea generation: {e}")
        return None

def save_ideas_to_db(response: IdeaGenerationResponse):
    """Save the generated ideas to the content_ideas table."""
    batch_date = datetime.now().strftime("%Y-%m-%d")
    inserted = 0
    
    with get_connection() as conn:
        cursor = conn.cursor()
        for idea in response.ideas:
            cursor.execute(
                """INSERT INTO content_ideas 
                   (title, content_type, description, batch_date)
                   VALUES (?, ?, ?, ?)""",
                (idea.title, idea.content_type, idea.description, batch_date)
            )
            inserted += 1
        conn.commit()
        
    logger.info(f"Saved {inserted} new ideas to DB.")

if __name__ == "__main__":
    generate_ideas()

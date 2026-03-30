from execution.config import PROMPTS_DIR
from execution.db import get_connection
from execution.models import CaptionGenerationResponse
from execution.utils.llm_client import LLMClient
from execution.utils.logger import setup_logger

logger = setup_logger("caption_generator")

def generate_captions():
    """Find pending generated_pins that need captions and generate them."""
    logger.info("Starting caption generation for pending pins...")
    
    # 1. Fetch pending pins (currently just stubs from idea_scorer)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT pin_id, title, description,
                      (SELECT content_type FROM content_ideas c WHERE c.idea_id = p.idea_id) as content_type
               FROM generated_pins p 
               WHERE status = 'pending' AND (seo_keywords IS NULL OR image_path IS NULL)"""
        )
        pins = [dict(row) for row in cursor.fetchall()]

    if not pins:
        logger.info("No pins needing captions right now.")
        return

    # 2. Load Prompts
    try:
        with open(PROMPTS_DIR / "brand_system_prompt.txt", "r", encoding="utf-8") as f:
            system_prompt = f.read()
            
        with open(PROMPTS_DIR / "caption_generation.txt", "r", encoding="utf-8") as f:
            user_prompt_template = f.read()
    except Exception as e:
        logger.error(f"Failed to load caption prompts: {e}")
        return

    client = LLMClient()
    updates = []
    
    # 3. Generate captions for each pin
    for pin in pins:
        logger.info(f"Generating caption for pin: {pin['title']}")
        user_prompt = user_prompt_template.format(
            idea_title=pin["title"],
            content_type=pin.get("content_type", "recipe"),
            target_keyword=pin["title"].lower() # Rough proxy, LLM will optimize it
        )
        
        try:
            response = client.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=CaptionGenerationResponse,
                task_name="caption_generation"
            )
            
            # Use alt_text conceptually or merge it, for now we save the text
            full_description = f"{response.pin_description}\n\n" + " ".join(response.hashtags)
            
            updates.append((
                response.pin_title,
                full_description,
                ",".join(response.hashtags),
                pin["pin_id"]
            ))
            
        except Exception as e:
            logger.error(f"Failed to generate caption for pin_id {pin['pin_id']}: {e}")

    # 4. Save to DB
    if updates:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """UPDATE generated_pins 
                   SET title=?, description=?, seo_keywords=? 
                   WHERE pin_id=?""",
                updates
            )
            conn.commit()
            
        logger.info(f"Successfully generated captions for {len(updates)} pins.")

if __name__ == "__main__":
    generate_captions()

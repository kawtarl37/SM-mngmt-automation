import datetime
from sqlalchemy.orm import Session
from execution.database import get_db, GeneratedPin, Blog
from execution.utils.llm_client import LLMClient
from execution.models import CaptionGenerationResponse
from execution.content.image_generator import generate_pin_image
from execution.content.blog_generator import generate_blog
from execution.utils.logger import setup_logger

logger = setup_logger("generate_custom_content")

def generate_custom(topic_type: str) -> dict | None:
    logger.info(f"Generating custom content for topic: {topic_type}")
    
    # 1. Generate Caption/Idea
    client = LLMClient()
    
    system_prompt = "You are a Pinterest content creator for an Easy Gluten Free brand."
    user_prompt = f"Create a new Pinterest pin idea and caption for the chosen category: {topic_type}. " \
                  f"The content must be highly engaging, Pinterest-optimized, unique, and appealing to a gluten-free audience. " \
                  f"Provide an accurate and catchy pin title, a descriptive caption, hashtags, and alt text."
    
    try:
        caption_resp: CaptionGenerationResponse = client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=CaptionGenerationResponse,
            task_name="custom_caption"
        )
    except Exception as e:
        logger.error(f"Failed to generate custom caption: {e}")
        return None
    
    # 2. Insert into DB to get Pin ID
    try:
        db_generator = get_db()
        db: Session = next(db_generator)
    except Exception as e:
        logger.error(f"Failed to get DB session: {e}")
        return None

    new_pin = GeneratedPin(
        idea_id=0,  # Custom pins are unlinked to scheduled idea generation
        title=caption_resp.pin_title,
        description=caption_resp.pin_description,
        seo_keywords=", ".join(caption_resp.hashtags),
        status="pending",
        batch_date=datetime.date.today(),
        created_at=datetime.datetime.utcnow()
    )
    db.add(new_pin)
    db.commit()
    db.refresh(new_pin)
    
    logger.info(f"Created new pending pin {new_pin.pin_id} in DB.")
    
    # 3. Generate Image
    subtitle_map = {
        "Educational": "Know Your Ingredients",
        "Practical Guide": "Tips & Tricks",
        "Lifestyle": "Living Gluten-Free",
        "Health & Wellness": "Healthy Living",
    }
    subtitle = subtitle_map.get(topic_type, "Easy, Delicious & Gluten-Free")
    
    image_path = generate_pin_image(caption_resp.pin_title, new_pin.pin_id, subtitle=subtitle)
    
    if image_path:
        new_pin.image_path = image_path
        db.commit()
        db.refresh(new_pin)
        
    # 4. Generate Blog
    # generate_blog reads the pin from SQLite by pin_id, and saves to DB. 
    blog_data = generate_blog(new_pin.pin_id)
    
    try:
        next(db_generator, None) # close Session generator
    except StopIteration:
        pass
        
    return {
        "pin_id": new_pin.pin_id,
        "pin_title": new_pin.title,
        "pin_description": new_pin.description,
        "image_path": new_pin.image_path,
        "blog_title": blog_data["title"] if blog_data else "Failed to generate blog",
        "blog_html": blog_data["html_content"] if blog_data else "No blog content generated."
    }

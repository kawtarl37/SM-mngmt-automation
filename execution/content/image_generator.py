import os
import time
import requests as http_requests
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from google import genai
from google.genai import types

from execution.config import GOOGLE_API_KEY, PROMPTS_DIR, TMP_PINS_DIR
from execution.db import get_connection
from execution.utils.cost_tracker import log_api_cost
from execution.utils.logger import setup_logger

logger = setup_logger("image_generator")

# ──────────────────────────────────────
# Font configuration
# ──────────────────────────────────────
# We use system serif fonts. On Windows, "Georgia" or "Times New Roman" are
# always available.  The user's feed uses a bold, elegant serif.
TITLE_FONT_NAME = "C:/Windows/Fonts/georgia.ttf"
SUBTITLE_FONT_NAME = "C:/Windows/Fonts/georgiaz.ttf"   # Georgia bold-italic
FALLBACK_FONT = "C:/Windows/Fonts/times.ttf"

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType font, fall back to system default."""
    for candidate in [path, FALLBACK_FONT]:
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


# ──────────────────────────────────────
# Text overlay renderer
# ──────────────────────────────────────
def add_text_overlay(
    image: Image.Image,
    title: str,
    subtitle: str | None = None,
) -> Image.Image:
    """
    Add brand-style text overlays to a food photo.
    Matches the Easy Gluten Free Pinterest feed:
      - Large bold serif TITLE at the top
      - Italic serif subtitle at the bottom
      - Warm cream/white text colour with soft shadow
    """
    img = image.copy()
    width, height = img.size
    draw = ImageDraw.Draw(img)

    # ── Title ──────────────────────────
    # Dynamically size the font so it fills ~80% of width
    title_text = title.upper()
    font_size = int(width * 0.10)  # Start large, shrink to fit
    title_font = _load_font(TITLE_FONT_NAME, font_size)

    # Wrap title text into lines that fit 80% width
    max_text_width = int(width * 0.80)
    lines = _wrap_text(title_text, title_font, max_text_width, draw)

    # If too many lines, reduce font size
    while len(lines) > 4 and font_size > 40:
        font_size -= 6
        title_font = _load_font(TITLE_FONT_NAME, font_size)
        lines = _wrap_text(title_text, title_font, max_text_width, draw)

    # Calculate total text block height
    line_spacing = int(font_size * 0.2)
    total_text_height = sum(
        draw.textbbox((0, 0), line, font=title_font)[3] - draw.textbbox((0, 0), line, font=title_font)[1]
        for line in lines
    ) + line_spacing * (len(lines) - 1)

    # Position title block in the upper third
    y_start = int(height * 0.06)
    y = y_start

    text_color = (255, 255, 250)       # warm white / cream
    shadow_color = (40, 30, 20, 120)   # soft warm shadow

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        text_w = bbox[2] - bbox[0]
        x = (width - text_w) // 2

        # Soft shadow
        shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        shadow_draw.text((x + 2, y + 2), line, fill=shadow_color, font=title_font)
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=3))
        img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)

        draw = ImageDraw.Draw(img)
        draw.text((x, y), line, fill=text_color, font=title_font)

        line_height = bbox[3] - bbox[1]
        y += line_height + line_spacing

    # ── Subtitle ───────────────────────
    if subtitle:
        sub_font_size = int(font_size * 0.45)
        sub_font = _load_font(SUBTITLE_FONT_NAME, sub_font_size)
        sub_text = subtitle

        bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
        sub_w = bbox[2] - bbox[0]
        sub_h = bbox[3] - bbox[1]
        sub_x = (width - sub_w) // 2
        sub_y = height - sub_h - int(height * 0.06)

        # Shadow for subtitle
        shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        shadow_draw.text((sub_x + 1, sub_y + 1), sub_text, fill=shadow_color, font=sub_font)
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=2))
        img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)

        draw = ImageDraw.Draw(img)
        draw.text((sub_x, sub_y), sub_text, fill=text_color, font=sub_font)

    return img.convert("RGB")


def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.Draw) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ──────────────────────────────────────
# Imagen 3 image generation
# ──────────────────────────────────────
def generate_pin_image(dish_name: str, pin_id: int, subtitle: str | None = None) -> str | None:
    """Generate a Pinterest pin image: Imagen 3 food photo + Pillow text overlay."""
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY is not set.")
        return None

    client = genai.Client(api_key=GOOGLE_API_KEY)

    try:
        with open(PROMPTS_DIR / "image_prompt_template.txt", "r", encoding="utf-8") as f:
            template = f.read()
    except Exception as e:
        logger.error(f"Failed to load image prompt template: {e}")
        return None

    prompt = template.format(dish_name=dish_name)

    retries = 3
    for attempt in range(retries):
        try:
            logger.info(f"Generating image for '{dish_name}' (Attempt {attempt + 1}/{retries})...")

            result = client.models.generate_images(
                model="imagen-4.0-generate-001",
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="9:16",
                )
            )

            # result.generated_images[0].image is a google.genai.types.Image (basically bytes + metadata)
            # We need to convert it to a PIL Image first
            raw_image_bytes = result.generated_images[0].image.image_bytes
            image = Image.open(BytesIO(raw_image_bytes))

            # Resize to exact Pinterest dimensions (1000×1500)
            image = image.resize((1000, 1500), Image.Resampling.LANCZOS)

            # Add brand text overlay
            # image = add_text_overlay(image, title=dish_name, subtitle=subtitle)

            # Save
            TMP_PINS_DIR.mkdir(parents=True, exist_ok=True)
            output_path = TMP_PINS_DIR / f"pin_{pin_id}.jpg"
            image.save(output_path, "JPEG", quality=95)

            log_api_cost("google", "imagen-4.0", 1, 1, "image_generation")
            logger.info(f"Saved pin image → {output_path}")
            return str(output_path)

        except Exception as e:
            logger.warning(f"Image generation failed: {e}")
            time.sleep(2 ** attempt)

    logger.error("Failed to generate image after all retries.")
    return None


# ──────────────────────────────────────
# Batch runner
# ──────────────────────────────────────
# Map of content_type → default subtitle
SUBTITLE_MAP = {
    "recipe": "Easy, Delicious & Gluten-Free",
    "tip": "Tips & Tricks",
    "education": "Know Your Ingredients",
}

def generate_all_pending_images():
    """Find pins without images and generate them."""
    logger.info("Starting image generation for pending pins...")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT p.pin_id, p.title,
                      (SELECT c.content_type FROM content_ideas c WHERE c.idea_id = p.idea_id) as content_type
               FROM generated_pins p
               WHERE p.status = 'pending' AND p.image_path IS NULL"""
        )
        pins = [dict(row) for row in cursor.fetchall()]

    if not pins:
        logger.info("No pins needing images right now.")
        return

    updates = []
    for pin in pins:
        content_type = pin.get("content_type", "recipe") or "recipe"
        subtitle = SUBTITLE_MAP.get(content_type, "Easy, Delicious & Gluten-Free")
        output_path = generate_pin_image(pin["title"], pin["pin_id"], subtitle=subtitle)
        if output_path:
            updates.append((output_path, pin["pin_id"]))

    if updates:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                "UPDATE generated_pins SET image_path=? WHERE pin_id=?",
                updates
            )
            conn.commit()

        logger.info(f"Successfully generated {len(updates)} images.")


if __name__ == "__main__":
    generate_all_pending_images()

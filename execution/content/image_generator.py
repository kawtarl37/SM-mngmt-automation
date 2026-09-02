import base64
import time
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from google import genai
from google.genai import types
from openai import OpenAI

from execution.config import (
    GEMINI_IMAGE_GENERATION_MODEL,
    GOOGLE_API_KEY,
    IMAGE_GENERATION_PROVIDER,
    IMAGE_GENERATION_MODEL,
    IMAGE_GENERATION_QUALITY,
    IMAGE_GENERATION_FORMAT,
    OPENAI_IMAGE_API_KEY,
    PIN_IMAGE_GENERATION_SIZE,
    PROMPTS_DIR,
    TMP_PINS_DIR,
)
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
# Image generation provider adapters
# ──────────────────────────────────────
def _generate_with_openai(prompt: str) -> Image.Image:
    """Generate an image with OpenAI's Image API and return it as a PIL image."""
    if not OPENAI_IMAGE_API_KEY:
        raise RuntimeError("OPENAI_IMAGE_API_KEY or OPENAI_API_KEY is not set.")

    client = OpenAI(api_key=OPENAI_IMAGE_API_KEY)
    result = client.images.generate(
        model=IMAGE_GENERATION_MODEL,
        prompt=prompt,
        n=1,
        size=PIN_IMAGE_GENERATION_SIZE,
        quality=IMAGE_GENERATION_QUALITY,
        output_format=IMAGE_GENERATION_FORMAT,
    )

    raw_image_bytes = base64.b64decode(result.data[0].b64_json)
    image = Image.open(BytesIO(raw_image_bytes))

    usage = getattr(result, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
    log_api_cost("openai", IMAGE_GENERATION_MODEL, input_tokens, output_tokens, "image_generation")
    return image


def _generate_with_gemini(prompt: str) -> Image.Image:
    """Generate an image with Gemini/Imagen and return it as a PIL image."""
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set.")

    client = genai.Client(api_key=GOOGLE_API_KEY)
    result = client.models.generate_images(
        model=GEMINI_IMAGE_GENERATION_MODEL,
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="9:16",
        )
    )

    raw_image_bytes = result.generated_images[0].image.image_bytes
    image = Image.open(BytesIO(raw_image_bytes))
    log_api_cost("google", GEMINI_IMAGE_GENERATION_MODEL, 1, 1, "image_generation")
    return image


def generate_pin_image(
    dish_name: str,
    pin_id: int,
    subtitle: str | None = None,
    prompt_template_name: str = "image_prompt_template.txt",
) -> str | None:
    """Generate a Pinterest pin image with the configured provider, then save a local JPG."""
    provider = IMAGE_GENERATION_PROVIDER.lower()
    if provider not in {"openai", "gemini"}:
        logger.error("Unsupported IMAGE_GENERATION_PROVIDER '%s'. Use 'openai' or 'gemini'.", provider)
        return None

    try:
        with open(PROMPTS_DIR / prompt_template_name, "r", encoding="utf-8") as f:
            template = f.read()
    except Exception as e:
        logger.error(f"Failed to load image prompt template '{prompt_template_name}': {e}")
        return None

    prompt = template.format(dish_name=dish_name)

    retries = 3
    for attempt in range(retries):
        try:
            logger.info(
                "Generating image for '%s' with %s (Attempt %s/%s)...",
                dish_name,
                provider,
                attempt + 1,
                retries,
            )

            if provider == "openai":
                image = _generate_with_openai(prompt)
            else:
                image = _generate_with_gemini(prompt)

            # Resize to exact Pinterest dimensions (1000×1500)
            image = image.resize((1000, 1500), Image.Resampling.LANCZOS)

            # Add brand text overlay
            # image = add_text_overlay(image, title=dish_name, subtitle=subtitle)

            # Save
            TMP_PINS_DIR.mkdir(parents=True, exist_ok=True)
            output_path = TMP_PINS_DIR / f"pin_{pin_id}.jpg"
            image.save(output_path, "JPEG", quality=95)

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

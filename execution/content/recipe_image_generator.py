"""
recipe_image_generator.py
-------------------------
Generates recipe images using the configured image provider:
  - 1 cover image (9:16, saved as 1000x1500) for hero/Pinterest use
  - 3 step images (1:1, saved as 1000x1000) for recipe instructions
  - 1 Pinterest pin image (1:2.1, saved as 1000x2100) composed from the cover
"""

import base64
import time
from io import BytesIO
from pathlib import Path

from google import genai
from google.genai import types
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from execution.config import (
    BASE_DIR,
    GEMINI_IMAGE_GENERATION_MODEL,
    GOOGLE_API_KEY,
    IMAGE_GENERATION_FORMAT,
    IMAGE_GENERATION_MODEL,
    IMAGE_GENERATION_PROVIDER,
    IMAGE_GENERATION_QUALITY,
    OPENAI_IMAGE_API_KEY,
    PIN_IMAGE_GENERATION_SIZE,
    STEP_IMAGE_GENERATION_SIZE,
    TMP_PINS_DIR,
)
from execution.utils.cost_tracker import log_api_cost
from execution.utils.logger import setup_logger

logger = setup_logger("recipe_image_generator")

PINTEREST_PIN_SIZE = (1000, 2100)
PLAYFAIR_FONT = BASE_DIR / "assets" / "fonts" / "PlayfairDisplay-Bold.ttf"
GEORGIA_BOLD_FONT = Path("C:/Windows/Fonts/georgiab.ttf")
GEORGIA_FONT = Path("C:/Windows/Fonts/georgia.ttf")


def _get_client():
    provider = IMAGE_GENERATION_PROVIDER.lower()
    if provider == "openai":
        if not OPENAI_IMAGE_API_KEY:
            raise RuntimeError("OPENAI_IMAGE_API_KEY or OPENAI_API_KEY is not set in .env")
        return OpenAI(api_key=OPENAI_IMAGE_API_KEY)
    if provider == "gemini":
        if not GOOGLE_API_KEY:
            raise RuntimeError("GOOGLE_API_KEY is not set in .env")
        return genai.Client(api_key=GOOGLE_API_KEY)
    raise RuntimeError("Unsupported IMAGE_GENERATION_PROVIDER. Use 'openai' or 'gemini'.")


def _log_usage(result, task: str) -> None:
    provider = IMAGE_GENERATION_PROVIDER.lower()
    if provider == "gemini":
        log_api_cost("google", GEMINI_IMAGE_GENERATION_MODEL, 1, 1, task)
        return

    usage = getattr(result, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
    log_api_cost("openai", IMAGE_GENERATION_MODEL, input_tokens, output_tokens, task)


def _generate_image(
    client,
    prompt: str,
    aspect_ratio: str,
    output_path: Path,
    retries: int = 3,
) -> str | None:
    """Call the configured image provider, save to output_path, return path string or None."""
    api_size = PIN_IMAGE_GENERATION_SIZE if aspect_ratio == "9:16" else STEP_IMAGE_GENERATION_SIZE
    target_size = (1000, 1500) if aspect_ratio == "9:16" else (1000, 1000)
    provider = IMAGE_GENERATION_PROVIDER.lower()

    for attempt in range(retries):
        try:
            logger.info(
                "%s image call [%s] attempt %s/%s: %s",
                provider,
                aspect_ratio,
                attempt + 1,
                retries,
                output_path.name,
            )
            if provider == "openai":
                result = client.images.generate(
                    model=IMAGE_GENERATION_MODEL,
                    prompt=prompt,
                    n=1,
                    size=api_size,
                    quality=IMAGE_GENERATION_QUALITY,
                    output_format=IMAGE_GENERATION_FORMAT,
                )
                raw_bytes = base64.b64decode(result.data[0].b64_json)
            elif provider == "gemini":
                result = client.models.generate_images(
                    model=GEMINI_IMAGE_GENERATION_MODEL,
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio=aspect_ratio,
                    ),
                )
                raw_bytes = result.generated_images[0].image.image_bytes
            else:
                raise RuntimeError("Unsupported IMAGE_GENERATION_PROVIDER. Use 'openai' or 'gemini'.")
            image = Image.open(BytesIO(raw_bytes)).resize(target_size, Image.Resampling.LANCZOS)

            TMP_PINS_DIR.mkdir(parents=True, exist_ok=True)
            image.save(output_path, "JPEG", quality=95)
            _log_usage(result, "recipe_image_generation")
            logger.info(f"Saved -> {output_path}")
            return str(output_path)

        except Exception as e:
            logger.warning(f"Image generation attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    logger.error(f"All {retries} attempts failed for {output_path.name}")
    return None


def _load_display_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load Playfair Display for recipe pin text, with local system fallbacks."""
    for font_path in (PLAYFAIR_FONT, GEORGIA_BOLD_FONT, GEORGIA_FONT):
        try:
            return ImageFont.truetype(str(font_path), size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Wrap text to fit max_width while preserving whole words."""
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word

    if current:
        lines.append(current)
    return lines


def _add_top_readability_gradient(image: Image.Image) -> Image.Image:
    """Add a restrained top veil so white title text remains readable."""
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = overlay.load()
    gradient_height = int(height * 0.36)

    for y in range(gradient_height):
        opacity = int(118 * (1 - y / gradient_height) ** 1.7)
        for x in range(width):
            pixels[x, y] = (0, 0, 0, opacity)

    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=10))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def generate_recipe_pinterest_pin(
    recipe_id: int,
    cover_image_path: str | None,
    recipe_title: str,
) -> str | None:
    """
    Compose a 1000x2100 Pinterest pin from the generated hero photo.

    Text is rendered deterministically in Playfair Display so the title stays
    crisp and readable; the image model is not asked to generate letters.
    """
    if not cover_image_path:
        logger.warning("Skipping Pinterest pin: no cover image for recipe_id=%s", recipe_id)
        return None

    source_path = Path(cover_image_path)
    if not source_path.exists():
        logger.warning("Skipping Pinterest pin: cover image not found: %s", cover_image_path)
        return None

    try:
        with Image.open(source_path) as source:
            pin = ImageOps.fit(
                source.convert("RGB"),
                PINTEREST_PIN_SIZE,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            ).convert("RGBA")

        pin = _add_top_readability_gradient(pin)
        draw = ImageDraw.Draw(pin)
        max_text_width = int(PINTEREST_PIN_SIZE[0] * 0.84)
        font_size = 108
        min_font_size = 58
        title = " ".join(recipe_title.strip().split())

        while True:
            font = _load_display_font(font_size)
            lines = _wrap_text(title, font, max_text_width, draw)
            if len(lines) <= 4 or font_size <= min_font_size:
                break
            font_size -= 6

        line_spacing = int(font_size * 0.16)
        line_heights = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_heights.append(bbox[3] - bbox[1])
        total_height = sum(line_heights) + line_spacing * max(0, len(lines) - 1)
        y = max(90, int(PINTEREST_PIN_SIZE[1] * 0.075) - total_height // 8)

        for line, line_height in zip(lines, line_heights):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (PINTEREST_PIN_SIZE[0] - text_width) // 2

            shadow = Image.new("RGBA", PINTEREST_PIN_SIZE, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.text(
                (x, y + 8),
                line,
                font=font,
                fill=(0, 0, 0, 115),
            )
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=7))
            pin = Image.alpha_composite(pin, shadow)
            draw = ImageDraw.Draw(pin)

            draw.text(
                (x, y),
                line,
                font=font,
                fill=(255, 255, 255, 255),
            )
            y += line_height + line_spacing

        TMP_PINS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = TMP_PINS_DIR / f"recipe_{recipe_id}_pinterest.jpg"
        pin.convert("RGB").save(output_path, "JPEG", quality=95, optimize=True)
        logger.info("Saved Pinterest pin -> %s", output_path)
        return str(output_path)
    except Exception as e:
        logger.warning("Pinterest pin composition failed: %s", e)
        return None


def generate_recipe_cover(recipe_id: int, prompt: str) -> str | None:
    """Generate the 9:16 cover/hero image for a recipe."""
    client = _get_client()
    output_path = TMP_PINS_DIR / f"recipe_{recipe_id}_cover.jpg"
    return _generate_image(client, prompt, "9:16", output_path)


def generate_recipe_step_images(recipe_id: int, step_prompts: list[str]) -> list[str | None]:
    """
    Generate up to 3 step images.
    Returns exactly 3 items; each is a path string or None if generation failed.
    """
    client = _get_client()
    results = []
    for i, prompt in enumerate(step_prompts[:3], start=1):
        output_path = TMP_PINS_DIR / f"recipe_{recipe_id}_step_{i}.jpg"
        results.append(_generate_image(client, prompt, "1:1", output_path))

    while len(results) < 3:
        results.append(None)
    return results

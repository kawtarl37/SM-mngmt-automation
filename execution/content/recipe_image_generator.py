"""
recipe_image_generator.py
-------------------------
Generates recipe images using the configured image provider:
  - 1 cover image (9:16, saved as 1000x1500) for hero/Pinterest use
  - 3 step images (1:1, saved as 1000x1000) for recipe instructions
"""

import base64
import time
from io import BytesIO
from pathlib import Path

from google import genai
from google.genai import types
from openai import OpenAI
from PIL import Image

from execution.config import (
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

"""
recipe_image_generator.py
─────────────────────────
Generates recipe images using Imagen 4:
  - 1 cover image (9:16, 1000×1500) — hero/Pinterest pin
  - 3 step images  (1:1, 1000×1000) — one per instruction step
"""

import time
from io import BytesIO
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

from execution.config import GOOGLE_API_KEY, TMP_PINS_DIR
from execution.utils.cost_tracker import log_api_cost
from execution.utils.logger import setup_logger

logger = setup_logger("recipe_image_generator")


def _get_client() -> genai.Client:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set in .env")
    return genai.Client(api_key=GOOGLE_API_KEY)


def _generate_image(
    client: genai.Client,
    prompt: str,
    aspect_ratio: str,
    output_path: Path,
    retries: int = 3,
) -> str | None:
    """Call Imagen 4, save to output_path, return path string or None."""
    for attempt in range(retries):
        try:
            logger.info(f"Imagen call [{aspect_ratio}] attempt {attempt + 1}/{retries}: {output_path.name}")
            result = client.models.generate_images(
                model="imagen-4.0-generate-001",
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio=aspect_ratio,
                ),
            )
            raw_bytes = result.generated_images[0].image.image_bytes
            image = Image.open(BytesIO(raw_bytes))

            # Resize to target dimensions
            if aspect_ratio == "9:16":
                image = image.resize((1000, 1500), Image.Resampling.LANCZOS)
            else:  # 1:1
                image = image.resize((1000, 1000), Image.Resampling.LANCZOS)

            TMP_PINS_DIR.mkdir(parents=True, exist_ok=True)
            image.save(output_path, "JPEG", quality=95)
            log_api_cost("google", "imagen-4.0", 1, 1, "recipe_image_generation")
            logger.info(f"Saved → {output_path}")
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
    Generate up to 3 step images (1:1 square).
    Returns a list of 3 items; each is a path string or None if failed.
    """
    client = _get_client()
    results = []
    for i, prompt in enumerate(step_prompts[:3], start=1):
        output_path = TMP_PINS_DIR / f"recipe_{recipe_id}_step_{i}.jpg"
        path = _generate_image(client, prompt, "1:1", output_path)
        results.append(path)
    # Pad to always return exactly 3 entries
    while len(results) < 3:
        results.append(None)
    return results

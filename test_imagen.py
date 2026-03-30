"""Test Google image gen — exhaustive model list."""
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

from google import genai
from google.genai import types

def test():
    api_key = os.getenv("GOOGLE_API_KEY")
    print(f"Key length: {len(api_key)}")
    client = genai.Client(api_key=api_key)
    
    prompt = (
        "A bright, airy iPhone photo of fluffy golden pancakes stacked on a white plate, "
        "natural daylight, modern kitchen, shallow depth of field, candid composition"
    )
    
    os.makedirs(".tmp/pins", exist_ok=True)
    
    # 1. Try Gemini models with native image generation (response_modalities=IMAGE)
    gemini_models = [
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash",
        "gemini-2.0-flash-preview-image-generation",
        "gemini-2.0-flash-exp-image-generation",
    ]
    
    for model_name in gemini_models:
        print(f"\nTrying {model_name} (generate_content with IMAGE modality)...")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                )
            )
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image"):
                    fname = f".tmp/pins/test_{model_name.replace('.','_').replace('-','_')}.jpg"
                    with open(fname, "wb") as f:
                        f.write(part.inline_data.data)
                    print(f"  SUCCESS! Saved {fname}")
                    return model_name
            print("  No image in response parts")
        except Exception as e:
            print(f"  Failed: {type(e).__name__}: {str(e)[:150]}")

    # 2. Try Imagen standalone models
    imagen_models = [
        "imagen-3.0-generate-001",
        "imagen-3.0-generate-002",
        "imagen-3.0-fast-generate-001",
        "imagen-4.0-generate-001",
        "imagen-4.0-fast-generate-001",
    ]
    
    for model_name in imagen_models:
        print(f"\nTrying {model_name} (generate_images)...")
        try:
            result = client.models.generate_images(
                model=model_name,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="9:16",
                )
            )
            for img in result.generated_images:
                fname = f".tmp/pins/test_{model_name.replace('.','_').replace('-','_')}.jpg"
                img.image.save(fname)
                print(f"  SUCCESS! Saved {fname}")
            return model_name
        except Exception as e:
            print(f"  Failed: {type(e).__name__}: {str(e)[:150]}")

    print("\nNo working model found.")
    return None

if __name__ == "__main__":
    result = test()
    if result:
        print(f"\n=== WORKING MODEL: {result} ===")

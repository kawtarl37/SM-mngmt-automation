from execution.config import OPENAI_API_KEY
from openai import OpenAI
import traceback

def test():
    print(f"Key loaded: {bool(OPENAI_API_KEY)}")
    client = OpenAI(api_key=OPENAI_API_KEY)
    try:
        r = client.images.generate(model='dall-e-3', prompt='A simple gluten-free pancake on a plate', size='1024x1024', n=1)
        print("Success:", r.data[0].url)
    except Exception as e:
        print("Error type:", type(e).__name__)
        print("Error message:", str(e))
        traceback.print_exc()

if __name__ == '__main__':
    test()

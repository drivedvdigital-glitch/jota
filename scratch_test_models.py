import asyncio
import os
from dotenv import load_dotenv
from google import genai

load_dotenv(override=True)

async def test_models():
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    models_to_test = [
        'gemini-2.5-flash',
        'gemini-2.5-flash-lite',
        'gemini-2.0-flash',
        'gemini-2.0-flash-lite',
        'gemini-3.5-flash',
        'gemini-3.1-flash-lite',
        'gemini-flash-latest',
        'gemini-pro-latest'
    ]
    
    for m in models_to_test:
        try:
            print(f"Testing model: {m}...")
            response = client.models.generate_content(
                model=m,
                contents="Reply with 'Hello from " + m + "'"
            )
            print(f"  [SUCCESS] {response.text.strip()}")
        except Exception as e:
            print(f"  [FAILED] {type(e).__name__}: {str(e)[:150]}")

if __name__ == "__main__":
    asyncio.run(test_models())

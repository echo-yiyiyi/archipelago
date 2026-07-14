from google import genai
from google.genai import types

client = genai.Client(
    vertexai=True,
    project="apex-safety",
    location="global",
)

response = client.models.generate_content(
    model="gemini-3.5-flash",
    contents="Solve this task: What is 17 * 24?",
    config=types.GenerateContentConfig(
        temperature=0,       # Useful for repeatable benchmarks
        max_output_tokens=500,
    ),
)

print(response.text)
print(response.usage_metadata)
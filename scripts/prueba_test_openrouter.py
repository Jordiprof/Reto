import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

completion = client.chat.completions.create(
    model="poolside/laguna-m.1:free",
    messages=[{"role": "user", "content": "Responde solo con la palabra: funciona"}],
)

print(completion.choices[0].message.content)
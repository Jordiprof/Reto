import os

from dotenv import load_dotenv
from ollama import Client

load_dotenv()
client = Client(
    host="https://ollama.com",
    headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
)

for nombre in ["gpt-oss:120b", "gpt-oss:120b-cloud"]:
    try:
        r = client.chat(model=nombre, messages=[{"role": "user", "content": "di ok"}])
        print(f"{nombre} -> FUNCIONA: {r['message']['content'][:50]}")
    except Exception as e:
        print(f"{nombre} -> ERROR: {e}")

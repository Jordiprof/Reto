import os
from dotenv import load_dotenv
from ollama import Client

load_dotenv()

client = Client(
    host="https://ollama.com",
    headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
)

response = client.chat(
    model="gpt-oss:120b",
    messages=[{"role": "user", "content": "Responde solo con la palabra: funciona"}],
)

print(response["message"]["content"])
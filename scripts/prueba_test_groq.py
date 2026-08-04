import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.environ["GROQ_API_KEY"])

chat_completion = client.chat.completions.create(
    messages=[{"role": "user", "content": "Responde solo con la palabra: funciona"}],
    model="llama-3.3-70b-versatile",
)

print(chat_completion.choices[0].message.content)

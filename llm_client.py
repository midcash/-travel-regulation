import os, json, asyncio
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

from openai import OpenAI  # 同步客户端

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

def ask_llm(prompt):
    if not API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置")
    client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or "{}"

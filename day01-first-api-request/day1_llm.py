import os
import requests

API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL = "gemini-2.5-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

def ask_llm(prompt: str) -> str:
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY не найден — проверь, что переменная окружения задана и терминал перезапущен")
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": API_KEY,
    }
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(URL, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]

if __name__ == "__main__":
    print(f"Мини-чат с {MODEL} (exit — выход)")
    while True:
        user_input = input("Вы: ")
        if user_input.lower() in ("exit", "quit"):
            break
        try:
            print("LLM:", ask_llm(user_input))
        except requests.RequestException as e:
            print("Ошибка запроса:", e)
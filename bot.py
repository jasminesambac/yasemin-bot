import os
import logging
import requests
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Denenecek modeller
MODELS = [
    "gemini-2.0-flash-exp",
    "gemini-1.5-pro",
    "gemini-pro"
]

def ask_gemini(question):
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}"
        
        data = {
            "contents": [{
                "parts": [{"text": question}]
            }]
        }
        
        try:
            response = requests.post(url, json=data)
            result = response.json()
            
            if "error" in result:
                continue  # Bu model çalışmadı, diğerini dene
            
            return f"[{model}]\n{result['candidates'][0]['content']['parts'][0]['text'][:500]}"
            
        except:
            continue
    
    return "Hiçbir model çalışmadı! Lütfen Google AI Studio'dan yeni API anahtarı al."

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Bot çalışıyor! /sor [soru] yaz")

@dp.message_handler(commands=['sor'])
async def ask(message: types.Message):
    question = message.get_args()
    if not question:
        await message.reply("Lütfen bir soru yaz: /sor [sorunuz]")
        return
    
    msg = await message.reply("🤔 Gemini düşünüyor...")
    
    cevap = ask_gemini(question)
    
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=msg.message_id,
        text=f"🤖 **Gemini:**\n\n{cevap}"
    )

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

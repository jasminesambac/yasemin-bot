import os
import logging
import requests
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={GEMINI_KEY}"

def ask_gemini(question):
    try:
        data = {
            "contents": [{
                "parts": [{"text": question}]
            }]
        }
        response = requests.post(GEMINI_URL, json=data)
        result = response.json()
        return result["candidates"][0]["content"]["parts"][0]["text"][:500]
    except Exception as e:
        return f"Gemini hatası: {str(e)[:100]}"

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Bot çalışıyor! /sor [soru] yaz")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Test başarılı!")

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
        text=f"🤖 **Gemini cevaplıyor:**\n\n{cevap}"
    )

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

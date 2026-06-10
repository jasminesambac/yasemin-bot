import os
import logging
import requests
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

def ask_gemini(question):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={GEMINI_KEY}"
    
    data = {
        "contents": [{
            "parts": [{"text": question}]
        }]
    }
    
    try:
        response = requests.post(url, json=data, timeout=30)
        result = response.json()
        
        if "error" in result:
            return f"API Hatası: {result['error']['message']}"
        
        return result["candidates"][0]["content"]["parts"][0]["text"][:500]
        
    except Exception as e:
        return f"Bağlantı hatası: {str(e)[:100]}"

@dp.message_handler(commands=['sor'])
async def sor(message: types.Message):
    soru = message.get_args()
    if not soru:
        await message.reply("Bir soru yaz: /sor [soru]")
        return
    
    msg = await message.reply("🤔 Gemini düşünüyor...")
    
    cevap = ask_gemini(soru)
    
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=msg.message_id,
        text=f"🤖 **Gemini:**\n\n{cevap}"
    )

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Gemini asistanın hazır!\n\n/sor [soru] - Soru sor")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

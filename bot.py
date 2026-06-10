import os
import logging
import requests
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Olası model adları (güncel)
MODEL_NAMES = [
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash-002",
    "gemini-1.5-pro-002", 
    "gemini-1.5-flash-001",
    "gemini-1.5-pro-001",
    "gemini-2.0-pro-exp",
    "gemini-exp-1206",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-pro"
]

def find_working_model(question):
    """Çalışan bir model bulana kadar dene"""
    for model in MODEL_NAMES:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}"
        
        data = {
            "contents": [{
                "parts": [{"text": question}]
            }]
        }
        
        try:
            response = requests.post(url, json=data, timeout=10)
            result = response.json()
            
            if "error" not in result:
                return model, result["candidates"][0]["content"]["parts"][0]["text"][:500]
        except:
            continue
    
    return None, "Hiçbir model çalışmadı. Lütfen Google AI Studio'da hangi modellerin aktif olduğunu kontrol et."

@dp.message_handler(commands=['sor'])
async def sor(message: types.Message):
    soru = message.get_args()
    if not soru:
        await message.reply("Bir soru yaz: /sor [soru]")
        return
    
    msg = await message.reply("🔍 Gemini modelleri taranıyor...")
    
    model, cevap = find_working_model(soru)
    
    if model:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg.message_id,
            text=f"✅ **Çalışan model: {model}**\n\n🤖 **Gemini:**\n\n{cevap}"
        )
    else:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg.message_id,
            text=f"❌ {cevap}"
        )

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Gemini Asistan aktif!\n\n/sor [soru] - Soru sor (otomatik model bulur)")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

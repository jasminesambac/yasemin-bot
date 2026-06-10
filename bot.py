import os
import logging
from openai import OpenAI
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")

# Agnes AI istemcisi (OpenAI uyumlu)
client = OpenAI(
    base_url="https://apihub.agnes-ai.com/v1",
    api_key=AGNES_API_KEY
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

def ask_agnes(question):
    try:
        response = client.chat.completions.create(
            model="agnes-2.0-flash",
            messages=[{"role": "user", "content": question}],
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Agnes hatası: {str(e)[:100]}"

@dp.message_handler(commands=['sor'])
async def sor(message: types.Message):
    soru = message.get_args()
    if not soru:
        await message.reply("Bir soru yaz: /sor [soru]")
        return
    
    msg = await message.reply("🤔 Agnes düşünüyor...")
    
    cevap = ask_agnes(soru)
    
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=msg.message_id,
        text=f"🤖 **Agnes AI:**\n\n{cevap}"
    )

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Agnes AI Asistan** hazır!\n\n📌 /sor [soru] - Soru sor")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

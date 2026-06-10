import os
import logging
import requests
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

def test_deepseek():
    """DeepSeek bağlantısını test et"""
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "Merhaba, sadece 'bağlantı başarılı' yaz"}]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        return response.status_code, response.text[:200]
    except Exception as e:
        return 0, str(e)[:100]

@dp.message_handler(commands=['testai'])
async def test_ai(message: types.Message):
    await message.reply("🔌 DeepSeek bağlantısı test ediliyor...")
    status, result = test_deepseek()
    await message.reply(f"Durum kodu: {status}\n\nYanıt: {result}")

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Bot çalışıyor! /testai ile DeepSeek'i dene")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Test başarılı!")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

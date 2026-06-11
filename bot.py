import os
import logging
import csv
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ========== STOK OKUMA ==========
def stok_oku():
    stok_listesi = []
    try:
        with open('inventory.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                stok_listesi.append(row)
    except Exception as e:
        print(f"Stok okuma hatası: {e}")
    return stok_listesi

@dp.message_handler(commands=['stok'])
async def stock(message: types.Message):
    stoklar = stok_oku()
    if not stoklar:
        await message.reply("❌ Stok dosyası okunamadı veya boş.")
        return
    
    mesaj = "📦 **ENVANTER**\n\n"
    for item in stoklar[:15]:
        mesaj += f"• {item['Malzeme / Alet']}: {item['Kalan Miktar']} {item['Birim']}\n"
    await message.reply(mesaj)

# ========== MEVCUT KOMUTLAR ==========
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Bot çalışıyor! /test ve /stok dene")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Test başarılı! Bot çalışıyor.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)import os
import logging
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Bot çalışıyor! /test yaz")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Test başarılı! Bot çalışıyor.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

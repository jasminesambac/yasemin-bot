import os
import logging
import csv
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

def stok_oku():
    stok_listesi = []
    try:
        with open('inventory.csv', 'r', encoding='utf-8-sig') as f:
            # delimiter tespiti
            ilk_satir = f.readline()
            f.seek(0)
            delimiter = ';' if ';' in ilk_satir else ','
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                stok_listesi.append(row)
    except Exception as e:
        print(f"Stok okuma hatası: {e}")
    return stok_listesi

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Bot çalışıyor! /stok yazabilirsin.")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Test başarılı! Bot çalışıyor.")

@dp.message_handler(commands=['stok'])
async def stok(message: types.Message):
    param = message.get_args()
    stoklar = stok_oku()
    
    if not stoklar:
        await message.reply("❌ Stok dosyası okunamadı veya boş.")
        return
    
    if param:
        for item in stoklar:
            if param.lower() in item.get('Malzeme / Alet', '').lower():
                await message.reply(
                    f"📦 **{item.get('Malzeme / Alet')}**\n"
                    f"📊 Kalan: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
                    f"📝 Görevi: {item.get('Görevi / Not', '-')}"
                )
                return
        await message.reply(f"❌ '{param}' envanterde bulunamadı.")
    else:
        mesaj = "📦 **ENVANTER LİSTESİ**\n\n"
        for item in stoklar[:25]:
            mesaj += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
        await message.reply(mesaj)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
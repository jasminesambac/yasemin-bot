import os
import logging
import csv
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ==================== STOK OKUMA ====================
def stok_oku():
    stok_listesi = []
    try:
        with open('inventory.csv', 'r', encoding='utf-8-sig') as f:
            # Otomatik delimiter tespiti
            ilk_satir = f.readline()
            f.seek(0)
            if ';' in ilk_satir:
                delimiter = ';'
            else:
                delimiter = ','
            
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                stok_listesi.append(row)
    except Exception as e:
        print(f"Stok okuma hatası: {e}")
    return stok_listesi

# ==================== KOMUTLAR ====================
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan** hazır!\n\n📌 **Komutlar:**\n/stok - Envanter listesi\n/stok [malzeme] - Malzeme sorgula\n/test - Bot testi")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

@dp.message_handler(commands=['stok'])
async def stock(message: types.Message):
    param = message.get_args()
    stoklar = stok_oku()
    
    if not stoklar:
        await message.reply("❌ Stok dosyası okunamadı veya boş.\n\n📌 inventory.csv dosyasının GitHub'da olduğundan emin ol.")
        return
    
    if param:
        # Belirli malzeme sorgula
        for item in stoklar:
            if param.lower() in item.get('Malzeme / Alet', '').lower():
                await message.reply(
                    f"📦 **{item.get('Malzeme / Alet', '-')}**\n"
                    f"📊 Kalan: {item.get('Kalan Miktar', '0')} {item.get('Birim', '')}\n"
                    f"📝 Görevi: {item.get('Görevi / Not', '-')}"
                )
                return
        await message.reply(f"❌ '{param}' envanterde bulunamadı.")
    else:
        # Tüm envanteri listele
        mesaj = "📦 **ENVANTER LİSTESİ**\n\n"
        for item in stoklar[:20]:
            mesaj += f"• {item.get('Malzeme / Alet', '-')}: {item.get('Kalan Miktar', '0')} {item.get('Birim', '')}\n"
        
        if len(stoklar) > 20:
            mesaj += f"\n*Toplam {len(stoklar)} malzeme var. Detay için /stok [malzeme]"
        
        await message.reply(mesaj)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
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
        # Malzemeyi bul
        malzeme_bulundu = None
        for item in stoklar:
            if param.lower() in item.get('Malzeme / Alet', '').lower():
                malzeme_bulundu = item
                break
        
        if not malzeme_bulundu:
            await message.reply(f"❌ '{param}' envanterde bulunamadı.")
            return
        
        # Stok bilgisi
        cevap = f"📦 **{malzeme_bulundu.get('Malzeme / Alet')}**\n"
        cevap += f"📊 Kalan: {malzeme_bulundu.get('Kalan Miktar')} {malzeme_bulundu.get('Birim')}\n"
        cevap += f"📝 Görevi: {malzeme_bulundu.get('Görevi / Not', '-')}\n\n"
        
        # History'den TÜM geçmiş kullanımları bul
        try:
            with open('history.csv', 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                satirlar = list(reader)
            
            kayitlar = []
            for row in satirlar[1:]:
                if len(row) >= 3 and param.lower() in row[2].lower():
                    kayitlar.append(row)
            
            if kayitlar:
                cevap += "📜 **TÜM KULLANIMLAR:**\n"
                for row in kayitlar:
                    cevap += f"   • {row[0]}: {row[2]}\n"
                if len(kayitlar) > 20:
                    cevap += f"\n*Toplam {len(kayitlar)} kayıt var.*"
            else:
                cevap += "📜 **Geçmiş kullanım kaydı yok.**"
            
        except Exception as e:
            cevap += f"📜 History okunamadı: {e}"
        
        await message.reply(cevap)
    else:
        mesaj = "📦 **ENVANTER LİSTESİ**\n\n"
        for item in stoklar[:25]:
            mesaj += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
        await message.reply(mesaj)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
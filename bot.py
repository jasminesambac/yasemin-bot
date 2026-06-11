import os
import logging
import csv
from datetime import datetime
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Geçici hafıza (son kaydı geri almak için)
son_kayit_geri_al = None

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

def tarih_format():
    return datetime.now().strftime("%d-%m-%Y")

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

def stok_kaydet(stok_listesi):
    try:
        with open('inventory.csv', 'w', encoding='utf-8-sig', newline='') as f:
            if stok_listesi:
                fieldnames = stok_listesi[0].keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
                writer.writeheader()
                writer.writerows(stok_listesi)
        return True
    except Exception as e:
        print(f"Stok kayıt hatası: {e}")
        return False

def history_ekle(islem, malzeme_adi, miktar, birim):
    try:
        with open('history.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih_format(), islem, f"{miktar} {birim} {malzeme_adi}", "-", "Bot ile eklendi"])
        return True
    except Exception as e:
        print(f"History kayıt hatası: {e}")
        return False

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Bot çalışıyor!\n\n"
                         "/stok - Envanter listesi\n"
                         "/stok NPK - Malzeme sorgula + geçmiş\n"
                         "/kaydet 5 gr NPK - Stoktan düş ve kaydet\n"
                         "/kaydet_geri_al - Son işlemi geri al\n"
                         "/test - Bot testi")

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
        malzeme_bulundu = None
        for item in stoklar:
            if param.lower() in item.get('Malzeme / Alet', '').lower():
                malzeme_bulundu = item
                break
        
        if not malzeme_bulundu:
            await message.reply(f"❌ '{param}' envanterde bulunamadı.")
            return
        
        cevap = f"📦 **{malzeme_bulundu.get('Malzeme / Alet')}**\n"
        cevap += f"📊 Kalan: {malzeme_bulundu.get('Kalan Miktar')} {malzeme_bulundu.get('Birim')}\n"
        cevap += f"📝 Görevi: {malzeme_bulundu.get('Görevi / Not', '-')}\n\n"
        
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
        except:
            cevap += "📜 History dosyası okunamadı."
        
        await message.reply(cevap)
    else:
        mesaj = "📦 **ENVANTER LİSTESİ**\n\n"
        for item in stoklar[:25]:
            mesaj += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
        await message.reply(mesaj)

@dp.message_handler(commands=['kaydet'])
async def kaydet(message: types.Message):
    global son_kayit_geri_al
    islem = message.get_args()
    if not islem:
        await message.reply("Örnek: /kaydet 5 gr NPK")
        return
    
    parcalar = islem.split()
    if len(parcalar) < 3:
        await message.reply("Örnek: /kaydet 5 gr NPK")
        return
    
    try:
        miktar = float(parcalar[0])
        birim = parcalar[1]
        malzeme = " ".join(parcalar[2:])
    except:
        await message.reply("Hatalı format. Örnek: /kaydet 5 gr NPK")
        return
    
    stoklar = stok_oku()
    for item in stoklar:
        if malzeme.lower() in item.get('Malzeme / Alet', '').lower():
            try:
                kalan = float(str(item['Kalan Miktar']).replace(',', '.'))
                if kalan >= miktar:
                    yeni_kalan = kalan - miktar
                    eski_kalan = kalan
                    item['Kalan Miktar'] = str(yeni_kalan).replace('.', ',')
                    kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
                    item['Kullanılan'] = str(kullanilan + miktar).replace('.', ',')
                    stok_kaydet(stoklar)
                    
                    # Geri alma için kaydet
                    son_kayit_geri_al = {
                        'malzeme': malzeme,
                        'eski_kalan': eski_kalan,
                        'kullanilan': miktar,
                        'birim': birim
                    }
                    
                    # History'ye kaydet
                    history_ekle("Kullanım", malzeme, miktar, birim)
                    
                    await message.reply(f"✅ {miktar:.1f} {birim} {malzeme} kullanıldı.\n📊 Kalan: {yeni_kalan:.1f} {birim}")
                    return
                else:
                    await message.reply(f"❌ Yetersiz stok! Kalan: {kalan:.1f} {birim}")
                    return
            except:
                await message.reply("❌ Miktar okunamadı")
                return
    await message.reply(f"❌ '{malzeme}' envanterde bulunamadı.")

@dp.message_handler(commands=['kaydet_geri_al'])
async def kaydet_geri_al(message: types.Message):
    global son_kayit_geri_al
    if not son_kayit_geri_al:
        await message.reply("❌ Geri alınacak kayıt yok")
        return
    
    stoklar = stok_oku()
    for item in stoklar:
        if son_kayit_geri_al['malzeme'].lower() in item.get('Malzeme / Alet', '').lower():
            item['Kalan Miktar'] = str(son_kayit_geri_al['eski_kalan']).replace('.', ',')
            kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
            item['Kullanılan'] = str(kullanilan - son_kayit_geri_al['kullanilan']).replace('.', ',')
            stok_kaydet(stoklar)
            
            miktar = son_kayit_geri_al['kullanilan']
            birim = son_kayit_geri_al['birim']
            malzeme = son_kayit_geri_al['malzeme']
            son_kayit_geri_al = None
            await message.reply(f"✅ Geri alındı: {malzeme} +{miktar:.1f} {birim}")
            return
    await message.reply("❌ Malzeme bulunamadı")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
import os
import logging
import csv
import asyncio
import zipfile
import io
import requests
from datetime import datetime
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Geçici hafızalar
silinecek_malzeme = None
son_kayit_geri_al = None

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

def tarih_format():
    return datetime.now().strftime("%d-%m-%Y")

# ==================== STOK FONKSİYONLARI ====================
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

# ==================== KOMUTLAR ====================
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan** hazır!\n\n"
                         "/stok - Envanter listesi\n"
                         "/stok NPK - Malzeme sorgula\n"
                         "/kaydet 5 gr NPK - Stok düş\n"
                         "/kaydet_geri_al - Son kaydı geri al\n"
                         "/ekle NPK;1000;gr;Gübre - Yeni malzeme\n"
                         "/ph 1 - Son pH\n"
                         "/ph_ekle 1 6.5 - pH ekle\n"
                         "/ph 1 hepsi - Tüm pH kayıtları\n"
                         "/gecmis - Son 10 işlem\n"
                         "/gecmis hepsi - Tüm işlemler\n"
                         "/sil NPK - Malzeme sil (onay için /evet)\n"
                         "/hatirlat 30-07-2026 10:00 Sula - Hatırlatma ekle\n"
                         "/hatirlatmalar - Bekleyen hatırlatmalar\n"
                         "/hatirlat_sil 1 - Hatırlatma sil\n"
                         "/rapor_gunluk - Bugünün raporu\n"
                         "/rapor_aylik 05-2026 - Aylık rapor\n"
                         "/hava İstanbul - Hava durumu\n"
                         "/yedekle - CSV yedekle\n"
                         "/test - Bot testi")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

# -------------------- STOK --------------------
@dp.message_handler(commands=['stok'])
async def stock(message: types.Message):
    param = message.get_args()
    stoklar = stok_oku()
    if not stoklar:
        await message.reply("❌ Stok dosyası okunamadı. inventory.csv var mı?")
        return
    if param:
        for item in stoklar:
            if param.lower() in item.get('Malzeme / Alet', '').lower():
                await message.reply(f"📦 **{item.get('Malzeme / Alet')}**\nKalan: {item.get('Kalan Miktar')} {item.get('Birim')}")
                return
        await message.reply(f"❌ '{param}' bulunamadı.")
    else:
        mesaj = "📦 **ENVANTER**\n\n"
        for item in stoklar[:20]:
            mesaj += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
        await message.reply(mesaj)

# -------------------- KAYDET --------------------
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
    except:
        await message.reply("Miktar sayı olmalı. Örnek: 5")
        return
    
    birim = parcalar[1]
    malzeme = " ".join(parcalar[2:])
    
    stoklar = stok_oku()
    for item in stoklar:
        if malzeme.lower() in item.get('Malzeme / Alet', '').lower():
            try:
                kalan = float(str(item['Kalan Miktar']).replace(',', '.'))
                if kalan >= miktar:
                    yeni_kalan = kalan - miktar
                    item['Kalan Miktar'] = str(yeni_kalan).replace('.', ',')
                    kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
                    item['Kullanılan'] = str(kullanilan + miktar).replace('.', ',')
                    stok_kaydet(stoklar)
                    
                    son_kayit_geri_al = {
                        'malzeme': malzeme,
                        'eski_kalan': kalan,
                        'kullanilan': miktar,
                        'birim': birim
                    }
                    
                    try:
                        with open('history.csv', 'a', encoding='utf-8-sig', newline='') as f:
                            writer = csv.writer(f)
                            writer.writerow([tarih_format(), "Sulama/Gübreleme", f"{miktar} {birim} {malzeme}", "-", "Bot ile eklendi"])
                    except:
                        pass
                    
                    await message.reply(f"✅ {miktar:.1f} {birim} {malzeme} kullanıldı. Kalan: {yeni_kalan:.1f} {birim}")
                    return
                else:
                    await message.reply(f"❌ Yetersiz stok! Kalan: {kalan:.1f} {birim}")
                    return
            except:
                await message.reply("❌ Miktar okunamadı")
                return
    await message.reply(f"❌ '{malzeme}' bulunamadı.")

# -------------------- KAYDET GERİ AL --------------------
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

# -------------------- EKLE --------------------
@dp.message_handler(commands=['ekle'])
async def ekle_envanter(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ekle NPK;1000;gr;Gübre")
        return
    
    parcalar = param.split(';')
    if len(parcalar) < 3:
        await message.reply("Format: Ad;Miktar;Birim;Görev")
        return
    
    malzeme_adi = parcalar[0].strip()
    miktar = parcalar[1].strip()
    birim = parcalar[2].strip()
    gorev = parcalar[3].strip() if len(parcalar) > 3 else "-"
    
    stoklar = stok_oku()
    for item in stoklar:
        if item.get('Malzeme / Alet', '').lower() == malzeme_adi.lower():
            await message.reply(f"❌ '{malzeme_adi}' zaten var.")
            return
    
    yeni_kayit = {
        'Kategori': 'Katı',
        'Malzeme / Alet': malzeme_adi,
        'Başlangıç Miktarı': miktar,
        'Kullanılan': '0',
        'Kalan Miktar': miktar,
        'Birim': birim,
        'Görevi / Not': gorev
    }
    stoklar.append(yeni_kayit)
    if stok_kaydet(stoklar):
        await message.reply(f"✅ **{malzeme_adi}** eklendi! ({miktar} {birim})")
    else:
        await message.reply("❌ Ekleme hatası")

# -------------------- pH --------------------
@dp.message_handler(commands=['ph_ekle'])
async def ph_ekle(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ph_ekle 1 6.5")
        return
    
    parcalar = param.split()
    if len(parcalar) < 2:
        await message.reply("Format: /ph_ekle teneke_no pH")
        return
    
    teneke = parcalar[0]
    ph = parcalar[1]
    tarih = tarih_format()
    
    try:
        with open('ph_records.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih, teneke, "Bot eklendi", ph, "Bot ile eklendi"])
        await message.reply(f"✅ pH kaydı eklendi!\n📅 {tarih} - Teneke {teneke} - pH {ph}")
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@dp.message_handler(commands=['ph'])
async def ph_sorgula(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ph 1 - Son ölçüm\n/ph 1 hepsi - Tüm ölçümler")
        return
    
    parcalar = param.split()
    teneke_no = parcalar[0]
    tumu = len(parcalar) > 1 and parcalar[1].lower() == 'hepsi'
    
    try:
        with open('ph_records.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=',')
            kayitlar = [row for row in reader if row.get('Teneke_No', '') == teneke_no]
        
        if not kayitlar:
            await message.reply(f"❌ Teneke {teneke_no} için kayıt yok.")
            return
        
        if tumu:
            mesaj = f"📊 **Teneke {teneke_no} - TÜM pH**\n\n"
            for k in sorted(kayitlar, key=lambda x: x.get('Tarih', ''), reverse=True)[:15]:
                mesaj += f"📅 {k['Tarih']}: pH {k['pH']}\n"
            await message.reply(mesaj)
        else:
            en_son = max(kayitlar, key=lambda x: x.get('Tarih', ''))
            await message.reply(f"📊 **Teneke {teneke_no}**\n📅 {en_son['Tarih']}\n🔬 pH: {en_son['pH']}")
    except Exception as e:
        await message.reply(f"Hata: {e}")

# -------------------- GEÇMİŞ --------------------
@dp.message_handler(commands=['gecmis'])
async def gecmis(message: types.Message):
    param = message.get_args()
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("Henüz kayıt yok. /kaydet ile ekleme yapabilirsin.")
            return
        
        veriler = satirlar[1:]
        
        if not param:
            sonlar = veriler[-10:][::-1]
            mesaj = "📜 **SON 10 İŞLEM**\n\n"
            for row in sonlar:
                mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:50]}\n\n"
            await message.reply(mesaj[:4000])
        elif param.lower() == 'hepsi':
            mesaj = "📜 **TÜM İŞLEMLER**\n\n"
            for row in veriler[-30:][::-1]:
                mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:50]}\n\n"
            await message.reply(mesaj[:4000])
        else:
            ay_kayitlari = [row for row in veriler if row[0].endswith(param)]
            if not ay_kayitlari:
                await message.reply(f"❌ {param} için kayıt bulunamadı.")
                return
            mesaj = f"📜 **{param} İŞLEMLERİ**\n\n"
            for row in ay_kayitlari:
                mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:50]}\n\n"
            await message.reply(mesaj[:4000])
    except Exception as e:
        await message.reply(f"Dosya okuma hatası: {e}")

# -------------------- SİL --------------------
@dp.message_handler(commands=['sil'])
async def sil_stok(message: types.Message):
    global silinecek_malzeme
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /sil NPK")
        return
    
    stoklar = stok_oku()
    for item in stoklar:
        if param.lower() in item.get('Malzeme / Alet', '').lower():
            silinecek_malzeme = item
            await message.reply(f"⚠️ **{item['Malzeme / Alet']}** silinsin mi? 30 sn içinde /evet yaz.")
            await asyncio.sleep(30)
            if silinecek_malzeme == item:
                silinecek_malzeme = None
                await message.reply("⏰ Silme iptal.")
            return
    await message.reply(f"❌ '{param}' bulunamadı.")

@dp.message_handler(commands=['evet'])
async def evet_sil(message: types.Message):
    global silinecek_malzeme
    if not silinecek_malzeme:
        await message.reply("❌ Silinecek malzeme yok.")
        return
    
    stoklar = stok_oku()
    malzeme_adi = silinecek_malzeme['Malzeme / Alet']
    yeni_stoklar = [item for item in stoklar if item.get('Malzeme / Alet') != malzeme_adi]
    
    if stok_kaydet(yeni_stoklar):
        await message.reply(f"✅ **{malzeme_adi}** silindi.")
    else:
        await message.reply("❌ Silme hatası")
    silinecek_malzeme = None

# -------------------- HATIRLATMA --------------------
@dp.message_handler(commands=['hatirlat'])
async def hatirlat(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /hatirlat 30-07-2026 10:00 Sula")
        return
    
    parcalar = param.split(maxsplit=2)
    if len(parcalar) < 3:
        await message.reply("Format: /hatirlat gun-ay-yil saat islem")
        return
    
    tarih, saat, islem = parcalar
    
    try:
        with open('reminders.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih, saat, islem, "bekliyor"])
        await message.reply(f"✅ Hatırlatma eklendi!\n📅 {tarih} {saat}\n📝 {islem}\n\n⚠️ Otomatik mesaj için zamanlayıcı henüz aktif değil.")
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@dp.message_handler(commands=['hatirlatmalar'])
async def list_hatirlatmalar(message: types.Message):
    try:
        with open('reminders.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("Henüz hatırlatma yok.")
            return
        
        bekleyenler = [(i, row) for i, row in enumerate(satirlar[1:], 1) if len(row) >= 4 and row[3] == "bekliyor"]
        if not bekleyenler:
            await message.reply("✅ Bekleyen hatırlatma yok.")
            return
        
        mesaj = "📅 **HATIRLATMALAR**\n\n"
        for i, row in bekleyenler:
            mesaj += f"**ID: {i}** | {row[0]} {row[1]} - {row[2]}\n"
        await message.reply(mesaj[:4000])
    except:
        await message.reply("Dosya okuma hatası.")

@dp.message_handler(commands=['hatirlat_sil'])
async def hatirlat_sil(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /hatirlat_sil 1\n(ID'yi /hatirlatmalar ile görebilirsin)")
        return
    
    try:
        with open('reminders.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ Hatırlatma yok.")
            return
        
        idx = int(param)
        if idx < 1 or idx >= len(satirlar):
            await message.reply("❌ Geçersiz ID.")
            return
        
        silinen = satirlar.pop(idx)
        with open('reminders.csv', 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(satirlar)
        
        await message.reply(f"✅ Hatırlatma silindi:\n{silinen[0]} {silinen[1]} - {silinen[2]}")
    except:
        await message.reply("❌ Hata")

# -------------------- RAPOR --------------------
@dp.message_handler(commands=['rapor_gunluk'])
async def rapor_gunluk(message: types.Message):
    bugun = tarih_format()
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        gunun_islemleri = [row for row in satirlar[1:] if row[0] == bugun]
        if not gunun_islemleri:
            await message.reply("Bugün hiç işlem yapılmamış.")
            return
        
        rapor = f"📅 **{bugun} GÜNLÜK RAPOR**\n\n"
        for row in gunun_islemleri[:15]:
            rapor += f"• {row[1]}: {row[2][:40]}\n"
        await message.reply(rapor)
    except Exception as e:
        await message.reply(f"Rapor alınamadı: {e}")

@dp.message_handler(commands=['rapor_aylik'])
async def rapor_aylik(message: types.Message):
    ay = message.get_args()
    if not ay:
        await message.reply("Örnek: /rapor_aylik 05-2026")
        return
    
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        ay_kayitlari = [row for row in satirlar[1:] if row[0].endswith(ay)]
        if not ay_kayitlari:
            await message.reply(f"{ay} için kayıt bulunamadı.")
            return
        
        rapor = f"📊 **{ay} AYLIK RAPOR**\n\n📝 Toplam: {len(ay_kayitlari)} işlem\n\n"
        for row in ay_kayitlari[:10]:
            rapor += f"   • {row[0]} - {row[1]}\n"
        await message.reply(rapor)
    except Exception as e:
        await message.reply(f"Rapor alınamadı: {e}")

# -------------------- HAVA --------------------
@dp.message_handler(commands=['hava'])
async def hava(message: types.Message):
    yer = message.get_args()
    if not yer:
        yer = "Istanbul"
    try:
        url = f"https://wttr.in/{yer}?format=%C+%t+%w+%h&m"
        response = requests.get(url, timeout=10)
        await message.reply(f"🌤️ **{yer}**\n{response.text.strip()}")
    except:
        await message.reply("Hava durumu alınamadı.")

# -------------------- YEDEK --------------------
@dp.message_handler(commands=['yedekle'])
async def yedekle(message: types.Message):
    await message.reply("📦 Yedekleniyor...")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for dosya in ['inventory.csv', 'history.csv', 'ph_records.csv', 'reminders.csv']:
            try:
                zip_file.write(dosya)
            except:
                pass
    zip_buffer.seek(0)
    await message.reply_document(document=('yasemin_yedek.zip', zip_buffer), caption="📦 Yedek")

# -------------------- BAŞLAT --------------------
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

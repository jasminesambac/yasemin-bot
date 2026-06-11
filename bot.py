import os
import logging
import csv
import re
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
stok_uyarilari = {}
ph_uyarilari = {}
baglam_metinleri = {}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ==================== YARDIMCI FONKSİYONLAR ====================
def tarih_format():
    return datetime.now().strftime("%d-%m-%Y")

def mesaj_parcala(metin, uzunluk=4000):
    if len(metin) <= uzunluk:
        return [metin]
    parcalar = []
    for i in range(0, len(metin), uzunluk):
        parcalar.append(metin[i:i+uzunluk])
    return parcalar

def baglam_guncelle(user_id, mesaj, cevap=""):
    if user_id not in baglam_metinleri:
        baglam_metinleri[user_id] = ""
    baglam_metinleri[user_id] += f"Kullanıcı: {mesaj}\n"
    if cevap:
        baglam_metinleri[user_id] += f"Asistan: {cevap}\n"
    satirlar = baglam_metinleri[user_id].split('\n')
    if len(satirlar) > 50:
        baglam_metinleri[user_id] = '\n'.join(satirlar[-50:])

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

def stok_bul(malzeme_adi):
    stoklar = stok_oku()
    for item in stoklar:
        if malzeme_adi.lower() in item.get('Malzeme / Alet', '').lower():
            return item
    return None

def stoktan_dus(malzeme_adi, miktar, birim):
    global son_kayit_geri_al
    stoklar = stok_oku()
    for item in stoklar:
        if malzeme_adi.lower() in item.get('Malzeme / Alet', '').lower():
            try:
                kalan = float(str(item.get('Kalan Miktar', '0')).replace(',', '.'))
                miktar_float = float(miktar)
                if kalan >= miktar_float:
                    yeni_kalan = kalan - miktar_float
                    item['Kalan Miktar'] = str(yeni_kalan).replace('.', ',')
                    kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
                    item['Kullanılan'] = str(kullanilan + miktar_float).replace('.', ',')
                    stok_kaydet(stoklar)
                    
                    son_kayit_geri_al = {
                        'malzeme': malzeme_adi,
                        'eski_kalan': kalan,
                        'kullanilan': miktar_float,
                        'birim': birim
                    }
                    
                    if malzeme_adi in stok_uyarilari and yeni_kalan <= stok_uyarilari[malzeme_adi]:
                        return True, f"{yeni_kalan:.1f} {birim} ⚠️ STOK UYARI!"
                    return True, f"{yeni_kalan:.1f} {birim}"
                else:
                    return False, f"Yetersiz! Kalan: {kalan:.1f}"
            except:
                return False, "Miktar okunamadı"
    return False, f"'{malzeme_adi}' bulunamadı"

def kayit_geri_al():
    global son_kayit_geri_al
    if not son_kayit_geri_al:
        return False, "Geri alınacak kayıt yok"
    
    stoklar = stok_oku()
    for item in stoklar:
        if son_kayit_geri_al['malzeme'].lower() in item.get('Malzeme / Alet', '').lower():
            item['Kalan Miktar'] = str(son_kayit_geri_al['eski_kalan']).replace('.', ',')
            kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
            item['Kullanılan'] = str(kullanilan - son_kayit_geri_al['kullanilan']).replace('.', ',')
            stok_kaydet(stoklar)
            malzeme = son_kayit_geri_al['malzeme']
            miktar = son_kayit_geri_al['kullanilan']
            birim = son_kayit_geri_al['birim']
            son_kayit_geri_al = None
            return True, f"{malzeme} +{miktar} {birim} (geri alındı)"
    return False, "Malzeme bulunamadı"

def parse_metin(text):
    pattern = r'(\d+(?:\.\d+)?)\s*([a-zA-Zğüşıöç]+)\s+(.+?)(?=\s*\+|\s*$)'
    malzemeler = []
    matches = re.findall(pattern, text, re.IGNORECASE)
    for miktar, birim, ad in matches:
        malzemeler.append({'miktar': miktar, 'birim': birim, 'ad': ad.strip()})
    return malzemeler

# ==================== HATIRLATICI ====================
def hatirlatma_ekle(tarih, saat, islem):
    try:
        with open('reminders.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih, saat, islem, "bekliyor"])
        return True
    except:
        return False

# ==================== HAVA DURUMU ====================
def hava_durumu(sehir="Istanbul"):
    try:
        url = f"https://wttr.in/{sehir}?format=%C+%t+%w+%h"
        response = requests.get(url, timeout=10)
        return response.text.strip()
    except:
        return "Hava durumu alınamadı."

# ==================== RAPORLAR ====================
def gunluk_rapor():
    bugun = tarih_format()
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        gunun_islemleri = [row for row in satirlar[1:] if row[0] == bugun]
        if not gunun_islemleri:
            return "Bugün hiç işlem yapılmamış."
        rapor = f"📅 **{bugun} GÜNLÜK RAPOR**\n\n"
        for row in gunun_islemleri[:20]:
            rapor += f"• {row[1]}: {row[2][:50]}\n"
        return rapor
    except:
        return "Rapor alınamadı."

def aylik_rapor(ay_str):
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        ay_kayitlari = [row for row in satirlar[1:] if row[0].endswith(ay_str)]
        if not ay_kayitlari:
            return f"{ay_str} için kayıt yok."
        rapor = f"📊 **{ay_str} AYLIK RAPOR**\n\n📝 Toplam: {len(ay_kayitlari)} işlem\n\n"
        for row in ay_kayitlari[:15]:
            rapor += f"   • {row[1]}\n"
        return rapor
    except:
        return "Rapor alınamadı."

# ==================== KOMUTLAR ====================
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan** hazır!\n\n"
                         "/stok - Envanter\n/stok NPK - Malzeme sorgula\n"
                         "/kaydet 5 gr NPK - Stok düş\n/kaydet_geri_al - Geri al\n"
                         "/ekle Ad;100;gr;Görev - Yeni malzeme\n"
                         "/ph 1 - pH sorgula\n/ph 1 hepsi - Tüm pH\n"
                         "/gecmis - Son 10 işlem\n/gecmis hepsi - Tüm işlemler\n"
                         "/hatirlat 30-07-2026 10:00 Sula - Hatırlatma\n/hatirlatmalar - Liste\n"
                         "/rapor_gunluk - Bugün\n/rapor_aylik 05-2026 - Aylık\n"
                         "/hava İstanbul - Hava durumu\n/yedekle - Yedek\n/test")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

@dp.message_handler(commands=['stok'])
async def stock(message: types.Message):
    param = message.get_args()
    stoklar = stok_oku()
    if not stoklar:
        await message.reply("❌ Stok dosyası okunamadı.")
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

@dp.message_handler(commands=['kaydet'])
async def kaydet(message: types.Message):
    islem = message.get_args()
    if not islem:
        await message.reply("Örnek: /kaydet 5 gr NPK")
        return
    malzemeler = parse_metin(islem)
    if not malzemeler:
        await message.reply("⚠️ Malzeme bulunamadı.")
        return
    sonuclar = []
    for m in malzemeler:
        if m['ad'].lower() in ['su', 'water']:
            sonuclar.append(f"• {m['miktar']} {m['birim']} {m['ad']}: stoktan düşülmez")
        else:
            basari, mesaj_sonuc = stoktan_dus(m['ad'], m['miktar'], m['birim'])
            if basari:
                sonuclar.append(f"• {m['miktar']} {m['birim']} {m['ad']}: ✅ {mesaj_sonuc}")
            else:
                sonuclar.append(f"• {m['miktar']} {m['birim']} {m['ad']}: ❌ {mesaj_sonuc}")
    await message.reply("✅ **İşlem kaydedildi!**\n\n" + "\n".join(sonuclar))

@dp.message_handler(commands=['kaydet_geri_al'])
async def kaydet_geri_al(message: types.Message):
    basari, mesaj = kayit_geri_al()
    await message.reply(f"✅ {mesaj}" if basari else f"❌ {mesaj}")

@dp.message_handler(commands=['ekle'])
async def ekle_envanter(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ekle Gubre;500;gr;Deneme")
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
        await message.reply(f"✅ **{malzeme_adi}** eklendi ({miktar} {birim})")
    else:
        await message.reply("❌ Ekleme hatası.")

@dp.message_handler(commands=['ph'])
async def ph_sorgula(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ph 1 veya /ph 1 hepsi")
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

@dp.message_handler(commands=['gecmis'])
async def gecmis(message: types.Message):
    param = message.get_args()
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        if len(satirlar) <= 1:
            await message.reply("Henüz kayıt yok.")
            return
        veriler = satirlar[1:]
        if not param:
            sonlar = veriler[-10:][::-1]
            mesaj = "📜 **SON 10 İŞLEM**\n\n"
            for row in sonlar:
                mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:50]}\n\n"
            await message.reply(mesaj[:4000])
        elif param.lower() == 'hepsi':
            for i in range(0, len(veriler), 15):
                blok = veriler[i:i+15]
                mesaj = "📜 **GEÇMİŞ**\n\n"
                for row in blok:
                    mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:50]}\n\n"
                await message.reply(mesaj[:4000])
        else:
            ay_kayitlari = [row for row in veriler if row[0].endswith(param)]
            if not ay_kayitlari:
                await message.reply(f"❌ {param} için kayıt yok.")
                return
            mesaj = f"📜 **{param} İŞLEMLERİ**\n\n"
            for row in ay_kayitlari:
                mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:50]}\n\n"
            await message.reply(mesaj[:4000])
    except:
        await message.reply("Dosya okuma hatası.")

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
        await message.reply("❌ Silme hatası.")
    silinecek_malzeme = None

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
    if hatirlatma_ekle(tarih, saat, islem):
        await message.reply(f"✅ Hatırlatma eklendi!\n📅 {tarih} {saat}\n📝 {islem}")
    else:
        await message.reply("❌ Hata.")

@dp.message_handler(commands=['hatirlatmalar'])
async def list_hatirlatmalar(message: types.Message):
    try:
        with open('reminders.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        if len(satirlar) <= 1:
            await message.reply("Hatırlatma yok.")
            return
        bekleyenler = [row for row in satirlar[1:] if len(row) >= 4 and row[3] == "bekliyor"]
        if not bekleyenler:
            await message.reply("✅ Bekleyen hatırlatma yok.")
            return
        mesaj = "📅 **HATIRLATMALAR**\n\n"
        for i, row in enumerate(bekleyenler, 1):
            mesaj += f"{i}. {row[0]} {row[1]} - {row[2]}\n"
        await message.reply(mesaj[:4000])
    except:
        await message.reply("Dosya okuma hatası.")

@dp.message_handler(commands=['rapor_gunluk'])
async def rapor_gunluk(message: types.Message):
    await message.reply(gunluk_rapor())

@dp.message_handler(commands=['rapor_aylik'])
async def rapor_aylik(message: types.Message):
    ay = message.get_args()
    if not ay:
        await message.reply("Örnek: /rapor_aylik 05-2026")
        return
    await message.reply(aylik_rapor(ay))

@dp.message_handler(commands=['hava'])
async def hava(message: types.Message):
    sehir = message.get_args()
    if not sehir:
        sehir = "Istanbul"
    durum = hava_durumu(sehir)
    await message.reply(f"🌤️ **{sehir}**\n{durum}")

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

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
import os
import logging
import csv
import io
import zipfile
import asyncio
import requests
from datetime import datetime
from openai import OpenAI
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")

# Geçici hafızalar
son_kayit_geri_al = None
silinecek_malzeme = None
silinecek_ph_kayitlari = None
silinecek_gecmis_id = None
silinecek_gecmis_hepsi = None
silinecek_kayit_id = None
silinecek_kayit_hepsi = None
stok_uyarilari = {}
stok_uyari_temizlik_onay = False
baglam_metinleri = {}

# Agnes AI istemcisi
client = OpenAI(
    base_url="https://apihub.agnes-ai.com/v1",
    api_key=AGNES_API_KEY
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

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

def ask_agnes(question, user_id=None):
    try:
        messages = []
        if user_id and user_id in baglam_metinleri and baglam_metinleri[user_id]:
            baglam = baglam_metinleri[user_id][-2000:]
            messages.append({"role": "system", "content": f"Previous conversation:\n{baglam}"})
        messages.append({"role": "user", "content": question})
        response = client.chat.completions.create(
            model="agnes-2.0-flash",
            messages=messages,
            max_tokens=3000
        )
        cevap = response.choices[0].message.content
        return cevap
    except Exception as e:
        return f"Agnes error: {str(e)[:100]}"

def stok_oku():
    stok_listesi = []
    try:
        with open('inventory.csv', 'r', encoding='utf-8-sig') as f:
            icerik = f.read()
            satirlar = icerik.strip().split('\n')
            if not satirlar:
                return []
            basliklar = satirlar[0].split(';')
            for satir in satirlar[1:]:
                if satir.strip():
                    degerler = satir.split(';')
                    while len(degerler) < len(basliklar):
                        degerler.append('')
                    satir_sozluk = {}
                    for i, baslik in enumerate(basliklar):
                        satir_sozluk[baslik] = degerler[i].strip()
                    stok_listesi.append(satir_sozluk)
    except Exception as e:
        print(f"Stok okuma hatası: {e}")
    return stok_listesi

def stok_kaydet(stok_listesi):
    try:
        with open('inventory.csv', 'w', encoding='utf-8-sig', newline='') as f:
            if stok_listesi:
                fieldnames = ['Kategori', 'Malzeme / Alet', 'Başlangıç Miktarı', 'Kullanılan', 'Kalan Miktar', 'Birim', 'Görevi / Not']
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

def malzeme_bul(aranan, stoklar):
    aranan = aranan.lower()
    eslesenler = []
    for item in stoklar:
        malzeme_adi = item.get('Malzeme / Alet', '').lower()
        if aranan in malzeme_adi:
            eslesenler.append(item)
    return eslesenler

def hatirlatma_ekle(tarih, saat, islem):
    try:
        with open('reminders.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih, saat, islem, "bekliyor"])
        return True
    except Exception as e:
        print(f"Hatırlatma ekleme hatası: {e}")
        return False

def stok_uyari_kontrol(malzeme_adi, kalan_miktar, birim):
    for uyarilanan_malzeme, veri in stok_uyarilari.items():
        if uyarilanan_malzeme.lower() == malzeme_adi.lower():
            if veri['birim'].lower() == birim.lower() and kalan_miktar <= veri['esik']:
                return True, veri['esik'], veri['birim']
    return False, None, None

# ==================== HAVA DURUMU (İNGİLİZCE - ÇALIŞIR) ====================
@dp.message_handler(commands=['hava'])
async def hava(message: types.Message):
    sehir = message.get_args()
    if not sehir:
        sehir = "Istanbul"
    try:
        url = f"https://wttr.in/{sehir}?format=%l:+%t+%C&m"
        response = requests.get(url, timeout=10)
        sonuc = response.text.strip()
        await message.reply(f"🌤️ **{sehir.upper()} - CURRENT WEATHER**\n\n{sonuc}")
    except:
        await message.reply("❌ Weather data unavailable.")

@dp.message_handler(commands=['hava_gunluk'])
async def hava_gunluk(message: types.Message):
    sehir = message.get_args()
    if not sehir:
        sehir = "Istanbul"
    try:
        url = f"https://wttr.in/{sehir}?0..1&format=%l:+%t+%C+%w&m"
        response = requests.get(url, timeout=10)
        satirlar = response.text.strip().split('\n')
        mesaj = f"📅 **{sehir.upper()} - DAILY WEATHER**\n\n"
        for i, satir in enumerate(satirlar):
            if i == 0:
                mesaj += f"**Today:** {satir}\n"
            else:
                mesaj += f"**Tomorrow:** {satir}\n"
        await message.reply(mesaj)
    except:
        await message.reply("❌ Weather data unavailable.")

@dp.message_handler(commands=['hava_haftalik'])
async def hava_haftalik(message: types.Message):
    sehir = message.get_args()
    if not sehir:
        sehir = "Istanbul"
    try:
        url = f"https://wttr.in/{sehir}?0..7&format=%l:+%t+%C&m"
        response = requests.get(url, timeout=10)
        satirlar = response.text.strip().split('\n')
        mesaj = f"📆 **{sehir.upper()} - 7 DAY WEATHER**\n\n"
        for satir in satirlar[:7]:
            mesaj += f"{satir}\n"
        await message.reply(mesaj)
    except:
        await message.reply("❌ Weather data unavailable.")

@dp.message_handler(commands=['hava_haftalik_detay'])
async def hava_haftalik_detay(message: types.Message):
    sehir = message.get_args()
    if not sehir:
        sehir = "Istanbul"
    try:
        url = f"https://wttr.in/{sehir}?0..7&format=%l:+%t+%w+%C+%h&m"
        response = requests.get(url, timeout=10)
        satirlar = response.text.strip().split('\n')
        mesaj = f"📆 **{sehir.upper()} - 7 DAY DETAILED WEATHER**\n\n"
        for satir in satirlar[:7]:
            mesaj += f"{satir}\n"
        await message.reply(mesaj)
    except:
        await message.reply("❌ Weather data unavailable.")

@dp.message_handler(commands=['hava_aylik'])
async def hava_aylik(message: types.Message):
    sehir = message.get_args()
    if not sehir:
        sehir = "Istanbul"
    try:
        url = f"https://wttr.in/{sehir}?m&format=%l:+%t+%C"
        response = requests.get(url, timeout=10)
        await message.reply(f"📊 **{sehir.upper()} - MONTHLY WEATHER**\n\n{response.text.strip()}")
    except:
        await message.reply("❌ Weather data unavailable.")

# ==================== KOMUTLAR ====================
@dp.message_handler(commands=['sor'])
async def sor(message: types.Message):
    soru = message.get_args()
    if not soru:
        await message.reply("Write a question: /sor [your question]")
        return
    user_id = str(message.from_user.id)
    msg = await message.reply("🤔 Agnes is thinking...")
    cevap = ask_agnes(soru, user_id)
    baglam_guncelle(user_id, soru, cevap)
    for parca in mesaj_parcala(cevap):
        await bot.send_message(chat_id=message.chat.id, text=f"🤖 **Agnes AI:**\n\n{parca}")

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin Assistant** ready!\n\n"
                         "📦 **STOCK COMMANDS:**\n"
                         "/stok - Inventory list\n"
                         "/stok [material] - Search material\n"
                         "/kaydet [amount] [unit] [material] - Use stock\n"
                         "/kaydet [note] - Save note\n"
                         "/kaydet_geri_al - Undo last operation\n"
                         "/ekle [name];[amount];[unit];[task] - Add new material\n"
                         "/sil [material] - Delete material (confirm: /evet)\n\n"
                         "🔬 **pH COMMANDS:**\n"
                         "/ph [can] - Latest pH\n"
                         "/ph [can] hepsi - All pH records\n"
                         "/ph_tumu - All cans all pH\n"
                         "/ph_ekle [can] [ph] - Add pH\n"
                         "/ph_sil [can] - Delete last pH\n\n"
                         "📜 **HISTORY COMMANDS:**\n"
                         "/gecmis - Last 10 records\n"
                         "/gecmis hepsi - All history\n"
                         "/gecmis [date] - Date filtered\n"
                         "/gecmis_sil [id] - Delete record (confirm: /gecmis_evet)\n\n"
                         "📊 **REPORT COMMANDS:**\n"
                         "/rapor_aylik [mm-yyyy] - Monthly report\n"
                         "/rapor_gunluk - Daily report\n"
                         "/istatistik - Statistics\n"
                         "/grafik [material] - Stock graph\n\n"
                         "⚠️ **ALERT COMMANDS:**\n"
                         "/stok_uyari [material] [threshold] [unit] - Add stock alert\n"
                         "/stok_uyari_sil [material] - Remove alert\n"
                         "/stok_uyari_liste - List alerts\n\n"
                         "⏰ **REMINDER COMMANDS:**\n"
                         "/hatirlat [dd-mm-yyyy] [hour:min] [task] - Add reminder\n"
                         "/hatirlatmalar - Pending reminders\n"
                         "/hatirlat_sil [id] - Delete reminder\n\n"
                         "🤖 **AI:**\n"
                         "/sor [question] - Ask Agnes AI\n\n"
                         "🌤️ **WEATHER:**\n"
                         "/hava [city] - Current weather\n"
                         "/hava_gunluk [city] - Today & tomorrow\n"
                         "/hava_haftalik [city] - 7 days\n"
                         "/hava_haftalik_detay [city] - 7 days detailed\n"
                         "/hava_aylik [city] - Monthly summary\n\n"
                         "💾 **OTHER:**\n"
                         "/yedekle - Backup CSV files\n"
                         "/test - Bot test")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot is working!")

# ==================== YEDEKLEME ====================
@dp.message_handler(commands=['yedekle'])
async def yedekle(message: types.Message):
    await message.reply("📦 Preparing backup...")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for dosya in ['inventory.csv', 'history.csv', 'ph_records.csv', 'reminders.csv']:
            try:
                zip_file.write(dosya)
            except:
                pass
    zip_buffer.seek(0)
    await message.reply_document(document=('yasemin_yedek.zip', zip_buffer), caption="📦 Backup files")

# ==================== STOK UYARISI ====================
@dp.message_handler(commands=['stok_uyari'])
async def stok_uyari_ekle(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Example: /stok_uyari \"NPK\" 100 gr")
        return
    
    parcalar = param.split()
    if len(parcalar) < 3:
        await message.reply("Example: /stok_uyari \"NPK\" 100 gr")
        return
    
    try:
        esik = float(parcalar[-2])
        birim = parcalar[-1].lower()
        malzeme_aranan = " ".join(parcalar[:-2]).strip('"')
    except:
        await message.reply("Example: /stok_uyari \"NPK\" 100 gr")
        return
    
    stoklar = stok_oku()
    eslesenler = malzeme_bul(malzeme_aranan, stoklar)
    
    if not eslesenler:
        await message.reply(f"❌ '{malzeme_aranan}' not found in inventory.")
        return
    
    if len(eslesenler) > 1:
        liste = "\n".join([f"• {item.get('Malzeme / Alet')}" for item in eslesenler[:5]])
        await message.reply(f"⚠️ Multiple materials found for '{malzeme_aranan}':\n\n{liste}\n\nPlease use full name.")
        return
    
    malzeme_adi = eslesenler[0].get('Malzeme / Alet')
    stok_uyarilari[malzeme_adi] = {'esik': esik, 'birim': birim}
    await message.reply(f"✅ Stock alert added:\n📦 {malzeme_adi}\n⚠️ Alert below {esik} {birim}")

@dp.message_handler(commands=['stok_uyari_sil'])
async def stok_uyari_sil(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Example: /stok_uyari_sil NPK")
        return
    
    silinecekler = []
    for malzeme in stok_uyarilari.keys():
        if param.lower() in malzeme.lower():
            silinecekler.append(malzeme)
    
    if not silinecekler:
        await message.reply(f"❌ No stock alert found for '{param}'.")
        return
    
    if len(silinecekler) > 1:
        liste = "\n".join([f"• {m}" for m in silinecekler])
        await message.reply(f"⚠️ Multiple alerts found for '{param}':\n\n{liste}\n\nPlease use full name.")
        return
    
    del stok_uyarilari[silinecekler[0]]
    await message.reply(f"✅ Stock alert removed for {silinecekler[0]}.")

@dp.message_handler(commands=['stok_uyari_liste'])
async def stok_uyari_liste(message: types.Message):
    if not stok_uyarilari:
        await message.reply("📋 No active stock alerts.\n\n/stok_uyari \"NPK\" 100 gr to add one.")
        return
    
    mesaj = "📋 **ACTIVE STOCK ALERTS**\n\n"
    stoklar = stok_oku()
    for malzeme, veri in stok_uyarilari.items():
        kalan = "?"
        for item in stoklar:
            if item.get('Malzeme / Alet') == malzeme:
                kalan = f"{item.get('Kalan Miktar')} {item.get('Birim')}"
                break
        mesaj += f"📦 {malzeme}\n   ⚠️ Threshold: {veri['esik']} {veri['birim']} | 📊 Current: {kalan}\n\n"
    await message.reply(mesaj)

@dp.message_handler(commands=['stok_uyari_temizle'])
async def stok_uyari_temizle(message: types.Message):
    global stok_uyari_temizlik_onay
    if not stok_uyarilari:
        await message.reply("❌ No stock alerts to delete.")
        return
    
    stok_uyari_temizlik_onay = True
    await message.reply(f"⚠️ **WARNING!**\n\n"
                       f"ALL stock alerts will be deleted ({len(stok_uyarilari)} alerts).\n\n"
                       f"**This action is IRREVERSIBLE!**\n\n"
                       f"Type `/stok_uyari_evet` within 30 seconds to confirm.")
    
    await asyncio.sleep(30)
    if stok_uyari_temizlik_onay:
        stok_uyari_temizlik_onay = False
        await message.reply("⏰ Deletion cancelled.")

@dp.message_handler(commands=['stok_uyari_evet'])
async def stok_uyari_evet(message: types.Message):
    global stok_uyari_temizlik_onay, stok_uyarilari
    if not stok_uyari_temizlik_onay:
        await message.reply("❌ No pending deletion or time expired. Use /stok_uyari_temizle first.")
        return
    
    stok_uyarilari.clear()
    stok_uyari_temizlik_onay = False
    await message.reply("✅ All stock alerts deleted.")

# ==================== İSTATİSTİK ====================
@dp.message_handler(commands=['istatistik'])
async def istatistik(message: types.Message):
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        veriler = satirlar[1:]
        toplam_islem = len(veriler)
        
        malzeme_sayilari = {}
        for row in veriler:
            if len(row) >= 3 and row[2] != "-":
                for m in row[2].split(','):
                    parcalar = m.strip().split()
                    if len(parcalar) >= 3:
                        malzeme = " ".join(parcalar[2:])
                        malzeme_sayilari[malzeme] = malzeme_sayilari.get(malzeme, 0) + 1
        
        en_cok = sorted(malzeme_sayilari.items(), key=lambda x: x[1], reverse=True)[:5]
        
        istatistik = f"📊 **STATISTICS**\n\n"
        istatistik += f"📝 Total operations: {toplam_islem}\n\n"
        istatistik += f"🔧 Most used materials:\n"
        for malzeme, sayi in en_cok:
            istatistik += f"   • {malzeme}: {sayi} times\n"
        
        await message.reply(istatistik)
    except Exception as e:
        await message.reply(f"❌ Statistics unavailable: {e}")

# ==================== GÜNLÜK RAPOR ====================
@dp.message_handler(commands=['rapor_gunluk'])
async def rapor_gunluk(message: types.Message):
    bugun = tarih_format()
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        gunun_islemleri = [row for row in satirlar[1:] if len(row) >= 1 and row[0] == bugun]
        if not gunun_islemleri:
            await message.reply(f"📅 **{bugun} DAILY REPORT**\n\nNo operations today.")
            return
        
        rapor = f"📅 **{bugun} DAILY REPORT**\n\n"
        rapor += f"📝 Total operations: {len(gunun_islemleri)}\n\n"
        for row in gunun_islemleri[:15]:
            rapor += f"• {row[1]}: {row[2][:50]}\n"
        await message.reply(rapor)
    except Exception as e:
        await message.reply(f"❌ Report unavailable: {e}")

# ==================== AYLIK RAPOR ====================
@dp.message_handler(commands=['rapor_aylik'])
async def rapor_aylik(message: types.Message):
    ay_param = message.get_args()
    if not ay_param:
        await message.reply("Example: /rapor_aylik 05-2026")
        return
    
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ No records yet.")
            return
        
        veriler = satirlar[1:]
        
        ay_kontrol1 = f"{ay_param[3:]}-{ay_param[:2]}"
        ay_kontrol2 = f"-{ay_param[3:]}-{ay_param[:2]}"
        ay_kontrol3 = ay_param
        
        ay_kayitlari = []
        for row in veriler:
            if len(row) >= 1:
                if ay_kontrol1 in row[0] or ay_kontrol2 in row[0] or ay_kontrol3 in row[0]:
                    ay_kayitlari.append(row)
        
        if not ay_kayitlari:
            await message.reply(f"❌ No operations found for {ay_param}.")
            return
        
        toplam_islem = len(ay_kayitlari)
        islem_turleri = {}
        malzeme_kullanimlari = {}
        toplam_miktar = 0
        miktar_sayac = 0
        
        for row in ay_kayitlari:
            tur = row[1] if len(row) > 1 else "Unknown"
            islem_turleri[tur] = islem_turleri.get(tur, 0) + 1
            
            if len(row) > 2 and row[2] != "-":
                parcalar = row[2].split()
                if len(parcalar) >= 3:
                    try:
                        miktar = float(parcalar[0].replace(',', '.'))
                        malzeme = " ".join(parcalar[2:])
                        toplam_miktar += miktar
                        miktar_sayac += 1
                        malzeme_kullanimlari[malzeme] = malzeme_kullanimlari.get(malzeme, 0) + 1
                    except:
                        pass
        
        en_cok_malzeme = max(malzeme_kullanimlari.items(), key=lambda x: x[1])[0] if malzeme_kullanimlari else "None"
        ortalama_miktar = toplam_miktar / miktar_sayac if miktar_sayac > 0 else 0
        
        ay_adi = ay_param
        rapor = f"📊 **{ay_adi} MONTHLY REPORT**\n\n"
        rapor += f"📝 Total operations: {toplam_islem}\n"
        rapor += f"🔧 Most used material: {en_cok_malzeme}\n"
        rapor += f"📦 Average usage: {ortalama_miktar:.1f} gr\n\n"
        rapor += f"📋 Operation types:\n"
        for tur, sayi in sorted(islem_turleri.items(), key=lambda x: x[1], reverse=True):
            rapor += f"   • {tur}: {sayi} times\n"
        
        await message.reply(rapor)
        
    except Exception as e:
        await message.reply(f"❌ Report unavailable: {e}")

# ==================== GRAFİK ====================
@dp.message_handler(commands=['grafik'])
async def grafik(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Example: /grafik NPK\n\nShows stock usage history of a material.")
        return
    
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        kayitlar = []
        for row in satirlar[1:]:
            if len(row) >= 3 and param.lower() in row[2].lower():
                kayitlar.append(row)
        
        if not kayitlar:
            await message.reply(f"❌ No history found for '{param}'.")
            return
        
        sonlar = kayitlar[-10:][::-1]
        grafik = f"📊 **'{param.upper()}' STOCK GRAPH (Last 10 uses)**\n\n"
        for row in sonlar:
            grafik += f"📅 {row[0]}: {row[2]}\n"
        
        await message.reply(grafik)
    except Exception as e:
        await message.reply(f"❌ Graph unavailable: {e}")

# ==================== HATIRLATMA ====================
@dp.message_handler(commands=['hatirlat'])
async def hatirlat(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Example: /hatirlat 30-07-2026 10:00 Water")
        return
    
    parcalar = param.split(maxsplit=2)
    if len(parcalar) < 3:
        await message.reply("Format: /hatirlat dd-mm-yyyy hour:min task")
        return
    
    tarih, saat, islem = parcalar
    if hatirlatma_ekle(tarih, saat, islem):
        await message.reply(f"✅ Reminder added!\n📅 {tarih} {saat}\n📝 {islem}")
    else:
        await message.reply("❌ Error.")

@dp.message_handler(commands=['hatirlatmalar'])
async def list_hatirlatmalar(message: types.Message):
    try:
        with open('reminders.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("No reminders yet. Use /hatirlat to add one.")
            return
        
        bekleyenler = []
        for i, row in enumerate(satirlar[1:], 1):
            if len(row) >= 4 and row[3] == "bekliyor":
                bekleyenler.append((i, row))
        
        if not bekleyenler:
            await message.reply("✅ No pending reminders.")
            return
        
        mesaj = "📅 **PENDING REMINDERS (with ID)**\n\n"
        for i, row in bekleyenler:
            mesaj += f"**ID: {i}** | {row[0]} {row[1]} - {row[2]}\n"
        await message.reply(mesaj[:4000])
    except:
        await message.reply("File read error. Does reminders.csv exist?")

@dp.message_handler(commands=['hatirlat_sil'])
async def hatirlat_sil(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Example: /hatirlat_sil 1\n\nGet ID from /hatirlatmalar")
        return
    
    try:
        with open('reminders.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ No reminders.")
            return
        
        idx = int(param)
        if idx < 1 or idx >= len(satirlar):
            await message.reply("❌ Invalid ID.")
            return
        
        silinen = satirlar.pop(idx)
        with open('reminders.csv', 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(satirlar)
        
        await message.reply(f"✅ Reminder deleted:\n{silinen[0]} {silinen[1]} - {silinen[2]}")
    except:
        await message.reply("❌ Error occurred.")

# ==================== KAYDET ====================
@dp.message_handler(commands=['kaydet'])
async def kaydet(message: types.Message):
    global son_kayit_geri_al
    islem = message.get_args()
    if not islem:
        await message.reply("Example: /kaydet 5 gr NPK or /kaydet Greenhouse installed")
        return
    
    parcalar = islem.split()
    if len(parcalar) >= 3 and parcalar[0].replace('.', '').replace(',', '').isdigit():
        try:
            miktar = float(parcalar[0].replace(',', '.'))
            birim = parcalar[1]
            malzeme_aranan = " ".join(parcalar[2:])
        except:
            history_ekle("Note", islem, "-", "-")
            await message.reply(f"✅ Note saved:\n📝 {islem}")
            return
        
        stoklar = stok_oku()
        eslesenler = malzeme_bul(malzeme_aranan, stoklar)
        
        if not eslesenler:
            history_ekle("Note", islem, "-", "-")
            await message.reply(f"✅ Note saved (material not found):\n📝 {islem}")
            return
        
        if len(eslesenler) > 1:
            liste = "\n".join([f"• {item.get('Malzeme / Alet')}" for item in eslesenler[:5]])
            await message.reply(f"⚠️ Multiple materials found for '{malzeme_aranan}':\n\n{liste}\n\nPlease use full name.\n\nNote still saved.")
            history_ekle("Note", islem, "-", "-")
            return
        
        item = eslesenler[0]
        malzeme_adi = item.get('Malzeme / Alet')
        
        try:
            kalan_str = str(item['Kalan Miktar']).replace(',', '.').strip()
            if kalan_str == 'Stok bol':
                item['Kalan Miktar'] = 'Stok bol'
                stok_kaydet(stoklar)
                
                son_kayit_geri_al = {
                    'malzeme': malzeme_adi,
                    'eski_kalan': 'Stok bol',
                    'kullanilan': miktar,
                    'birim': birim
                }
                
                history_ekle("Usage", malzeme_adi, miktar, birim)
                await message.reply(f"✅ {miktar:.1f} {birim} {malzeme_adi} used. (Unlimited stock)")
                return
            
            kalan = float(kalan_str)
            if kalan >= miktar:
                yeni_kalan = kalan - miktar
                eski_kalan = kalan
                item['Kalan Miktar'] = str(yeni_kalan).replace('.', ',')
                kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
                item['Kullanılan'] = str(kullanilan + miktar).replace('.', ',')
                stok_kaydet(stoklar)
                
                son_kayit_geri_al = {
                    'malzeme': malzeme_adi,
                    'eski_kalan': eski_kalan,
                    'kullanilan': miktar,
                    'birim': birim
                }
                
                history_ekle("Usage", malzeme_adi, miktar, birim)
                
                uyari_var, esik, uyari_birimi = stok_uyari_kontrol(malzeme_adi, yeni_kalan, birim)
                if uyari_var:
                    await message.reply(f"✅ {miktar:.1f} {birim} {malzeme_adi} used.\n📊 Remaining: {yeni_kalan:.1f} {birim}\n\n⚠️ **STOCK ALERT!** {malzeme_adi} below {esik} {uyari_birimi}!")
                else:
                    await message.reply(f"✅ {miktar:.1f} {birim} {malzeme_adi} used.\n📊 Remaining: {yeni_kalan:.1f} {birim}")
                return
            else:
                await message.reply(f"❌ Insufficient stock! Remaining: {kalan:.1f} {birim}\n\nNote still saved.")
                history_ekle("Note", islem, "-", "-")
                return
        except Exception as e:
            await message.reply(f"❌ Error: {e}\n\nNote still saved.")
            history_ekle("Note", islem, "-", "-")
            return
    
    else:
        history_ekle("Note", islem, "-", "-")
        await message.reply(f"✅ Note saved:\n📝 {islem}")
        return

# ==================== KAYDET GERİ AL (ONAYLI) ====================
@dp.message_handler(commands=['kaydet_geri_al'])
async def kaydet_geri_al(message: types.Message):
    global silinecek_kayit_id, silinecek_kayit_hepsi, son_kayit_geri_al
    param = message.get_args()
    
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ No records to undo.")
            return
        
        basliklar = satirlar[0]
        veriler = satirlar[1:]
        
        if not veriler:
            await message.reply("❌ No records to undo.")
            return
        
        if param and param.isdigit():
            kayit_id = int(param)
            if kayit_id < 1 or kayit_id > len(veriler):
                await message.reply(f"❌ Invalid ID. Enter 1-{len(veriler)}.\n\nUse /gecmis to see IDs.")
                return
            
            idx = kayit_id - 1
            silinecek_kayit_id = (idx, veriler[idx], kayit_id)
            
            await message.reply(f"⚠️ **WARNING!**\n\n"
                               f"Record ID: {kayit_id} will be deleted:\n"
                               f"📅 {veriler[idx][0]} - {veriler[idx][1]}\n"
                               f"📝 {veriler[idx][2][:200]}\n\n"
                               f"**This action is IRREVERSIBLE!**\n\n"
                               f"Type `/kaydet_evet` within 30 seconds to confirm.")
            
            await asyncio.sleep(30)
            if silinecek_kayit_id == (idx, veriler[idx], kayit_id):
                silinecek_kayit_id = None
                await message.reply("⏰ Deletion cancelled.")
            return
        
        elif param and param.lower() == 'hepsi':
            silinecek_kayit_hepsi = veriler.copy()
            await message.reply(f"⚠️ **WARNING!**\n\n"
                               f"ALL history records will be deleted ({len(veriler)} records).\n\n"
                               f"**This action is IRREVERSIBLE!**\n\n"
                               f"Type `/kaydet_evet` within 30 seconds to confirm.")
            await asyncio.sleep(30)
            if silinecek_kayit_hepsi:
                silinecek_kayit_hepsi = None
                await message.reply("⏰ Deletion cancelled.")
            return
        
        son_islem = veriler[-1]
        kayit_id = len(veriler)
        silinecek_kayit_id = (len(veriler)-1, son_islem, kayit_id)
        
        await message.reply(f"⚠️ **WARNING!**\n\n"
                           f"LAST record will be deleted:\n"
                           f"📅 {son_islem[0]} - {son_islem[1]}\n"
                           f"📝 {son_islem[2][:200]}\n\n"
                           f"**This action is IRREVERSIBLE!**\n\n"
                           f"Type `/kaydet_evet` within 30 seconds to confirm.")
        
        await asyncio.sleep(30)
        if silinecek_kayit_id == (len(veriler)-1, son_islem, kayit_id):
            silinecek_kayit_id = None
            await message.reply("⏰ Deletion cancelled.")
        
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@dp.message_handler(commands=['kaydet_evet'])
async def kaydet_evet(message: types.Message):
    global silinecek_kayit_id, silinecek_kayit_hepsi, son_kayit_geri_al
    
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ No records to delete.")
            silinecek_kayit_id = None
            silinecek_kayit_hepsi = None
            return
        
        basliklar = satirlar[0]
        veriler = satirlar[1:]
        
        if silinecek_kayit_hepsi:
            with open('history.csv', 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(basliklar)
            await message.reply(f"✅ All history records deleted.")
            son_kayit_geri_al = None
            silinecek_kayit_hepsi = None
            return
        
        if silinecek_kayit_id:
            idx, silinen_islem, kayit_id = silinecek_kayit_id
            if idx < len(veriler):
                veriler.pop(idx)
                
                if son_kayit_geri_al and son_kayit_geri_al.get('malzeme') and silinen_islem[1] == "Usage":
                    stoklar = stok_oku()
                    for item in stoklar:
                        if son_kayit_geri_al['malzeme'].lower() in item.get('Malzeme / Alet', '').lower():
                            if son_kayit_geri_al['eski_kalan'] == 'Stok bol':
                                item['Kalan Miktar'] = 'Stok bol'
                            else:
                                item['Kalan Miktar'] = str(son_kayit_geri_al['eski_kalan']).replace('.', ',')
                            kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
                            item['Kullanılan'] = str(kullanilan - son_kayit_geri_al['kullanilan']).replace('.', ',')
                            stok_kaydet(stoklar)
                            break
                    son_kayit_geri_al = None
                
                with open('history.csv', 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(basliklar)
                    writer.writerows(veriler)
                
                await message.reply(f"✅ Record ID {kayit_id} deleted:\n📅 {silinen_islem[0]} - {silinen_islem[1]}\n📝 {silinen_islem[2][:200]}")
                silinecek_kayit_id = None
                return
        
        await message.reply("❌ No record found to delete.")
        silinecek_kayit_id = None
        
    except Exception as e:
        await message.reply(f"❌ Error: {e}")
        silinecek_kayit_id = None
        silinecek_kayit_hepsi = None

# ==================== STOK ====================
@dp.message_handler(commands=['stok'])
async def stok(message: types.Message):
    param = message.get_args()
    stoklar = stok_oku()
    
    if not stoklar:
        await message.reply("❌ Stock file cannot be read or empty.")
        return
    
    if param:
        eslesenler = malzeme_bul(param, stoklar)
        
        if not eslesenler:
            await message.reply(f"❌ '{param}' not found.")
            return
        
        if len(eslesenler) == 1:
            item = eslesenler[0]
            cevap = f"📦 **{item.get('Malzeme / Alet')}**\n"
            cevap += f"📊 Remaining: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
            cevap += f"📝 Task: {item.get('Görevi / Not', '-')}\n\n"
            
            try:
                with open('history.csv', 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    satirlar = list(reader)
                
                kayitlar = []
                for row in satirlar[1:]:
                    if len(row) >= 3 and param.lower() in row[2].lower():
                        kayitlar.append(row)
                
                if kayitlar:
                    cevap += "📜 **ALL USAGES:**\n"
                    for row in kayitlar:
                        cevap += f"   • {row[0]}: {row[2]}\n"
                else:
                    cevap += "📜 **No usage history.**"
            except:
                cevap += "📜 History unavailable."
            
            await message.reply(cevap)
        else:
            cevap = f"🔍 **Materials matching '{param}':**\n\n"
            for item in eslesenler[:10]:
                cevap += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
            await message.reply(cevap)
    else:
        mesaj = "📦 **INVENTORY LIST**\n\n"
        for item in stoklar[:30]:
            mesaj += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
        await message.reply(mesaj)

# ==================== EKLE ====================
@dp.message_handler(commands=['ekle'])
async def ekle_envanter(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Example: /ekle NPK;1000;gr;Fertilizer\n\nFormat: Name;Amount;Unit;Task")
        return
    
    parcalar = param.split(';')
    if len(parcalar) < 3:
        await message.reply("Format: Name;Amount;Unit;Task\nExample: NewFertilizer;500;gr;Test")
        return
    
    malzeme_adi = parcalar[0].strip()
    miktar = parcalar[1].strip()
    birim = parcalar[2].strip()
    gorev = parcalar[3].strip() if len(parcalar) > 3 else "-"
    
    stoklar = stok_oku()
    
    for item in stoklar:
        if item.get('Malzeme / Alet', '').lower() == malzeme_adi.lower():
            await message.reply(f"❌ '{malzeme_adi}' already exists in inventory.")
            return
    
    if birim.lower() in ['ml', 'l', 'litre']:
        kategori = 'Sıvı'
    elif birim.lower() in ['adet']:
        kategori = 'Alet'
    else:
        kategori = 'Katı'
    
    yeni_kayit = {
        'Kategori': kategori,
        'Malzeme / Alet': malzeme_adi,
        'Başlangıç Miktarı': miktar,
        'Kullanılan': '0',
        'Kalan Miktar': miktar,
        'Birim': birim,
        'Görevi / Not': gorev
    }
    
    stoklar.append(yeni_kayit)
    
    if stok_kaydet(stoklar):
        await message.reply(f"✅ **'{malzeme_adi}'** added to inventory!\n\n📦 Amount: {miktar} {birim}\n📝 Task: {gorev}")
        history_ekle("ADDED TO INVENTORY", malzeme_adi, miktar, birim)
    else:
        await message.reply("❌ Error while adding.")

# ==================== SİLME ====================
@dp.message_handler(commands=['sil'])
async def sil_stok(message: types.Message):
    global silinecek_malzeme
    param = message.get_args()
    if not param:
        await message.reply("Example: /sil Test")
        return
    
    stoklar = stok_oku()
    eslesenler = malzeme_bul(param, stoklar)
    
    if not eslesenler:
        await message.reply(f"❌ '{param}' not found.")
        return
    
    if len(eslesenler) > 1:
        liste = "\n".join([f"• {item.get('Malzeme / Alet')}" for item in eslesenler[:5]])
        await message.reply(f"⚠️ Multiple materials found for '{param}':\n\n{liste}\n\nPlease use full name.")
        return
    
    silinecek_malzeme = eslesenler[0]
    await message.reply(f"⚠️ **{silinecek_malzeme.get('Malzeme / Alet')}** will be deleted?\n\n"
                       f"📊 Amount: {silinecek_malzeme.get('Kalan Miktar')} {silinecek_malzeme.get('Birim')}\n\n"
                       f"**This action is IRREVERSIBLE!**\n\n"
                       f"Type `/evet` within 30 seconds to confirm.")
    await asyncio.sleep(30)
    if silinecek_malzeme:
        silinecek_malzeme = None
        await message.reply("⏰ Deletion cancelled.")

@dp.message_handler(commands=['evet'])
async def evet_sil(message: types.Message):
    global silinecek_malzeme
    if not silinecek_malzeme:
        await message.reply("❌ No material to delete. Use /sil first.")
        return
    
    stoklar = stok_oku()
    malzeme_adi = silinecek_malzeme.get('Malzeme / Alet')
    miktar = silinecek_malzeme.get('Kalan Miktar')
    birim = silinecek_malzeme.get('Birim')
    
    yeni_stoklar = [item for item in stoklar if item.get('Malzeme / Alet') != malzeme_adi]
    
    if stok_kaydet(yeni_stoklar):
        await message.reply(f"✅ **'{malzeme_adi}'** deleted from inventory.\n\n📊 Amount: {miktar} {birim}")
        history_ekle("DELETED FROM INVENTORY", malzeme_adi, miktar, birim)
    else:
        await message.reply("❌ Error during deletion.")
    
    silinecek_malzeme = None

# ==================== pH EKLE ====================
@dp.message_handler(commands=['ph_ekle'])
async def ph_ekle(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Example: /ph_ekle 1 6.5\n\nAdd note: /ph_ekle 1 6.5 Mud test")
        return
    
    parcalar = param.split(maxsplit=2)
    if len(parcalar) < 2:
        await message.reply("Format: /ph_ekle can_no ph [note]")
        return
    
    teneke = parcalar[0]
    ph = parcalar[1]
    not_metni = parcalar[2] if len(parcalar) > 2 else "Added by bot"
    
    try:
        with open('ph_records.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih_format(), teneke, "-", ph, not_metni])
        await message.reply(f"✅ pH record added!\n📅 {tarih_format()} - Can {teneke} - pH {ph}\n📝 {not_metni}")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

# ==================== pH SORGULA ====================
@dp.message_handler(commands=['ph'])
async def ph_sorgula(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Example: /ph 1 - Latest pH\n/ph 1 hepsi - All pH records")
        return
    
    parcalar = param.split()
    teneke_no = parcalar[0]
    tumu = len(parcalar) > 1 and parcalar[1].lower() == 'hepsi'
    
    try:
        with open('ph_records.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=',')
            kayitlar = [row for row in reader if row.get('Teneke_No', '').strip() == teneke_no]
        
        if not kayitlar:
            await message.reply(f"❌ No pH records for can {teneke_no}.")
            return
        
        if tumu:
            mesaj = f"📊 **Can {teneke_no} - ALL pH RECORDS**\n\n"
            for k in sorted(kayitlar, key=lambda x: x.get('Tarih', ''), reverse=True):
                not_str = f" - {k.get('Not', '')}" if k.get('Not') else ""
                bolge_str = f" ({k.get('Bolge', '-')})" if k.get('Bolge') and k.get('Bolge') != '-' else ""
                mesaj += f"📅 {k['Tarih']}: pH {k['pH']}{bolge_str}{not_str}\n"
                if len(mesaj) > 3800:
                    mesaj += "\n*Continue with /ph 1 devam*"
                    break
            await message.reply(mesaj)
        else:
            en_son = max(kayitlar, key=lambda x: x.get('Tarih', ''))
            not_str = f"\n📝 Note: {en_son.get('Not', '-')}" if en_son.get('Not') else ""
            bolge_str = f"📍 Region: {en_son.get('Bolge', '-')}\n" if en_son.get('Bolge') and en_son.get('Bolge') != '-' else ""
            await message.reply(
                f"📊 **Can {teneke_no} - Latest pH**\n"
                f"📅 {en_son['Tarih']}\n"
                f"🔬 pH: {en_son['pH']}\n"
                f"{bolge_str}{not_str}"
            )
    except Exception as e:
        await message.reply(f"Error: {e}")

# ==================== TÜM TENEKELERİN TÜM pH ====================
@dp.message_handler(commands=['ph_tumu'])
async def ph_tumu(message: types.Message):
    try:
        with open('ph_records.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=',')
            tum_kayitlar = list(reader)
        
        if not tum_kayitlar:
            await message.reply("❌ No pH records.")
            return
        
        tenekeler = {}
        for row in tum_kayitlar:
            teneke = row.get('Teneke_No', 'Unknown')
            if teneke not in tenekeler:
                tenekeler[teneke] = []
            tenekeler[teneke].append(row)
        
        cevap = "📊 **ALL CANS - ALL pH RECORDS**\n\n"
        
        for teneke in sorted(tenekeler.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            cevap += f"🔹 **Can {teneke}**\n"
            kayitlar = sorted(tenekeler[teneke], key=lambda x: x.get('Tarih', ''), reverse=True)
            for k in kayitlar[:10]:
                not_str = f" - {k.get('Not', '')}" if k.get('Not') else ""
                bolge_str = f" ({k.get('Bolge', '-')})" if k.get('Bolge') and k.get('Bolge') != '-' else ""
                cevap += f"   📅 {k['Tarih']}: pH {k['pH']}{bolge_str}{not_str}\n"
            if len(kayitlar) > 10:
                cevap += f"   *Total {len(kayitlar)} records*\n"
            cevap += "\n"
            
            if len(cevap) > 3800:
                await message.reply(cevap)
                cevap = ""
        
        if cevap:
            await message.reply(cevap)
            
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

# ==================== pH SİLME ====================
@dp.message_handler(commands=['ph_sil'])
async def ph_sil(message: types.Message):
    global silinecek_ph_kayitlari
    param = message.get_args()
    if not param:
        await message.reply("Example:\n/ph_sil 1 - Delete last pH\n/ph_sil 1 hepsi - Delete all pH records\n/ph_sil 1 19-05-2026 - Delete by date")
        return
    
    parcalar = param.split()
    teneke_no = parcalar[0]
    
    try:
        with open('ph_records.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ No records to delete.")
            return
        
        basliklar = satirlar[0]
        veriler = satirlar[1:]
        
        teneke_kayitlari = []
        for i, row in enumerate(veriler):
            if len(row) > 1 and row[1] == teneke_no:
                teneke_kayitlari.append((i, row))
        
        if not teneke_kayitlari:
            await message.reply(f"❌ No pH records for can {teneke_no}.")
            return
        
        if len(parcalar) > 1 and parcalar[1].lower() == 'hepsi':
            silinecek_ph_kayitlari = teneke_kayitlari
            await message.reply(f"⚠️ **WARNING!**\n\n"
                               f"ALL pH records for can {teneke_no} will be deleted ({len(teneke_kayitlari)} records).\n\n"
                               f"**This action is IRREVERSIBLE!**\n\n"
                               f"Type `/ph_evet` within 30 seconds to confirm.")
            await asyncio.sleep(30)
            if silinecek_ph_kayitlari == teneke_kayitlari:
                silinecek_ph_kayitlari = None
                await message.reply("⏰ Deletion cancelled.")
            return
        
        if len(parcalar) > 1:
            tarih = parcalar[1]
            bulunan = None
            for i, row in teneke_kayitlari:
                if len(row) > 0 and row[0] == tarih:
                    bulunan = (i, row)
                    break
            
            if not bulunan:
                await message.reply(f"❌ No record found for can {teneke_no} on {tarih}.")
                return
            
            silinen = veriler.pop(bulunan[0])
            with open('ph_records.csv', 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(basliklar)
                writer.writerows(veriler)
            
            await message.reply(f"✅ pH record deleted:\n📅 {silinen[0]} - Can {silinen[1]} - pH {silinen[3]}")
            return
        
        son_kayit = teneke_kayitlari[-1]
        veriler.pop(son_kayit[0])
        
        with open('ph_records.csv', 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(basliklar)
            writer.writerows(veriler)
        
        await message.reply(f"✅ Latest pH record deleted:\n📅 {son_kayit[1][0]} - Can {son_kayit[1][1]} - pH {son_kayit[1][3]}")
        
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@dp.message_handler(commands=['ph_evet'])
async def ph_evet(message: types.Message):
    global silinecek_ph_kayitlari
    if not silinecek_ph_kayitlari:
        await message.reply("❌ No records to delete. Use /ph_sil first.")
        return
    
    try:
        with open('ph_records.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        basliklar = satirlar[0]
        veriler = satirlar[1:]
        
        indeksler = sorted([i for i, _ in silinecek_ph_kayitlari], reverse=True)
        for idx in indeksler:
            veriler.pop(idx)
        
        with open('ph_records.csv', 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(basliklar)
            writer.writerows(veriler)
        
        await message.reply(f"✅ All pH records for can {silinecek_ph_kayitlari[0][1][1]} deleted.")
        silinecek_ph_kayitlari = None
    except Exception as e:
        await message.reply(f"❌ Error: {e}")
        silinecek_ph_kayitlari = None

# ==================== GEÇMİŞ ====================
@dp.message_handler(commands=['gecmis'])
async def gecmis(message: types.Message):
    param = message.get_args()
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("📜 No records yet.")
            return
        
        veriler = satirlar[1:]
        
        if not param:
            sonlar = veriler[-10:][::-1]
            mesaj = "📜 **LAST 10 RECORDS (with ID)**\n\n"
            for i, row in enumerate(sonlar, 1):
                kayit_id = len(veriler) - i + 1
                mesaj += f"**ID: {kayit_id}** | 📅 {row[0]} - {row[1]}\n   {row[2][:100]}\n\n"
            await message.reply(mesaj[:4000])
        
        elif param.lower() == 'hepsi':
            for i in range(0, len(veriler), 10):
                blok = veriler[i:i+10]
                mesaj = "📜 **ALL RECORDS (with ID)**\n\n"
                for j, row in enumerate(blok):
                    kayit_id = i + j + 1
                    mesaj += f"**ID: {kayit_id}** | 📅 {row[0]} - {row[1]}\n   {row[2][:100]}\n\n"
                await message.reply(mesaj[:4000])
        
        else:
            tarih_kayitlari = [(i+1, row) for i, row in enumerate(veriler) if row[0] == param]
            
            if not tarih_kayitlari and '-' in param:
                parcalar = param.split('-')
                if len(parcalar) == 3:
                    if len(parcalar[0]) == 4:
                        ters_param = f"{parcalar[2]}-{parcalar[1]}-{parcalar[0]}"
                        tarih_kayitlari = [(i+1, row) for i, row in enumerate(veriler) if row[0] == ters_param]
                    else:
                        ters_param = f"{parcalar[2]}-{parcalar[1]}-{parcalar[0]}"
                        tarih_kayitlari = [(i+1, row) for i, row in enumerate(veriler) if row[0] == ters_param]
            
            if not tarih_kayitlari:
                await message.reply(f"❌ No records found for {param}.\n\nTry: /gecmis 14-05-2026 or /gecmis 2026-05-14")
                return
            
            mesaj = f"📜 **RECORDS FOR {param} (with ID)**\n\n"
            for kayit_id, row in tarih_kayitlari[:20]:
                mesaj += f"**ID: {kayit_id}** | 📅 {row[0]} - {row[1]}\n   {row[2][:100]}\n\n"
            await message.reply(mesaj[:4000])
            
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

# ==================== GEÇMİŞ SİLME ====================
@dp.message_handler(commands=['gecmis_sil'])
async def gecmis_sil(message: types.Message):
    global silinecek_gecmis_id, silinecek_gecmis_hepsi
    param = message.get_args()
    if not param:
        await message.reply("Example:\n/gecmis_sil 5 - Delete by ID (see IDs with /gecmis)\n/gecmis_sil hepsi - Delete all history")
        return
    
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ No records to delete.")
            return
        
        basliklar = satirlar[0]
        veriler = satirlar[1:]
        
        if param.lower() == 'hepsi':
            silinecek_gecmis_hepsi = True
            await message.reply(f"⚠️ **WARNING!**\n\n"
                               f"ALL history records will be deleted ({len(veriler)} records).\n\n"
                               f"**This action is IRREVERSIBLE!**\n\n"
                               f"Type `/gecmis_evet` within 30 seconds to confirm.")
            await asyncio.sleep(30)
            if silinecek_gecmis_hepsi:
                silinecek_gecmis_hepsi = None
                await message.reply("⏰ Deletion cancelled.")
            return
        
        try:
            kayit_id = int(param)
            if kayit_id < 1 or kayit_id > len(veriler):
                await message.reply(f"❌ Invalid ID. Enter 1-{len(veriler)}.")
                return
            
            idx = kayit_id - 1
            silinecek_gecmis_id = (idx, veriler[idx])
            await message.reply(f"⚠️ **WARNING!**\n\n"
                               f"Record ID: {kayit_id} will be deleted:\n"
                               f"📅 {veriler[idx][0]} - {veriler[idx][1]}\n"
                               f"📝 {veriler[idx][2][:200]}\n\n"
                               f"**This action is IRREVERSIBLE!**\n\n"
                               f"Type `/gecmis_evet` within 30 seconds to confirm.")
            await asyncio.sleep(30)
            if silinecek_gecmis_id == (idx, veriler[idx]):
                silinecek_gecmis_id = None
                await message.reply("⏰ Deletion cancelled.")
            return
        except ValueError:
            await message.reply("❌ ID must be a number. Example: /gecmis_sil 5")
            
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@dp.message_handler(commands=['gecmis_evet'])
async def gecmis_evet(message: types.Message):
    global silinecek_gecmis_id, silinecek_gecmis_hepsi
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        basliklar = satirlar[0]
        veriler = satirlar[1:]
        
        if silinecek_gecmis_hepsi:
            with open('history.csv', 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(basliklar)
            await message.reply("✅ All history records deleted.")
            silinecek_gecmis_hepsi = None
            return
        
        if silinecek_gecmis_id:
            idx, silinen = silinecek_gecmis_id
            veriler.pop(idx)
            with open('history.csv', 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(basliklar)
                writer.writerows(veriler)
            await message.reply(f"✅ Record deleted:\n📅 {silinen[0]} - {silinen[1]}\n📝 {silinen[2][:200]}")
            silinecek_gecmis_id = None
            return
        
        await message.reply("❌ No record to delete. Use /gecmis_sil first.")
        
    except Exception as e:
        await message.reply(f"❌ Error: {e}")
        silinecek_gecmis_id = None
        silinecek_gecmis_hepsi = None

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
import os
import logging
import csv
import re
import asyncio
import zipfile
import io
import requests
from datetime import datetime, timedelta
from openai import OpenAI
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")

# Geçici hafızalar
silinecek_malzeme = None
son_kayit_geri_al = None
stok_uyarilari = {}
ph_uyarilari = {}
baglam_metinleri = {}

# Agnes AI istemcisi
client = OpenAI(
    base_url="https://apihub.agnes-ai.com/v1",
    api_key=AGNES_API_KEY
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ==================== YARDIMCI FONKSİYONLAR ====================
def tarih_format():
    return datetime.now().strftime("%d-%m-%Y")

def saat_format():
    return datetime.now().strftime("%H:%M")

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
    
    # Son 200 satırı tut
    satirlar = baglam_metinleri[user_id].split('\n')
    if len(satirlar) > 200:
        baglam_metinleri[user_id] = '\n'.join(satirlar[-200:])

# ==================== STOK FONKSİYONLARI ====================
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

def stok_kaydet(stok_listesi):
    try:
        with open('inventory.csv', 'w', encoding='utf-8-sig', newline='') as f:
            fieldnames = ['Kategori', 'Malzeme / Alet', 'Başlangıç Miktarı', 'Kullanılan', 'Kalan Miktar', 'Birim', 'Görevi / Not']
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
            writer.writeheader()
            writer.writerows(stok_listesi)
        return True
    except Exception as e:
        print(f"Stok kayıt hatası: {e}")
        return False

def stoktan_dus(malzeme_adi, miktar, birim):
    global son_kayit_geri_al
    stoklar = stok_oku()
    for item in stoklar:
        if malzeme_adi.lower() in item['Malzeme / Alet'].lower():
            try:
                kalan = float(str(item['Kalan Miktar']).replace(',', '.'))
                miktar_float = float(str(miktar).replace(',', '.'))
                if kalan >= miktar_float:
                    yeni_kalan = kalan - miktar_float
                    eski_kalan = kalan
                    item['Kalan Miktar'] = str(yeni_kalan).replace('.', ',')
                    kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
                    item['Kullanılan'] = str(kullanilan + miktar_float).replace('.', ',')
                    stok_kaydet(stoklar)
                    
                    # GERİ ALMA İÇİN KAYDET
                    son_kayit_geri_al = {
                        'malzeme': malzeme_adi,
                        'eski_kalan': eski_kalan,
                        'kullanilan': miktar_float,
                        'birim': birim,
                        'islem_metni': f"{miktar} {birim} {malzeme_adi}"
                    }
                    
                    if malzeme_adi in stok_uyarilari and yeni_kalan <= stok_uyarilari[malzeme_adi]:
                        return True, f"{yeni_kalan:.1f} {birim} (⚠️ UYARI: {malzeme_adi} stok eşiğin altında!)"
                    return True, f"{yeni_kalan:.1f} {birim}"
                else:
                    return False, f"Yetersiz stok! Kalan: {kalan:.1f} {birim}"
            except:
                return False, "Miktar okunamadı"
    return False, f"'{malzeme_adi}' envanterde bulunamadı"

def kayit_geri_al():
    global son_kayit_geri_al
    if not son_kayit_geri_al:
        return False, "Geri alınacak kayıt yok"
    
    stoklar = stok_oku()
    for item in stoklar:
        if son_kayit_geri_al['malzeme'].lower() in item['Malzeme / Alet'].lower():
            item['Kalan Miktar'] = str(son_kayit_geri_al['eski_kalan']).replace('.', ',')
            kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
            item['Kullanılan'] = str(kullanilan - son_kayit_geri_al['kullanilan']).replace('.', ',')
            stok_kaydet(stoklar)
            malzeme = son_kayit_geri_al['malzeme']
            miktar = son_kayit_geri_al['kullanilan']
            birim = son_kayit_geri_al['birim']
            son_kayit_geri_al = None
            return True, f"Geri alındı: {malzeme} +{miktar:.1f} {birim}"
    return False, "Malzeme bulunamadı"

def parse_metin(text):
    pattern = r'(\d+(?:\.\d+)?)\s*([a-zA-Zğüşıöç]+)\s+(.+?)(?=\s*\+|\s*$)'
    malzemeler = []
    matches = re.findall(pattern, text, re.IGNORECASE)
    for miktar, birim, ad in matches:
        malzemeler.append({'miktar': miktar, 'birim': birim, 'ad': ad.strip()})
    return malzemeler

def islemi_kaydet(islem_metni, malzemeler):
    try:
        tarih = tarih_format()
        malzeme_str = ", ".join([f"{m['miktar']} {m['birim']} {m['ad']}" for m in malzemeler])
        with open('history.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih, islem_metni, malzeme_str, "-", "Bot tarafından eklendi"])
        return True
    except Exception as e:
        print(f"History kayıt hatası: {e}")
        return False

# ==================== HATIRLATICI FONKSİYONLARI ====================
def hatirlatma_ekle(tarih, saat, islem):
    try:
        with open('reminders.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih, saat, islem, "bekliyor"])
        return True
    except Exception as e:
        print(f"Hatırlatma ekleme hatası: {e}")
        return False

# ==================== HAVA DURUMU ====================
def hava_durumu(yer):
    try:
        url = f"https://wttr.in/{yer}?format=%C+%t+%w+%h&m"
        response = requests.get(url, timeout=10)
        return response.text.strip()
    except:
        return "Hava durumu alınamadı."

# ==================== AGNES AI ====================
def ask_agnes(question, user_id=None):
    try:
        messages = []
        if user_id and user_id in baglam_metinleri and baglam_metinleri[user_id]:
            baglam = baglam_metinleri[user_id][-3000:]
            messages.append({"role": "system", "content": f"Önceki konuşma geçmişi:\n{baglam}"})
        messages.append({"role": "user", "content": question})
        response = client.chat.completions.create(
            model="agnes-2.0-flash",
            messages=messages,
            max_tokens=2000
        )
        cevap = response.choices[0].message.content
        if len(cevap) > 4000:
            cevap = cevap[:3950] + "\n\n[Devamı kesildi...]"
        return cevap
    except Exception as e:
        return f"Agnes hatası: {str(e)[:100]}"

# ==================== RAPORLAMA ====================
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

def aylik_rapor(ay_param):
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        ay_map = {'01': 'Ocak', '02': 'Şubat', '03': 'Mart', '04': 'Nisan', '05': 'Mayıs', '06': 'Haziran',
                  '07': 'Temmuz', '08': 'Ağustos', '09': 'Eylül', '10': 'Ekim', '11': 'Kasım', '12': 'Aralık'}
        
        if re.match(r'\d{2}-\d{4}', ay_param):
            ay_no = ay_param[:2]
            yil = ay_param[3:]
            ay_adi = ay_map.get(ay_no, ay_no)
            aradigimiz = f"-{ay_no}-{yil}"
        else:
            ters_ay_map = {v.lower(): k for k, v in ay_map.items()}
            ay_no = ters_ay_map.get(ay_param.lower())
            if not ay_no:
                return f"Geçersiz ay: {ay_param}. Örnek: 05-2026 veya Mayıs"
            yil = datetime.now().strftime("%Y")
            ay_adi = ay_param.capitalize()
            aradigimiz = f"-{ay_no}-{yil}"
        
        ay_kayitlari = [row for row in satirlar[1:] if len(row) >= 1 and aradigimiz in row[0]]
        
        if not ay_kayitlari:
            return f"{ay_adi} {yil} ayında işlem bulunamadı."
        
        rapor = f"📊 **{ay_adi} {yil} AYLIK RAPOR**\n\n"
        rapor += f"📝 Toplam işlem: {len(ay_kayitlari)}\n\n"
        rapor += f"🔧 İşlemler:\n"
        for row in ay_kayitlari[:15]:
            rapor += f"   • {row[0]} - {row[1]}\n"
        if len(ay_kayitlari) > 15:
            rapor += f"\n*Toplam {len(ay_kayitlari)} işlem var. Detay için /gecmis {ay_param}"
        return rapor
    except Exception as e:
        return f"Rapor alınamadı: {e}"

# ==================== TÜM MESAJLARI YAKALA (BAĞLAM İÇİN) ====================
@dp.message_handler()
async def her_mesaj(message: types.Message):
    """Komut olmayan tüm mesajları bağlama ekle"""
    user_id = str(message.from_user.id)
    text = message.text
    if text and not text.startswith('/'):
        baglam_guncelle(user_id, text)
        await message.reply(f"📝 Not alındı. /sor ile soru sorabilir veya /kaydet ile işlem yapabilirsin.")

# ==================== KOMUTLAR ====================
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan** hazır!\n\n📌 **Komutlar:**\n"
                         "/sor [soru] - Agnes AI'ya sor\n"
                         "/stok [malzeme] - Stok sorgula\n"
                         "/kaydet [işlem] - Stok düş ve kaydet\n"
                         "/kaydet_geri_al - Son kaydı geri al\n"
                         "/redo - Geri alınanı yeniden yap\n"
                         "/ekle Ad;Miktar;Birim;Görev - Yeni malzeme ekle\n"
                         "/ph [teneke] - pH sorgula\n/ph_ekle [teneke] [pH] [tarih] - pH ekle\n"
                         "/gecmis [ay/hepsi] - Geçmiş işlemler\n"
                         "/sil [malzeme] - Malzeme sil\n"
                         "/hatirlat [gun-ay-yil] [saat] [islem] - Hatırlatma ekle\n"
                         "/hatirlat_sil [id] - Hatırlatma sil\n"
                         "/hatirlatmalar - Bekleyen hatırlatmalar\n"
                         "/rapor_gunluk - Bugünün raporu\n"
                         "/rapor_aylik [05-2026] - Aylık rapor\n"
                         "/istatistik - Genel istatistik\n"
                         "/stok_uyari [malzeme] [esik] - Stok uyarısı\n"
                         "/ph_uyari [teneke] [esik_ph] - pH uyarısı\n"
                         "/hava [yer] - Hava durumu\n"
                         "/yedekle - CSV'leri yedekle\n"
                         "/baglam_al - Konuşma özetini al\n"
                         "/baglam_sifirla - Bağlamı sıfırla\n"
                         "/baglam_goster - Bağlamı göster\n"
                         "/test - Bot testi")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

@dp.message_handler(commands=['sor'])
async def sor(message: types.Message):
    soru = message.get_args()
    if not soru:
        await message.reply("Bir soru yaz: /sor [soru]")
        return
    user_id = str(message.from_user.id)
    msg = await message.reply("🤔 Agnes düşünüyor...")
    cevap = ask_agnes(soru, user_id)
    baglam_guncelle(user_id, soru, cevap)
    for parca in mesaj_parcala(cevap):
        await bot.send_message(chat_id=message.chat.id, text=f"🤖 **Agnes AI:**\n\n{parca}")

@dp.message_handler(commands=['stok'])
async def stock(message: types.Message):
    param = message.get_args()
    if param:
        stoklar = stok_oku()
        for item in stoklar:
            if param.lower() in item['Malzeme / Alet'].lower():
                await message.reply(f"📦 **{item['Malzeme / Alet']}**\nKalan: {item['Kalan Miktar']} {item['Birim']}\nGörevi: {item['Görevi / Not']}")
                return
        await message.reply(f"❌ '{param}' bulunamadı.")
    else:
        stoklar = stok_oku()
        mesaj = "📦 **ENVANTER LISTESI**\n\n"
        for item in stoklar[:20]:
            mesaj += f"• {item['Malzeme / Alet']}: {item['Kalan Miktar']} {item['Birim']}\n"
        await message.reply(mesaj)

@dp.message_handler(commands=['kaydet'])
async def kaydet(message: types.Message):
    islem = message.get_args()
    if not islem:
        await message.reply("Örnek: /kaydet 10 lt su + 5 gr NPK")
        return
    msg = await message.reply("📝 İşlem işleniyor...")
    malzemeler = parse_metin(islem)
    if not malzemeler:
        await bot.edit_message_text("⚠️ Malzeme bulunamadı.", chat_id=message.chat.id, message_id=msg.message_id)
        return
    sonuclar = []
    for m in malzemeler:
        if m['ad'].lower() in ['su', 'water']:
            sonuclar.append(f"• {m['miktar']} {m['birim']} {m['ad']}: ℹ️ stoktan düşülmez")
        else:
            basari, mesaj_sonuc = stoktan_dus(m['ad'], m['miktar'], m['birim'])
            if basari:
                sonuclar.append(f"• {m['miktar']} {m['birim']} {m['ad']}: ✅ düşüldü ({mesaj_sonuc})")
            else:
                sonuclar.append(f"• {m['miktar']} {m['birim']} {m['ad']}: ❌ {mesaj_sonuc}")
    islemi_kaydet("Sulama/Gübreleme", malzemeler)
    await bot.edit_message_text(f"✅ **İşlem kaydedildi!**\n\n📝 {islem}\n\n" + "\n".join(sonuclar), chat_id=message.chat.id, message_id=msg.message_id)

@dp.message_handler(commands=['kaydet_geri_al'])
async def kaydet_geri_al(message: types.Message):
    basari, mesaj = kayit_geri_al()
    await message.reply(f"✅ {mesaj}" if basari else f"❌ {mesaj}")

@dp.message_handler(commands=['redo'])
async def redo(message: types.Message):
    global son_kayit_geri_al
    if not son_kayit_geri_al:
        await message.reply("❌ Yeniden yapılacak işlem yok.")
        return
    stoklar = stok_oku()
    for item in stoklar:
        if son_kayit_geri_al['malzeme'].lower() in item['Malzeme / Alet'].lower():
            kalan = float(str(item['Kalan Miktar']).replace(',', '.'))
            yeni_kalan = kalan - son_kayit_geri_al['kullanilan']
            if yeni_kalan < 0:
                await message.reply("❌ Stok yetersiz.")
                return
            item['Kalan Miktar'] = str(yeni_kalan).replace('.', ',')
            kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
            item['Kullanılan'] = str(kullanilan + son_kayit_geri_al['kullanilan']).replace('.', ',')
            stok_kaydet(stoklar)
            await message.reply(f"✅ İşlem yeniden yapıldı:\n{son_kayit_geri_al['malzeme']} -{son_kayit_geri_al['kullanilan']} {son_kayit_geri_al['birim']}")
            with open('history.csv', 'a', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([tarih_format(), "REDO", son_kayit_geri_al['islem_metni'], "-", "Bot ile yeniden yapıldı"])
            return
    await message.reply("❌ Malzeme bulunamadı.")

@dp.message_handler(commands=['ekle'])
async def ekle_envanter(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ekle Malzeme;1000;gr;Görevi")
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
        if item['Malzeme / Alet'].lower() == malzeme_adi.lower():
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
        await message.reply(f"✅ **'{malzeme_adi}'** eklendi!\n📦 {miktar} {birim}\n📝 {gorev}")
    else:
        await message.reply("❌ Ekleme hatası.")

@dp.message_handler(commands=['ph_ekle'])
async def ph_ekle(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ph_ekle 1 6.5 11-06-2026")
        return
    parcalar = param.split()
    if len(parcalar) < 2:
        await message.reply("Format: /ph_ekle teneke_no pH [tarih]")
        return
    teneke = parcalar[0]
    ph = parcalar[1]
    tarih = parcalar[2] if len(parcalar) > 2 else tarih_format()
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
            content = f.read()
            if ';' in content[:100]:
                delimiter = ';'
            else:
                delimiter = ','
            f.seek(0)
            reader = csv.DictReader(f, delimiter=delimiter)
            teneke_kayitlari = []
            for row in reader:
                if row.get('Teneke_No', '').strip() == teneke_no:
                    teneke_kayitlari.append(row)
        if not teneke_kayitlari:
            await message.reply(f"❌ Teneke {teneke_no} için pH kaydı yok.")
            return
        if tumu:
            mesaj = f"📊 **Teneke {teneke_no} - TÜM pH ÖLÇÜMLERİ**\n\n"
            for kayit in sorted(teneke_kayitlari, key=lambda x: x.get('Tarih', ''), reverse=True):
                mesaj += f"📅 {kayit['Tarih']}: pH {kayit['pH']} ({kayit.get('Bolge', '-')})\n"
            for parca in mesaj_parcala(mesaj):
                await message.reply(parca)
        else:
            en_son = max(teneke_kayitlari, key=lambda x: x.get('Tarih', ''))
            await message.reply(f"📊 **Teneke {teneke_no} - Son pH**\n📅 {en_son['Tarih']}\n🔬 pH: {en_son['pH']}\n📍 {en_son.get('Bolge', '-')}")
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
            son_kayitlar = veriler[-10:][::-1]
            mesaj = "📜 **SON 10 İŞLEM**\n\n"
            for row in son_kayitlar:
                if len(row) >= 3:
                    mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2]}\n\n"
            await message.reply(mesaj[:4000])
        elif param.lower() == 'hepsi':
            for i in range(0, len(veriler), 15):
                blok = veriler[i:i+15]
                mesaj = "📜 **GEÇMİŞ İŞLEMLER**\n\n"
                for row in blok:
                    if len(row) >= 3:
                        mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:100]}\n\n"
                await message.reply(mesaj[:4000])
        else:
            ay_map = {'01': 'Ocak', '02': 'Şubat', '03': 'Mart', '04': 'Nisan', '05': 'Mayıs', '06': 'Haziran',
                      '07': 'Temmuz', '08': 'Ağustos', '09': 'Eylül', '10': 'Ekim', '11': 'Kasım', '12': 'Aralık'}
            ters_ay_map = {v.lower(): k for k, v in ay_map.items()}
            if re.match(r'\d{2}-\d{4}', param):
                aradigimiz = f"-{param[:2]}-{param[3:]}"
            elif param.lower() in ters_ay_map:
                ay_no = ters_ay_map[param.lower()]
                yil = datetime.now().strftime("%Y")
                aradigimiz = f"-{ay_no}-{yil}"
            else:
                await message.reply("Geçersiz format. Örnek: /gecmis 05-2026 veya /gecmis mayıs")
                return
            ay_kayitlari = [row for row in veriler if aradigimiz in row[0]]
            if not ay_kayitlari:
                await message.reply(f"❌ {param} için kayıt bulunamadı.")
                return
            mesaj = f"📜 **{param} İŞLEMLERİ**\n\n"
            for row in ay_kayitlari:
                if len(row) >= 3:
                    mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:100]}\n\n"
            await message.reply(mesaj[:4000])
    except Exception as e:
        await message.reply(f"Hata: {e}")

@dp.message_handler(commands=['sil'])
async def sil_stok(message: types.Message):
    global silinecek_malzeme
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /sil NPK")
        return
    stoklar = stok_oku()
    bulunan = None
    for item in stoklar:
        if param.lower() in item['Malzeme / Alet'].lower():
            bulunan = item
            break
    if not bulunan:
        await message.reply(f"❌ '{param}' bulunamadı.")
        return
    silinecek_malzeme = bulunan
    await message.reply(f"⚠️ **{bulunan['Malzeme / Alet']}** silinsin mi? 30 saniye içinde `/evet` yaz.")
    await asyncio.sleep(30)
    if silinecek_malzeme == bulunan:
        silinecek_malzeme = None
        await message.reply("⏰ Silme iptal edildi.")

@dp.message_handler(commands=['evet'])
async def evet_sil(message: types.Message):
    global silinecek_malzeme
    if not silinecek_malzeme:
        await message.reply("❌ Silme onayı yok.")
        return
    stoklar = stok_oku()
    malzeme_adi = silinecek_malzeme['Malzeme / Alet']
    yeni_stoklar = [item for item in stoklar if item['Malzeme / Alet'] != malzeme_adi]
    if stok_kaydet(yeni_stoklar):
        await message.reply(f"✅ **'{malzeme_adi}'** silindi.")
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
        await message.reply(f"✅ Hatırlatma eklendi!\n📅 {tarih} {saat}\n📝 {islem}\n\n⚠️ Not: Otomatik mesaj için zamanlayıcı henüz aktif değil.")
    else:
        await message.reply("❌ Hata.")

@dp.message_handler(commands=['hatirlat_sil'])
async def hatirlat_sil(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /hatirlat_sil 1\n\nID'yi /hatirlatmalar ile görebilirsin.")
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
        await message.reply("❌ Hata oluştu.")

@dp.message_handler(commands=['hatirlatmalar'])
async def list_hatirlatmalar(message: types.Message):
    try:
        with open('reminders.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        if len(satirlar) <= 1:
            await message.reply("Henüz hatırlatma yok. /hatirlat ile ekleyebilirsin.")
            return
        bekleyenler = []
        for i, row in enumerate(satirlar[1:], 1):
            if len(row) >= 4 and row[3] == "bekliyor":
                bekleyenler.append((i, row))
        if not bekleyenler:
            await message.reply("✅ Bekleyen hatırlatma yok.")
            return
        mesaj = "📅 **BEKLEYEN HATIRLATMALAR**\n\n"
        for i, row in bekleyenler:
            mesaj += f"**ID: {i}** | {row[0]} {row[1]} - {row[2]}\n"
        await message.reply(mesaj[:4000])
    except:
        await message.reply("Dosya okuma hatası.")

@dp.message_handler(commands=['rapor_gunluk'])
async def rapor_gunluk(message: types.Message):
    rapor = gunluk_rapor()
    await message.reply(rapor)

@dp.message_handler(commands=['rapor_aylik'])
async def rapor_aylik(message: types.Message):
    ay = message.get_args()
    if not ay:
        await message.reply("Örnek: /rapor_aylik 05-2026 veya /rapor_aylik mayıs")
        return
    rapor = aylik_rapor(ay)
    await message.reply(rapor)

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
            if len(row) >= 3:
                for m in row[2].split(','):
                    malzeme_adi = m.strip().split(' ')[-1] if m.strip() else "bilinmiyor"
                    malzeme_sayilari[malzeme_adi] = malzeme_sayilari.get(malzeme_adi, 0) + 1
        en_cok = sorted(malzeme_sayilari.items(), key=lambda x: x[1], reverse=True)[:5]
        istatistik = f"📊 **GENEL İSTATİSTİK**\n\n"
        istatistik += f"📝 Toplam işlem: {toplam_islem}\n\n"
        istatistik += f"🔧 En çok kullanılan malzemeler:\n"
        for malzeme, sayi in en_cok:
            istatistik += f"   • {malzeme}: {sayi} kez\n"
        await message.reply(istatistik)
    except Exception as e:
        await message.reply(f"İstatistik alınamadı: {e}")

@dp.message_handler(commands=['stok_uyari'])
async def stok_uyari(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /stok_uyari NPK 100")
        return
    parcalar = param.split()
    if len(parcalar) < 2:
        await message.reply("Örnek: /stok_uyari NPK 100")
        return
    malzeme, esik = parcalar[0], float(parcalar[1])
    stok_uyarilari[malzeme] = esik
    await message.reply(f"✅ Uyarı eklendi: {malzeme} {esik} gr altında uyarı verilecek.")

@dp.message_handler(commands=['ph_uyari'])
async def ph_uyari(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ph_uyari 1 6.5")
        return
    parcalar = param.split()
    if len(parcalar) < 2:
        await message.reply("Örnek: /ph_uyari 1 6.5")
        return
    teneke, esik = parcalar[0], float(parcalar[1])
    ph_uyarilari[teneke] = esik
    await message.reply(f"✅ pH uyarısı eklendi: Teneke {teneke} pH {esik} altında/üstünde uyarı verilecek.")

@dp.message_handler(commands=['hava'])
async def hava(message: types.Message):
    yer = message.get_args()
    if not yer:
        yer = "Istanbul"
    durum = hava_durumu(yer)
    await message.reply(f"🌤️ **{yer} HAVA DURUMU**\n\n{durum}\n\n(°C, km/h)")

@dp.message_handler(commands=['yedekle'])
async def yedekle(message: types.Message):
    await message.reply("📦 Yedekleme hazırlanıyor...")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for dosya in ['inventory.csv', 'history.csv', 'ph_records.csv', 'reminders.csv']:
            try:
                zip_file.write(dosya)
            except:
                pass
    zip_buffer.seek(0)
    await message.reply_document(document=('yasemin_yedek.zip', zip_buffer), caption="📦 Yedek dosyaları")

@dp.message_handler(commands=['baglam_al'])
async def baglam_al(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in baglam_metinleri and baglam_metinleri[user_id]:
        for parca in mesaj_parcala(baglam_metinleri[user_id], 4000):
            await message.reply(f"📝 **Konuşma geçmişi:**\n\n{parca}")
    else:
        await message.reply("Henüz konuşma geçmişi yok.")

@dp.message_handler(commands=['baglam_sifirla'])
async def baglam_sifirla(message: types.Message):
    user_id = str(message.from_user.id)
    baglam_metinleri[user_id] = ""
    await message.reply("✅ Konuşma bağlamı sıfırlandı.")

@dp.message_handler(commands=['baglam_goster'])
async def baglam_goster(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in baglam_metinleri and baglam_metinleri[user_id]:
        for parca in mesaj_parcala(baglam_metinleri[user_id], 4000):
            await message.reply(f"📝 **Bağlam:**\n\n{parca}")
    else:
        await message.reply("Henüz bağlam yok.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

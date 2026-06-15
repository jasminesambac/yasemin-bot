import os
import logging
import asyncio
import requests
import json
from datetime import datetime, timedelta
from openai import OpenAI
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import gspread
from oauth2client.service_account import ServiceAccountCredentials

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")
SHEET_ID = os.getenv("SHEET_ID")
CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS")

# Google Sheets bağlantısı
creds_dict = json.loads(CREDENTIALS_JSON)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SHEET_ID)

inventory_sheet = sh.worksheet("inventory")
history_sheet = sh.worksheet("history")
ph_sheet = sh.worksheet("ph_records")
reminders_sheet = sh.worksheet("reminders")

# Global değişkenler
son_kayit_geri_al = None
baglam_metinleri = {}
bekleyen_silme = {}
bekleyen_ekleme = {}
bekleyen_ai = {}
bekleyen_rapor_aylik = {}
bekleyen_grafik = {}
bekleyen_ph_ekle = {}
bekleyen_hatirlat = {}
bekleyen_islem = {}
bekleyen_dus = {}
bekleyen_gecmis_tarih = {}
bekleyen_gecmis_sil = {}
bekleyen_hatirlat_sil = {}
bekleyen_ph_sil = {}

client = OpenAI(base_url="https://apihub.agnes-ai.com/v1", api_key=AGNES_API_KEY)
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ------------------- Yardımcı fonksiyonlar -------------------
def tarih_format():
    return datetime.now().strftime("%d-%m-%Y")

def tarih_convert(tarih_str):
    if not tarih_str:
        return None
    if '-' in tarih_str:
        parcalar = tarih_str.split('-')
        if len(parcalar) == 3:
            if len(parcalar[0]) == 4:
                return f"{parcalar[2]}-{parcalar[1]}-{parcalar[0]}"
    return tarih_str

def mesaj_parcala(metin, uzunluk=4000):
    return [metin[i:i+uzunluk] for i in range(0, len(metin), uzunluk)]

def ask_agnes(question, user_id=None):
    try:
        messages = []
        if user_id and user_id in baglam_metinleri:
            messages.append({"role": "system", "content": f"Önceki konuşma:\n{baglam_metinleri[user_id][-2000:]}"})
        messages.append({"role": "user", "content": question})
        response = client.chat.completions.create(model="agnes-2.0-flash", messages=messages, max_tokens=3000)
        cevap = response.choices[0].message.content
        if user_id:
            baglam_metinleri[user_id] = baglam_metinleri.get(user_id, "") + f"Kullanıcı: {question}\nAsistan: {cevap}\n"
            if len(baglam_metinleri[user_id].split('\n')) > 50:
                baglam_metinleri[user_id] = '\n'.join(baglam_metinleri[user_id].split('\n')[-50:])
        return cevap
    except Exception as e:
        return f"Agnes hatası: {str(e)[:100]}"

def stok_oku():
    try:
        return inventory_sheet.get_all_records()
    except:
        return []

def stok_guncelle(stoklar):
    """Stok tablosunu günceller (temizleme yapar, dikkatli kullan)."""
    try:
        inventory_sheet.clear()
        if stoklar:
            headers = list(stoklar[0].keys())
            inventory_sheet.append_row(headers)
            for row in stoklar:
                inventory_sheet.append_row(list(row.values()))
        return True
    except:
        return False

def stok_ekle(yeni_kayit):
    """Sadece ekleme yapar, mevcut veriyi silmez."""
    stoklar = stok_oku()
    stoklar.append(yeni_kayit)
    return stok_guncelle(stoklar)

def stok_sil(malzeme_adi):
    stoklar = stok_oku()
    yeni_stoklar = [i for i in stoklar if i.get('Malzeme / Alet') != malzeme_adi]
    return stok_guncelle(yeni_stoklar)

def stok_miktar_guncelle(malzeme_adi, yeni_kalan, kullanilan_artis=0):
    stoklar = stok_oku()
    for item in stoklar:
        if item.get('Malzeme / Alet') == malzeme_adi:
            item['Kalan Miktar'] = str(yeni_kalan).replace('.', ',')
            if kullanilan_artis:
                eski = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
                item['Kullanılan'] = str(eski + kullanilan_artis).replace('.', ',')
            return stok_guncelle(stoklar)
    return False

def history_ekle(islem, malzeme, miktar, birim, ph="", not_metni=""):
    try:
        history_sheet.append_row([tarih_format(), islem, f"{miktar} {birim} {malzeme}", ph, not_metni])
        return True
    except:
        return False

def history_oku():
    try:
        return history_sheet.get_all_records()
    except:
        return []

def stoktan_dus(malzeme_adi, miktar, birim, islem_turu, not_metni=""):
    global son_kayit_geri_al
    stoklar = stok_oku()
    for item in stoklar:
        if item.get('Malzeme / Alet') == malzeme_adi:
            try:
                kalan_str = str(item['Kalan Miktar']).replace(',', '.').strip()
                if kalan_str == 'Stok bol':
                    son_kayit_geri_al = {'malzeme': malzeme_adi, 'eski_kalan': 'Stok bol', 'kullanilan': miktar, 'birim': birim}
                    history_ekle(islem_turu, malzeme_adi, miktar, birim, "", not_metni)
                    return True, "Stok bol"
                kalan = float(kalan_str)
                if kalan >= miktar:
                    yeni_kalan = kalan - miktar
                    stok_miktar_guncelle(malzeme_adi, yeni_kalan, miktar)
                    son_kayit_geri_al = {'malzeme': malzeme_adi, 'eski_kalan': kalan, 'kullanilan': miktar, 'birim': birim}
                    history_ekle(islem_turu, malzeme_adi, miktar, birim, "", not_metni)
                    return True, f"{yeni_kalan:.1f}"
                return False, f"Yetersiz! Kalan: {kalan:.1f}"
            except:
                return False, "Hata"
    return False, "Malzeme bulunamadı"

def iptal_menusu(geri):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ İptal", callback_data=geri))
    return kb

# ------------------- Menüler -------------------
def ana_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📦 Stok", callback_data="menu_stok"),
        InlineKeyboardButton("🔬 pH", callback_data="menu_ph"),
        InlineKeyboardButton("📜 Geçmiş", callback_data="menu_gecmis"),
        InlineKeyboardButton("📊 Rapor", callback_data="menu_rapor"),
        InlineKeyboardButton("⏰ Hatırlatma", callback_data="menu_hatirlat"),
        InlineKeyboardButton("🌤️ Hava", callback_data="menu_hava"),
        InlineKeyboardButton("🤖 AI Sor", callback_data="menu_ai"),
        InlineKeyboardButton("💾 Yedekle", callback_data="menu_yedek")
    )
    return kb

def stok_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📋 Stok Listesi", callback_data="stok_liste"),
        InlineKeyboardButton("🔍 Stok Sorgula", callback_data="stok_sorgula_ac"),
        InlineKeyboardButton("⬇️ Stoktan Düş", callback_data="stok_dus"),
        InlineKeyboardButton("➕ Yeni Malzeme Ekle", callback_data="stok_ekle_ac"),
        InlineKeyboardButton("❌ Malzeme Sil", callback_data="stok_sil_ac"),
        InlineKeyboardButton("↩️ Geri Al", callback_data="stok_geri_al"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_ana")
    )
    return kb

def gecmis_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📜 Son 10 İşlem", callback_data="gecmis_son"),
        InlineKeyboardButton("📋 Tüm Geçmiş", callback_data="gecmis_hepsi"),
        InlineKeyboardButton("📅 Tarihli İşlemler", callback_data="gecmis_tarih_ac"),
        InlineKeyboardButton("❌ İşlem Sil", callback_data="gecmis_sil_ac"),
        InlineKeyboardButton("📝 İşlem Ekle", callback_data="islem_ekle"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_ana")
    )
    return kb

def rapor_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📊 Aylık Rapor", callback_data="rapor_aylik_ac"),
        InlineKeyboardButton("📅 Günlük Rapor", callback_data="rapor_gunluk"),
        InlineKeyboardButton("📈 İstatistik", callback_data="rapor_istatistik"),
        InlineKeyboardButton("📉 Stok Grafiği", callback_data="rapor_grafik_ac"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_ana")
    )
    return kb

def hatirlatma_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("➕ Hatırlatma Ekle", callback_data="hatirlat_ekle_ac"),
        InlineKeyboardButton("📋 Bekleyen Hatırlatmalar", callback_data="hatirlat_liste"),
        InlineKeyboardButton("❌ Hatırlatma Sil", callback_data="hatirlat_sil_ac"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_ana")
    )
    return kb

def hava_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🌤️ Anlık Hava", callback_data="hava_anlik_ac"),
        InlineKeyboardButton("📊 Aylık Hava", callback_data="hava_aylik_ac"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_ana")
    )
    return kb

def ai_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🤖 Agnes AI'ya Sor", callback_data="ai_sor_ac"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_ana")
    )
    return kb

def yedekle_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("💾 Yedekle", callback_data="yedekle_yap"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_ana")
    )
    return kb

def ph_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🔬 Son pH", callback_data="ph_son_ac"),
        InlineKeyboardButton("📊 Tüm pH (Tek Teneke)", callback_data="ph_tumu_tek_ac"),
        InlineKeyboardButton("📋 Tüm Tenekelerin Tüm pH", callback_data="ph_tumu"),
        InlineKeyboardButton("➕ pH Ekle", callback_data="ph_ekle_ac"),
        InlineKeyboardButton("❌ pH Sil", callback_data="ph_sil_ac"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_ana")
    )
    return kb

def kategori_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    for k in ["Katı", "Sıvı", "Alet", "Mekanik", "Cihaz"]:
        kb.add(InlineKeyboardButton(k, callback_data=f"kategori_{k}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="stok_menu"))
    return kb

def birim_menu():
    kb = InlineKeyboardMarkup(row_width=3)
    for b in ["gr", "ml", "L", "adet"]:
        kb.add(InlineKeyboardButton(b, callback_data=f"birim_{b}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="stok_ekle_ac"))
    return kb

def malzeme_listesi_menu(malzemeler, page=0, action="sorgula"):
    kb = InlineKeyboardMarkup(row_width=2)
    for item in malzemeler[page*8:(page+1)*8]:
        ad = item.get('Malzeme / Alet', '-')
        kb.add(InlineKeyboardButton(ad[:30], callback_data=f"{action}_{ad}"))
    if page > 0:
        kb.add(InlineKeyboardButton("◀️ Önceki", callback_data=f"page_{action}_{page-1}"))
    if len(malzemeler) > (page+1)*8:
        kb.add(InlineKeyboardButton("Sonraki ▶️", callback_data=f"page_{action}_{page+1}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="stok_menu"))
    return kb

def stoktan_dus_malzeme_menu(malzemeler, page=0):
    kb = InlineKeyboardMarkup(row_width=2)
    for item in malzemeler[page*8:(page+1)*8]:
        ad = item.get('Malzeme / Alet', '-')
        kb.add(InlineKeyboardButton(ad[:30], callback_data=f"dus_malzeme_{ad}"))
    if page > 0:
        kb.add(InlineKeyboardButton("◀️ Önceki", callback_data=f"dus_page_{page-1}"))
    if len(malzemeler) > (page+1)*8:
        kb.add(InlineKeyboardButton("Sonraki ▶️", callback_data=f"dus_page_{page+1}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="stok_menu"))
    return kb

def miktar_menu(malzeme, birim, prefix):
    kb = InlineKeyboardMarkup(row_width=4)
    for m in [1,5,10,20,50,100]:
        kb.add(InlineKeyboardButton(str(m), callback_data=f"{prefix}_miktar_{m}_{malzeme}_{birim}"))
    kb.add(InlineKeyboardButton("✏️ Özel", callback_data=f"{prefix}_ozel_{malzeme}_{birim}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data=f"{prefix}_geri"))
    return kb

def islem_tur_menu(prefix):
    kb = InlineKeyboardMarkup(row_width=2)
    for t in ["Sulama", "Gübreleme", "İlaçlama", "Hasat", "Toprak İşlemi", "Diğer"]:
        kb.add(InlineKeyboardButton(t, callback_data=f"{prefix}_tur_{t}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data=f"{prefix}_miktar_geri"))
    return kb

def tarih_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📅 Bugün", callback_data="tarih_bugun"),
        InlineKeyboardButton("📅 Dün", callback_data="tarih_dun"),
        InlineKeyboardButton("✏️ Özel Tarih", callback_data="tarih_ozel"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_gecmis")
    )
    return kb

def ph_secim_menu():
    kb = InlineKeyboardMarkup(row_width=4)
    for p in ["5.0","5.5","6.0","6.5","7.0","Ölçmedim"]:
        kb.add(InlineKeyboardButton(p, callback_data=f"islem_ph_{p}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="islem_miktar_geri"))
    return kb

def teneke_menu():
    try:
        kayitlar = ph_sheet.get_all_records()
        tenekeler = sorted(set(str(r.get('Teneke_No','')).strip() for r in kayitlar if r.get('Teneke_No')), key=lambda x: int(x) if str(x).isdigit() else 0)
    except:
        tenekeler = []
    kb = InlineKeyboardMarkup(row_width=4)
    for t in tenekeler[:20]:
        kb.add(InlineKeyboardButton(str(t), callback_data=f"ph_teneke_{t}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="menu_ph"))
    return kb

def sehir_menu():
    kb = InlineKeyboardMarkup(row_width=3)
    for s in ["İstanbul","Ankara","İzmir","Bursa","Antalya","Adana","Konya","Trabzon"]:
        kb.add(InlineKeyboardButton(s, callback_data=f"sehir_{s}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="menu_hava"))
    return kb

def hatirlatma_saat_menu():
    kb = InlineKeyboardMarkup(row_width=3)
    for s in ["09:00","12:00","15:00","17:00","20:00"]:
        kb.add(InlineKeyboardButton(s, callback_data=f"hatirlat_saat_{s}"))
    kb.add(InlineKeyboardButton("✏️ Özel", callback_data="hatirlat_saat_ozel"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="hatirlat_ekle_ac"))
    return kb

# ------------------- Komutlar -------------------
@dp.message_handler(commands=['menu','start'])
async def menu(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan**", reply_markup=ana_menu())

@dp.message_handler(commands=['sor'])
async def sor_command(message: types.Message):
    soru = message.get_args()
    if not soru:
        await message.reply("Bir soru yaz: /sor [sorunuz]")
        return
    msg = await message.reply("🤔 Agnes düşünüyor...")
    cevap = ask_agnes(soru, str(message.from_user.id))
    for parca in mesaj_parcala(cevap):
        await message.reply(f"🤖 **Agnes AI:**\n\n{parca}")
    await bot.delete_message(msg.chat.id, msg.message_id)

@dp.message_handler(commands=['kaydet'])
async def kaydet_command(message: types.Message):
    global son_kayit_geri_al
    metin = message.get_args()
    if not metin:
        await message.reply("Örnek: /kaydet 5 gr NPK")
        return
    parcalar = metin.split()
    if len(parcalar) >= 3:
        try:
            miktar = float(parcalar[0].replace(',','.'))
            birim = parcalar[1]
            malzeme = " ".join(parcalar[2:])
            basarili, sonuc = stoktan_dus(malzeme, miktar, birim, "Kullanım", "")
            if basarili:
                await message.reply(f"✅ {miktar} {birim} {malzeme} kullanıldı.\n📊 Kalan: {sonuc} {birim}")
            else:
                await message.reply(f"❌ {sonuc}")
        except:
            history_ekle("Not", metin, "-", "-")
            await message.reply(f"✅ Not kaydedildi: {metin}")
    else:
        history_ekle("Not", metin, "-", "-")
        await message.reply(f"✅ Not kaydedildi: {metin}")

@dp.message_handler(commands=['stok'])
async def stok_command(message: types.Message):
    param = message.get_args()
    stoklar = stok_oku()
    if not stoklar:
        await message.reply("❌ Stok boş")
        return
    if param:
        for item in stoklar:
            if param.lower() in item.get('Malzeme / Alet', '').lower():
                await message.reply(f"📦 **{item.get('Malzeme / Alet')}**\n📊 Kalan: {item.get('Kalan Miktar')} {item.get('Birim')}\n📝 {item.get('Görevi / Not','-')}")
                return
        await message.reply(f"❌ '{param}' bulunamadı")
    else:
        mesaj = "📦 **STOK LİSTESİ**\n\n"
        for item in stoklar[:50]:
            mesaj += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
        for parca in mesaj_parcala(mesaj):
            await message.reply(parca)

@dp.message_handler(commands=['ekle'])
async def ekle_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ekle NPK;1000;gr;Gübre")
        return
    parcalar = param.split(';')
    if len(parcalar) < 3:
        await message.reply("Format: Ad;Miktar;Birim;Görev")
        return
    ad = parcalar[0].strip()
    miktar = parcalar[1].strip()
    birim = parcalar[2].strip()
    gorev = parcalar[3].strip() if len(parcalar)>3 else "-"
    stoklar = stok_oku()
    for item in stoklar:
        if item.get('Malzeme / Alet', '').lower() == ad.lower():
            await message.reply(f"❌ '{ad}' zaten var")
            return
    if birim in ['ml','L']:
        kategori = 'Sıvı'
    elif birim == 'adet':
        kategori = 'Alet'
    else:
        kategori = 'Katı'
    yeni = {'Kategori':kategori, 'Malzeme / Alet':ad, 'Başlangıç Miktarı':miktar, 'Kullanılan':'0', 'Kalan Miktar':miktar, 'Birim':birim, 'Görevi / Not':gorev}
    if stok_ekle(yeni):
        await message.reply(f"✅ **'{ad}'** eklendi!\n📦 {miktar} {birim}\n📝 {gorev}")
        history_ekle("ENVANTERE EKLENDİ", ad, miktar, birim)
    else:
        await message.reply("❌ Hata")

@dp.message_handler(commands=['sil'])
async def sil_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /sil NPK")
        return
    stoklar = stok_oku()
    for item in stoklar:
        if item.get('Malzeme / Alet', '').lower() == param.lower():
            bekleyen_silme[message.from_user.id] = item
            await message.reply(f"⚠️ **{item.get('Malzeme / Alet')}** silinsin mi?\n\n30 saniye içinde /evet yazın")
            await asyncio.sleep(30)
            if message.from_user.id in bekleyen_silme:
                del bekleyen_silme[message.from_user.id]
                await message.reply("⏰ Silme iptal edildi")
            return
    await message.reply(f"❌ '{param}' bulunamadı")

@dp.message_handler(commands=['evet'])
async def evet_command(message: types.Message):
    if message.from_user.id not in bekleyen_silme:
        await message.reply("❌ Silinecek malzeme yok")
        return
    malzeme = bekleyen_silme[message.from_user.id]
    ad = malzeme.get('Malzeme / Alet')
    if stok_sil(ad):
        await message.reply(f"✅ **'{ad}'** silindi")
        history_ekle("ENVANTERDEN SİLİNDİ", ad, "-", "-")
    else:
        await message.reply("❌ Hata")
    del bekleyen_silme[message.from_user.id]

@dp.message_handler(commands=['gecmis'])
async def gecmis_command(message: types.Message):
    param = message.get_args()
    kayitlar = history_oku()
    if not kayitlar:
        await message.reply("📜 Kayıt yok")
        return
    if param and param.lower() != "hepsi":
        aranan_tarih = tarih_convert(param)
        tarih_kayitlari = []
        for idx, r in enumerate(kayitlar):
            if r.get('Tarih','') == aranan_tarih:
                tarih_kayitlari.append((idx+1, r))
        if not tarih_kayitlari:
            await message.reply(f"❌ {param} tarihinde kayıt yok")
            return
        mesaj = f"📜 **{param} TARİHİNDEKİ İŞLEMLER**\n\n"
        for kayit_id, r in tarih_kayitlari[:15]:
            mesaj += f"**ID: {kayit_id}** | 📅 {r.get('Tarih','-')} - {r.get('Islem','-')}\n   {r.get('Kullanilan_Malzeme_Miktar','-')}\n\n"
        for parca in mesaj_parcala(mesaj):
            await message.reply(parca)
        return
    sonlar = kayitlar[-15:][::-1]
    mesaj = "📜 **SON 15 İŞLEM (ID ile)**\n\n"
    for i, r in enumerate(sonlar, 1):
        kayit_id = len(kayitlar) - i + 1
        mesaj += f"**ID: {kayit_id}** | 📅 {r.get('Tarih','-')} - {r.get('Islem','-')}\n   {r.get('Kullanilan_Malzeme_Miktar','-')}\n\n"
    for parca in mesaj_parcala(mesaj):
        await message.reply(parca)

@dp.message_handler(commands=['rapor_gunluk'])
async def rapor_gunluk_command(message: types.Message):
    bugun = tarih_format()
    kayitlar = history_oku()
    gun = [r for r in kayitlar if r.get('Tarih','') == bugun]
    if not gun:
        await message.reply(f"📅 {bugun} - İşlem yok")
        return
    mesaj = f"📅 **{bugun} GÜNLÜK RAPOR**\n\n📝 Toplam: {len(gun)}\n\n"
    for r in gun[:10]:
        mesaj += f"• {r.get('Islem','-')}: {r.get('Kullanilan_Malzeme_Miktar','-')}\n"
    await message.reply(mesaj)

@dp.message_handler(commands=['istatistik'])
async def istatistik_command(message: types.Message):
    kayitlar = history_oku()
    if not kayitlar:
        await message.reply("📊 Veri yok")
        return
    sayilar = {}
    for r in kayitlar:
        tur = r.get('Islem','Bilinmiyor')
        sayilar[tur] = sayilar.get(tur,0)+1
    mesaj = "📊 **İSTATİSTİK**\n\n"
    for tur, sayi in sorted(sayilar.items(), key=lambda x: x[1], reverse=True):
        mesaj += f"• {tur}: {sayi} kez\n"
    await message.reply(mesaj)

@dp.message_handler(commands=['yedekle'])
async def yedekle_command(message: types.Message):
    await message.reply("📦 Yedek hazırlanıyor...")
    try:
        import io, csv, zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, sheet in [("inventory.csv", inventory_sheet), ("history.csv", history_sheet), ("ph_records.csv", ph_sheet), ("reminders.csv", reminders_sheet)]:
                data = sheet.get_all_values()
                csv_buffer = io.StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerows(data)
                zf.writestr(name, csv_buffer.getvalue().encode('utf-8-sig'))
        zip_buffer.seek(0)
        await message.reply_document(document=('yasemin_yedek.zip', zip_buffer), caption="📦 Yedek")
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@dp.message_handler(commands=['hava'])
async def hava_command(message: types.Message):
    sehir = message.get_args() or "Istanbul"
    try:
        r = requests.get(f"https://wttr.in/{sehir}?format=%C+%t+%w+%h&m&lang=tr", timeout=10)
        durum = r.text.strip()
        await message.reply(f"🌤️ **{sehir.upper()} ŞU ANKİ HAVA**\n\n{durum}\n(°C, km/h, %)")
    except:
        await message.reply("❌ Hava alınamadı")

@dp.message_handler(commands=['ph_ekle'])
async def ph_ekle_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ph_ekle 1 6.5")
        return
    parcalar = param.split()
    if len(parcalar) < 2:
        await message.reply("Format: teneke pH")
        return
    try:
        ph_sheet.append_row([tarih_format(), parcalar[0], "-", parcalar[1], "Bot ile eklendi"])
        await message.reply(f"✅ pH eklendi: Teneke {parcalar[0]} - pH {parcalar[1]}")
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

# ------------------- Callback handler -------------------
@dp.callback_query_handler(lambda c: True)
async def process_callback(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    data = callback_query.data
    msg = callback_query.message
    user_id = callback_query.from_user.id

    if data == "menu_ana":
        await bot.edit_message_text("🌿 **Yasemin Asistan**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=ana_menu())
        return
    elif data == "menu_stok":
        await bot.edit_message_text("📦 **STOK YÖNETİMİ**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=stok_menu())
        return
    elif data == "menu_gecmis":
        await bot.edit_message_text("📜 **GEÇMİŞ YÖNETİMİ**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=gecmis_menu())
        return
    elif data == "menu_rapor":
        await bot.edit_message_text("📊 **RAPORLAR**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=rapor_menu())
        return
    elif data == "menu_hatirlat":
        await bot.edit_message_text("⏰ **HATIRLATMALAR**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=hatirlatma_menu())
        return
    elif data == "menu_hava":
        await bot.edit_message_text("🌤️ **HAVA DURUMU**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=hava_menu())
        return
    elif data == "menu_ai":
        bekleyen_ai[user_id] = True
        await bot.edit_message_text("🤖 **Agnes AI'ya Sor**\n\nSormak istediğin soruyu yaz:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_ai"))
        return
    elif data == "menu_yedek":
        await bot.edit_message_text("💾 **YEDEKLEME**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=yedekle_menu())
        return
    elif data == "menu_ph":
        await bot.edit_message_text("🔬 **pH YÖNETİMİ**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=ph_menu())
        return

    elif data == "stok_liste":
        stoklar = stok_oku()
        if not stoklar:
            await bot.edit_message_text("❌ Stok boş", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        mesaj = "📦 **ENVANTER LİSTESİ**\n\n"
        for i in stoklar:
            mesaj += f"• {i.get('Malzeme / Alet')}: {i.get('Kalan Miktar')} {i.get('Birim')}\n"
        for parca in mesaj_parcala(mesaj):
            await bot.send_message(chat_id=msg.chat.id, text=parca)
        await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        return

    elif data == "stok_sorgula_ac":
        stoklar = stok_oku()
        await bot.edit_message_text("🔍 **Malzeme seçin:**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=malzeme_listesi_menu(stoklar,0,"sorgula"))
        return
    elif data.startswith("sorgula_"):
        ad = data.replace("sorgula_","")
        stoklar = stok_oku()
        for i in stoklar:
            if i.get('Malzeme / Alet') == ad:
                await bot.edit_message_text(f"📦 **{ad}**\n📊 Kalan: {i.get('Kalan Miktar')} {i.get('Birim')}\n📝 {i.get('Görevi / Not','-')}", chat_id=msg.chat.id, message_id=msg.message_id)
                return
        await bot.edit_message_text(f"❌ {ad} bulunamadı", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "stok_sil_ac":
        stoklar = stok_oku()
        await bot.edit_message_text("❌ **Silinecek malzemeyi seçin:**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=malzeme_listesi_menu(stoklar,0,"sil"))
        return
    elif data.startswith("sil_"):
        ad = data.replace("sil_","")
        stoklar = stok_oku()
        for i in stoklar:
            if i.get('Malzeme / Alet') == ad:
                bekleyen_silme[user_id] = i
                await bot.edit_message_text(f"⚠️ **{ad}** silinsin mi?\n\nBu işlem GERİ DÖNÜŞÜMSÜZDÜR!\n\n30 saniye içinde /evet yazın.", chat_id=msg.chat.id, message_id=msg.message_id)
                await asyncio.sleep(30)
                if user_id in bekleyen_silme:
                    del bekleyen_silme[user_id]
                return
        await bot.edit_message_text(f"❌ {ad} bulunamadı", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "stok_ekle_ac":
        bekleyen_ekleme[user_id] = {}
        await bot.edit_message_text("➕ **YENİ MALZEME EKLE**\n\nKategori seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=kategori_menu())
        return
    elif data.startswith("kategori_"):
        kat = data.replace("kategori_","")
        bekleyen_ekleme[user_id]['kategori'] = kat
        await bot.edit_message_text(f"📝 Kategori: {kat}\n\nMalzeme adını yazın:", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data.startswith("birim_"):
        birim = data.replace("birim_","")
        bekleyen_ekleme[user_id]['birim'] = birim
        await bot.edit_message_text(f"📝 Birim: {birim}\n\nGörev / Not yazın:", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "stok_dus":
        stoklar = stok_oku()
        await bot.edit_message_text("⬇️ **STOKTAN DÜŞ**\n\nMalzeme seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=stoktan_dus_malzeme_menu(stoklar,0))
        return
    elif data.startswith("dus_page_"):
        page = int(data.replace("dus_page_",""))
        stoklar = stok_oku()
        await bot.edit_message_text("⬇️ **STOKTAN DÜŞ**\n\nMalzeme seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=stoktan_dus_malzeme_menu(stoklar,page))
        return
    elif data.startswith("dus_malzeme_"):
        ad = data.replace("dus_malzeme_","")
        stoklar = stok_oku()
        for i in stoklar:
            if i.get('Malzeme / Alet') == ad:
                birim = i.get('Birim','gr')
                bekleyen_dus[user_id] = {'malzeme': ad, 'birim': birim}
                await bot.edit_message_text(f"📦 **{ad}**\n\nMiktar seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=miktar_menu(ad, birim, "dus"))
                return
        await bot.edit_message_text(f"❌ {ad} bulunamadı", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data.startswith("dus_miktar_"):
        parts = data.split("_")
        if len(parts) >= 6:
            miktar = float(parts[3])
            ad = parts[4]
            birim = parts[5]
            bekleyen_dus[user_id]['miktar'] = miktar
            await bot.edit_message_text(f"📦 {ad} - {miktar} {birim}\n\nİşlem türü seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=islem_tur_menu("dus"))
        return
    elif data.startswith("dus_tur_"):
        tur = data.replace("dus_tur_","")
        bekleyen_dus[user_id]['tur'] = tur
        await bot.edit_message_text(f"📝 Not yazın (isteğe bağlı):", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "stok_geri_al":
        global son_kayit_geri_al
        if not son_kayit_geri_al:
            await bot.edit_message_text("❌ Geri alınacak işlem yok", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        stoklar = stok_oku()
        for i in stoklar:
            if son_kayit_geri_al['malzeme'].lower() in i.get('Malzeme / Alet','').lower():
                if son_kayit_geri_al['eski_kalan'] == 'Stok bol':
                    i['Kalan Miktar'] = 'Stok bol'
                else:
                    i['Kalan Miktar'] = str(son_kayit_geri_al['eski_kalan']).replace('.',',')
                kull = float(str(i.get('Kullanılan','0')).replace(',','.'))
                i['Kullanılan'] = str(kull - son_kayit_geri_al['kullanilan']).replace('.',',')
                stok_guncelle(stoklar)
                await bot.edit_message_text(f"✅ Geri alındı:\n📦 {son_kayit_geri_al['malzeme']}\n➕ +{son_kayit_geri_al['kullanilan']} {son_kayit_geri_al['birim']}", chat_id=msg.chat.id, message_id=msg.message_id)
                son_kayit_geri_al = None
                return
        await bot.edit_message_text("❌ Malzeme bulunamadı", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    elif data == "gecmis_son":
        kayitlar = history_oku()
        if not kayitlar:
            await bot.edit_message_text("📜 Kayıt yok", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        sonlar = kayitlar[-10:][::-1]
        mesaj = "📜 **SON 10 İŞLEM (ID ile)**\n\n"
        for i, r in enumerate(sonlar,1):
            kayit_id = len(kayitlar) - i + 1
            mesaj += f"**ID: {kayit_id}** | 📅 {r.get('Tarih','-')} - {r.get('Islem','-')}\n   {r.get('Kullanilan_Malzeme_Miktar','-')}\n\n"
        for parca in mesaj_parcala(mesaj):
            await bot.send_message(chat_id=msg.chat.id, text=parca)
        await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "gecmis_hepsi":
        kayitlar = history_oku()
        if not kayitlar:
            await bot.edit_message_text("📜 Kayıt yok", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        mesaj = "📜 **SON 30 İŞLEM (ID ile)**\n\n"
        for idx, r in enumerate(kayitlar[-30:][::-1],1):
            kayit_id = len(kayitlar) - idx + 1
            mesaj += f"**ID: {kayit_id}** | 📅 {r.get('Tarih','-')} - {r.get('Islem','-')}\n   {r.get('Kullanilan_Malzeme_Miktar','-')}\n\n"
        for parca in mesaj_parcala(mesaj):
            await bot.send_message(chat_id=msg.chat.id, text=parca)
        await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "gecmis_tarih_ac":
        bekleyen_gecmis_tarih[user_id] = True
        await bot.edit_message_text("📅 **Tarih yazın (örn: 14-06-2026):**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_gecmis"))
        return
    elif data == "gecmis_sil_ac":
        bekleyen_gecmis_sil[user_id] = True
        await bot.edit_message_text("❌ **Silinecek işlemin ID'sini yazın**\n(/gecmis ile ID'leri görebilirsiniz):", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_gecmis"))
        return
    elif data == "islem_ekle":
        bekleyen_islem[user_id] = {}
        await bot.edit_message_text("📝 **İŞLEM EKLE**\n\nTarih seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=tarih_menu())
        return

    elif data == "tarih_bugun":
        if user_id in bekleyen_islem:
            bekleyen_islem[user_id]['tarih'] = tarih_format()
            await bot.edit_message_text(f"📅 Tarih: {tarih_format()}\n\nİşlem türü seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=islem_tur_menu("islem"))
        elif user_id in bekleyen_hatirlat:
            bekleyen_hatirlat[user_id]['tarih'] = tarih_format()
            await bot.edit_message_text(f"📅 Tarih: {tarih_format()}\n\nSaat seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=hatirlatma_saat_menu())
        return
    elif data == "tarih_dun":
        dun = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")
        if user_id in bekleyen_islem:
            bekleyen_islem[user_id]['tarih'] = dun
            await bot.edit_message_text(f"📅 Tarih: {dun}\n\nİşlem türü seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=islem_tur_menu("islem"))
        elif user_id in bekleyen_hatirlat:
            bekleyen_hatirlat[user_id]['tarih'] = dun
            await bot.edit_message_text(f"📅 Tarih: {dun}\n\nSaat seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=hatirlatma_saat_menu())
        return
    elif data == "tarih_ozel":
        if user_id in bekleyen_islem:
            bekleyen_islem[user_id]['tarih_ozel'] = True
            await bot.edit_message_text("📅 **Tarih yazın (örn: 14-06-2026):**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("islem_ekle"))
        elif user_id in bekleyen_hatirlat:
            bekleyen_hatirlat[user_id]['tarih_ozel'] = True
            await bot.edit_message_text("📅 **Tarih yazın (örn: 14-06-2026):**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("hatirlat_ekle_ac"))
        return

    elif data.startswith("islem_tur_"):
        tur = data.replace("islem_tur_","")
        bekleyen_islem[user_id]['tur'] = tur
        stoklar = stok_oku()
        await bot.edit_message_text(f"📋 İşlem: {tur}\n\nMalzeme yazın veya seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=malzeme_listesi_menu(stoklar,0,"islem_malzeme"))
        return
    elif data.startswith("islem_malzeme_"):
        ad = data.replace("islem_malzeme_","")
        stoklar = stok_oku()
        for i in stoklar:
            if i.get('Malzeme / Alet') == ad:
                birim = i.get('Birim','gr')
                bekleyen_islem[user_id]['malzeme'] = ad
                bekleyen_islem[user_id]['birim'] = birim
                await bot.edit_message_text(f"📦 Malzeme: {ad}\n\nMiktar seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=miktar_menu(ad, birim, "islem"))
                return
        await bot.edit_message_text(f"❌ {ad} bulunamadı\n\nLütfen malzeme adını yazın:", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data.startswith("islem_miktar_"):
        parts = data.split("_")
        if len(parts) >= 6:
            miktar = float(parts[3])
            ad = parts[4]
            birim = parts[5]
            bekleyen_islem[user_id]['miktar'] = miktar
            await bot.edit_message_text(f"📦 {ad} - {miktar} {birim}\n\npH seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=ph_secim_menu())
        return
    elif data.startswith("islem_ph_"):
        ph = data.replace("islem_ph_","")
        bekleyen_islem[user_id]['ph'] = ph
        await bot.edit_message_text(f"🔬 pH: {ph}\n\nNot yazın (isteğe bağlı):", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    elif data == "hatirlat_ekle_ac":
        bekleyen_hatirlat[user_id] = {}
        await bot.edit_message_text("⏰ **Hatırlatma Ekle**\n\nTarih seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=tarih_menu())
        return
    elif data == "hatirlat_liste":
        try:
            kayitlar = reminders_sheet.get_all_records()
            bekleyen = [(i,r) for i,r in enumerate(kayitlar,1) if r.get('Durum') == "bekliyor"]
            if not bekleyen:
                await bot.edit_message_text("✅ Bekleyen hatırlatma yok", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            mesaj = "📅 **BEKLEYEN HATIRLATMALAR**\n\n"
            for i,r in bekleyen:
                mesaj += f"**ID: {i}** | {r.get('Tarih')} {r.get('Saat')} - {r.get('Islem')}\n"
            for parca in mesaj_parcala(mesaj):
                await bot.send_message(chat_id=msg.chat.id, text=parca)
            await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "hatirlat_sil_ac":
        bekleyen_hatirlat_sil[user_id] = True
        await bot.edit_message_text("❌ **Silinecek hatırlatmanın ID'sini yazın**\n(/hatirlat_liste ile ID'leri görebilirsiniz):", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_hatirlat"))
        return
    elif data.startswith("hatirlat_saat_"):
        saat = data.replace("hatirlat_saat_","")
        if saat == "ozel":
            bekleyen_hatirlat[user_id]['saat_ozel'] = True
            await bot.edit_message_text("⏰ **Saat yazın (örn: 10:00):**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("hatirlat_ekle_ac"))
        else:
            bekleyen_hatirlat[user_id]['saat'] = saat
            await bot.edit_message_text(f"⏰ Saat: {saat}\n\nHatırlatma metnini yazın:", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    elif data == "rapor_aylik_ac":
        bekleyen_rapor_aylik[user_id] = True
        await bot.edit_message_text("📊 **Ay ve yıl yazın (örn: 05-2026):**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_rapor"))
        return
    elif data == "rapor_gunluk":
        bugun = tarih_format()
        kayitlar = history_oku()
        gun = [r for r in kayitlar if r.get('Tarih','') == bugun]
        if not gun:
            await bot.edit_message_text(f"📅 {bugun} - İşlem yok", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        mesaj = f"📅 **{bugun} GÜNLÜK RAPOR**\n\n📝 Toplam: {len(gun)}\n\n"
        for r in gun[:10]:
            mesaj += f"• {r.get('Islem','-')}: {r.get('Kullanilan_Malzeme_Miktar','-')}\n"
        await bot.edit_message_text(mesaj, chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "rapor_istatistik":
        kayitlar = history_oku()
        if not kayitlar:
            await bot.edit_message_text("📊 Veri yok", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        sayilar = {}
        for r in kayitlar:
            tur = r.get('Islem','Bilinmiyor')
            sayilar[tur] = sayilar.get(tur,0)+1
        mesaj = "📊 **İSTATİSTİK**\n\n"
        for tur, sayi in sorted(sayilar.items(), key=lambda x: x[1], reverse=True):
            mesaj += f"• {tur}: {sayi} kez\n"
        await bot.edit_message_text(mesaj, chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "rapor_grafik_ac":
        bekleyen_grafik[user_id] = True
        await bot.edit_message_text("📉 **Stok Grafiği**\n\nMalzeme adını yazın:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_rapor"))
        return

    elif data == "hava_anlik_ac":
        await bot.edit_message_text("🌤️ **Şehir seçin:**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=sehir_menu())
        return
    elif data == "hava_aylik_ac":
        await bot.edit_message_text("📊 **Aylık Hava Durumu**\n\nŞehir seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=sehir_menu())
        return
    elif data.startswith("sehir_"):
        sehir = data.replace("sehir_","")
        try:
            if "hava_anlik_ac" in str(msg.text):
                r = requests.get(f"https://wttr.in/{sehir}?format=%C+%t+%w+%h&m&lang=tr", timeout=10)
                await bot.edit_message_text(f"🌤️ **{sehir.upper()} ŞU ANKİ HAVA**\n\n{r.text.strip()}\n(°C, km/h, %)", chat_id=msg.chat.id, message_id=msg.message_id)
            else:
                r = requests.get(f"https://wttr.in/{sehir}?m&lang=tr", timeout=10)
                await bot.edit_message_text(f"📊 **{sehir.upper()} AYLIK HAVA**\n\n{r.text.strip()}", chat_id=msg.chat.id, message_id=msg.message_id)
        except:
            await bot.edit_message_text("❌ Hava alınamadı", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    elif data == "yedekle_yap":
        await bot.edit_message_text("📦 Yedek hazırlanıyor...", chat_id=msg.chat.id, message_id=msg.message_id)
        try:
            import io, csv, zipfile
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for name, sheet in [("inventory.csv", inventory_sheet), ("history.csv", history_sheet), ("ph_records.csv", ph_sheet), ("reminders.csv", reminders_sheet)]:
                    data_sheet = sheet.get_all_values()
                    csv_buffer = io.StringIO()
                    writer = csv.writer(csv_buffer)
                    writer.writerows(data_sheet)
                    zf.writestr(name, csv_buffer.getvalue().encode('utf-8-sig'))
            zip_buffer.seek(0)
            await bot.send_document(msg.chat.id, document=('yasemin_yedek.zip', zip_buffer), caption="📦 Yedek")
            await bot.delete_message(msg.chat.id, msg.message_id)
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    elif data == "ph_son_ac":
        try:
            kayitlar = ph_sheet.get_all_records()
            if not kayitlar:
                await bot.edit_message_text("❌ pH kaydı yok", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            tenekeler = sorted(set(str(r.get('Teneke_No','')).strip() for r in kayitlar if r.get('Teneke_No')), key=lambda x: int(x) if str(x).isdigit() else 0)
            await bot.edit_message_text("🔬 **Teneke seçin:**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=teneke_menu())
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data.startswith("ph_teneke_"):
        teneke = data.replace("ph_teneke_","")
        try:
            kayitlar = ph_sheet.get_all_records()
            teneke_kayitlari = [r for r in kayitlar if str(r.get('Teneke_No','')).strip() == teneke]
            if not teneke_kayitlari:
                await bot.edit_message_text(f"❌ Teneke {teneke} için kayıt yok", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            def tarih_parse(t):
                try:
                    return datetime.strptime(t, "%d-%m-%Y")
                except:
                    try:
                        return datetime.strptime(t, "%Y-%m-%d")
                    except:
                        return datetime(2000,1,1)
            en_son = max(teneke_kayitlari, key=lambda x: tarih_parse(x.get('Tarih','01-01-2000')))
            await bot.edit_message_text(f"🔬 **Teneke {teneke} - Son pH**\n📅 {en_son['Tarih']}\n📊 pH: {en_son['pH']}\n📝 {en_son.get('Not','-')}", chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "ph_tumu_tek_ac":
        try:
            kayitlar = ph_sheet.get_all_records()
            if not kayitlar:
                await bot.edit_message_text("❌ pH kaydı yok", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            tenekeler = sorted(set(str(r.get('Teneke_No','')).strip() for r in kayitlar if r.get('Teneke_No')), key=lambda x: int(x) if str(x).isdigit() else 0)
            await bot.edit_message_text("📊 **Teneke seçin (tüm pH):**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=teneke_menu())
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data.startswith("ph_tumu_tek_"):
        teneke = data.replace("ph_tumu_tek_","")
        try:
            kayitlar = ph_sheet.get_all_records()
            teneke_kayitlari = [r for r in kayitlar if str(r.get('Teneke_No','')).strip() == teneke]
            if not teneke_kayitlari:
                await bot.edit_message_text(f"❌ Teneke {teneke} için kayıt yok", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            def tarih_parse(t):
                try:
                    return datetime.strptime(t, "%d-%m-%Y")
                except:
                    try:
                        return datetime.strptime(t, "%Y-%m-%d")
                    except:
                        return datetime(2000,1,1)
            mesaj = f"📊 **Teneke {teneke} - TÜM pH**\n\n"
            for k in sorted(teneke_kayitlari, key=lambda x: tarih_parse(x.get('Tarih','01-01-2000')), reverse=True):
                mesaj += f"📅 {k['Tarih']}: pH {k['pH']} - {k.get('Not','')}\n"
            for parca in mesaj_parcala(mesaj):
                await bot.send_message(chat_id=msg.chat.id, text=parca)
            await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "ph_tumu":
        try:
            kayitlar = ph_sheet.get_all_records()
            if not kayitlar:
                await bot.edit_message_text("❌ pH kaydı yok", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            tenekeler = {}
            for r in kayitlar:
                t = r.get('Teneke_No','Bilinmiyor')
                tenekeler.setdefault(t,[]).append(r)
            def tarih_parse(t):
                try:
                    return datetime.strptime(t, "%d-%m-%Y")
                except:
                    try:
                        return datetime.strptime(t, "%Y-%m-%d")
                    except:
                        return datetime(2000,1,1)
            mesaj = "📊 **TÜM TENEKELER - TÜM pH**\n\n"
            for t in sorted(tenekeler.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
                mesaj += f"🔹 **Teneke {t}**\n"
                for k in sorted(tenekeler[t], key=lambda x: tarih_parse(x.get('Tarih','01-01-2000')), reverse=True)[:5]:
                    mesaj += f" 📅 {k['Tarih']}: pH {k['pH']}\n"
                mesaj += "\n"
            for parca in mesaj_parcala(mesaj):
                await bot.send_message(chat_id=msg.chat.id, text=parca)
            await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    elif data == "ph_ekle_ac":
        bekleyen_ph_ekle[user_id] = {}
        await bot.edit_message_text("➕ **Teneke numarasını yazın:**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_ph"))
        return
    elif data == "ph_sil_ac":
        bekleyen_ph_sil[user_id] = True
        await bot.edit_message_text("❌ **Silinecek pH kaydının ID'sini yazın**\n(/ph_tumu ile ID'leri görebilirsiniz):", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_ph"))
        return

    elif data == "ai_sor_ac":
        bekleyen_ai[user_id] = True
        await bot.edit_message_text("🤖 **Sorunuzu yazın:**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_ai"))
        return

    elif data.startswith("page_"):
        parts = data.split("_")
        if len(parts) >= 3:
            action = parts[1]
            page = int(parts[2])
            stoklar = stok_oku()
            await bot.edit_message_text("🔍 **Malzeme seçin:**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=malzeme_listesi_menu(stoklar, page, action))
        return

    elif data == "islem_ekle_geri":
        await bot.edit_message_text("📝 **İŞLEM EKLE**\n\nTarih seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=tarih_menu())
        return
    elif data == "islem_miktar_geri":
        stoklar = stok_oku()
        await bot.edit_message_text("📦 Malzeme yazın veya seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=malzeme_listesi_menu(stoklar,0,"islem_malzeme"))
        return
    elif data == "dus_miktar_geri":
        stoklar = stok_oku()
        await bot.edit_message_text("⬇️ Malzeme seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=stoktan_dus_malzeme_menu(stoklar,0))
        return
    elif data == "dus_geri":
        stoklar = stok_oku()
        await bot.edit_message_text("⬇️ Malzeme seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=stoktan_dus_malzeme_menu(stoklar,0))
        return

# ------------------- Text handler -------------------
@dp.message_handler(content_types=types.ContentTypes.TEXT)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    # AI Sor
    if user_id in bekleyen_ai:
        del bekleyen_ai[user_id]
        msg = await message.reply("🤔 Agnes düşünüyor...")
        cevap = ask_agnes(text, str(user_id))
        for parca in mesaj_parcala(cevap):
            await message.reply(f"🤖 **Agnes AI:**\n\n{parca}")
        await bot.delete_message(msg.chat.id, msg.message_id)
        return

    # Yeni Malzeme Ekle - ad
    if user_id in bekleyen_ekleme and 'kategori' in bekleyen_ekleme[user_id] and 'ad' not in bekleyen_ekleme[user_id]:
        bekleyen_ekleme[user_id]['ad'] = text
        await message.reply(f"📝 Ad: {text}\n\nMiktar yazın (sayı):", reply_markup=iptal_menusu("stok_ekle_ac"))
        return
    # Yeni Malzeme Ekle - miktar
    if user_id in bekleyen_ekleme and 'ad' in bekleyen_ekleme[user_id] and 'miktar' not in bekleyen_ekleme[user_id]:
        try:
            miktar = float(text.replace(',','.'))
            bekleyen_ekleme[user_id]['miktar'] = str(miktar).replace('.',',')
            await message.reply(f"📦 Miktar: {text}\n\nBirim seçin:", reply_markup=birim_menu())
        except:
            await message.reply("❌ Geçersiz sayı.", reply_markup=iptal_menusu("stok_ekle_ac"))
        return
    # Yeni Malzeme Ekle - görev
    if user_id in bekleyen_ekleme and 'birim' in bekleyen_ekleme[user_id]:
        veri = bekleyen_ekleme[user_id]
        yeni = {
            'Kategori': veri['kategori'],
            'Malzeme / Alet': veri['ad'],
            'Başlangıç Miktarı': veri['miktar'],
            'Kullanılan': '0',
            'Kalan Miktar': veri['miktar'],
            'Birim': veri['birim'],
            'Görevi / Not': text
        }
        if stok_ekle(yeni):
            await message.reply(f"✅ **{veri['ad']}** eklendi!\n📦 {veri['miktar']} {veri['birim']}\n📝 {text}")
            history_ekle("ENVANTERE EKLENDİ", veri['ad'], veri['miktar'], veri['birim'])
        else:
            await message.reply("❌ Kayıt hatası.")
        del bekleyen_ekleme[user_id]
        return

    # Stoktan Düş - not
    if user_id in bekleyen_dus and 'tur' in bekleyen_dus[user_id]:
        veri = bekleyen_dus[user_id]
        basarili, sonuc = stoktan_dus(veri['malzeme'], veri['miktar'], veri['birim'], veri['tur'], text)
        if basarili:
            await message.reply(f"✅ {veri['miktar']} {veri['birim']} {veri['malzeme']} kullanıldı.\n📊 Kalan: {sonuc} {veri['birim']}")
        else:
            await message.reply(f"❌ {sonuc}")
        del bekleyen_dus[user_id]
        return

    # İşlem Ekle - özel tarih
    if user_id in bekleyen_islem and bekleyen_islem[user_id].get('tarih_ozel'):
        bekleyen_islem[user_id]['tarih'] = tarih_convert(text)
        del bekleyen_islem[user_id]['tarih_ozel']
        await message.reply(f"📅 Tarih: {text}\n\nİşlem türü seçin:", reply_markup=islem_tur_menu("islem"))
        return
    # İşlem Ekle - malzeme adı (butonda yoksa yazı ile)
    if user_id in bekleyen_islem and 'tur' in bekleyen_islem[user_id] and 'malzeme' not in bekleyen_islem[user_id]:
        stoklar = stok_oku()
        bulundu = False
        for i in stoklar:
            if i.get('Malzeme / Alet', '').lower() == text.lower():
                birim = i.get('Birim','gr')
                bekleyen_islem[user_id]['malzeme'] = i.get('Malzeme / Alet')
                bekleyen_islem[user_id]['birim'] = birim
                await message.reply(f"📦 Malzeme: {text}\n\nMiktar seçin:", reply_markup=miktar_menu(text, birim, "islem"))
                bulundu = True
                return
        if not bulundu:
            await message.reply(f"❌ '{text}' stokta bulunamadı.\n\nLütfen listeden seçin veya doğru adı yazın:", reply_markup=malzeme_listesi_menu(stoklar,0,"islem_malzeme"))
        return
    # İşlem Ekle - not (son adım)
    if user_id in bekleyen_islem and 'ph' in bekleyen_islem[user_id]:
        veri = bekleyen_islem[user_id]
        tarih = veri.get('tarih', tarih_format())
        basarili, sonuc = stoktan_dus(veri['malzeme'], veri['miktar'], veri['birim'], veri['tur'], text)
        if basarili:
            history_sheet.append_row([tarih, veri['tur'], f"{veri['miktar']} {veri['birim']} {veri['malzeme']}", veri['ph'], text])
            await message.reply(f"✅ İşlem kaydedildi!\n📅 {tarih}\n📋 {veri['tur']}\n📦 {veri['miktar']} {veri['birim']} {veri['malzeme']}\n🔬 pH: {veri['ph']}\n📝 {text}")
        else:
            await message.reply(f"❌ Stok hatası: {sonuc}")
        del bekleyen_islem[user_id]
        return

    # Aylık Rapor
    if user_id in bekleyen_rapor_aylik:
        del bekleyen_rapor_aylik[user_id]
        ay_str = text.strip()
        kayitlar = history_oku()
        if not kayitlar:
            await message.reply("❌ Kayıt yok")
            return
        ay_kayitlari = []
        for r in kayitlar:
            tarih_str = r.get('Tarih', '')
            if not tarih_str:
                continue
            try:
                tarih_obj = datetime.strptime(tarih_str, "%d-%m-%Y")
            except:
                try:
                    tarih_obj = datetime.strptime(tarih_str, "%Y-%m-%d")
                except:
                    continue
            if tarih_obj.strftime("%m-%Y") == ay_str or tarih_obj.strftime("%Y-%m") == ay_str:
                ay_kayitlari.append(r)
        if not ay_kayitlari:
            await message.reply(f"❌ {ay_str} ayında kayıt bulunamadı.")
            return
        sayilar = {}
        malzemeler = {}
        for r in ay_kayitlari:
            tur = r.get('Islem','Bilinmiyor')
            sayilar[tur] = sayilar.get(tur,0)+1
            m_str = r.get('Kullanilan_Malzeme_Miktar','')
            if m_str and m_str != "-":
                parts = m_str.split()
                if len(parts) >= 3:
                    malzeme_adi = " ".join(parts[2:])
                    malzemeler[malzeme_adi] = malzemeler.get(malzeme_adi,0)+1
        en_cok = max(malzemeler.items(), key=lambda x: x[1])[0] if malzemeler else "Yok"
        mesaj = f"📊 **{ay_str} AYLIK RAPORU**\n\n📝 Toplam işlem: {len(ay_kayitlari)}\n🔧 En çok kullanılan: {en_cok}\n\n📋 İşlem türleri:\n"
        for tur, sayi in sorted(sayilar.items(), key=lambda x: x[1], reverse=True):
            mesaj += f"• {tur}: {sayi} kez\n"
        await message.reply(mesaj)
        return

    # Stok Grafiği
    if user_id in bekleyen_grafik:
        del bekleyen_grafik[user_id]
        malzeme = text.strip()
        kayitlar = history_oku()
        gecmis = [r for r in kayitlar if malzeme.lower() in r.get('Kullanilan_Malzeme_Miktar','').lower()]
        if not gecmis:
            await message.reply(f"❌ '{malzeme}' için kayıt yok")
            return
        mesaj = f"📉 **'{malzeme.upper()}' KULLANIM GEÇMİŞİ (Son 10)**\n\n"
        for r in gecmis[-10:][::-1]:
            mesaj += f"📅 {r.get('Tarih','-')}: {r.get('Kullanilan_Malzeme_Miktar','-')}\n"
        await message.reply(mesaj)
        return

    # pH Ekle
    if user_id in bekleyen_ph_ekle and 'teneke' not in bekleyen_ph_ekle[user_id]:
        bekleyen_ph_ekle[user_id]['teneke'] = text
        await message.reply(f"🔬 Teneke: {text}\n\npH değerini yazın (örn: 6.5):", reply_markup=iptal_menusu("menu_ph"))
        return
    if user_id in bekleyen_ph_ekle and 'teneke' in bekleyen_ph_ekle[user_id] and 'ph' not in bekleyen_ph_ekle[user_id]:
        bekleyen_ph_ekle[user_id]['ph'] = text
        await message.reply(f"🔬 pH: {text}\n\nNot yazın (isteğe bağlı):", reply_markup=iptal_menusu("menu_ph"))
        return
    if user_id in bekleyen_ph_ekle and 'ph' in bekleyen_ph_ekle[user_id]:
        veri = bekleyen_ph_ekle[user_id]
        try:
            ph_sheet.append_row([tarih_format(), veri['teneke'], "-", veri['ph'], text if text else "Bot ile eklendi"])
            await message.reply(f"✅ pH kaydedildi!\n📅 {tarih_format()}\n🔬 Teneke {veri['teneke']} - pH {veri['ph']}")
        except Exception as e:
            await message.reply(f"❌ Hata: {e}")
        del bekleyen_ph_ekle[user_id]
        return

    # Hatırlatma Ekle - özel tarih
    if user_id in bekleyen_hatirlat and bekleyen_hatirlat[user_id].get('tarih_ozel'):
        bekleyen_hatirlat[user_id]['tarih'] = tarih_convert(text)
        del bekleyen_hatirlat[user_id]['tarih_ozel']
        await message.reply(f"📅 Tarih: {text}\n\nSaat yazın (örn: 10:00):", reply_markup=iptal_menusu("hatirlat_ekle_ac"))
        return
    # Hatırlatma Ekle - özel saat
    if user_id in bekleyen_hatirlat and bekleyen_hatirlat[user_id].get('saat_ozel'):
        bekleyen_hatirlat[user_id]['saat'] = text
        del bekleyen_hatirlat[user_id]['saat_ozel']
        await message.reply(f"⏰ Saat: {text}\n\nHatırlatma metnini yazın:", reply_markup=iptal_menusu("hatirlat_ekle_ac"))
        return
    # Hatırlatma Ekle - saat yoksa
    if user_id in bekleyen_hatirlat and 'tarih' in bekleyen_hatirlat[user_id] and 'saat' not in bekleyen_hatirlat[user_id]:
        bekleyen_hatirlat[user_id]['saat'] = text
        await message.reply(f"⏰ Saat: {text}\n\nHatırlatma metnini yazın:", reply_markup=iptal_menusu("hatirlat_ekle_ac"))
        return
    # Hatırlatma Ekle - metin
    if user_id in bekleyen_hatirlat and 'saat' in bekleyen_hatirlat[user_id]:
        veri = bekleyen_hatirlat[user_id]
        try:
            reminders_sheet.append_row([veri['tarih'], veri['saat'], text, "bekliyor"])
            await message.reply(f"✅ Hatırlatma eklendi!\n📅 {veri['tarih']} {veri['saat']}\n📝 {text}")
        except Exception as e:
            await message.reply(f"❌ Kayıt hatası: {e}")
        del bekleyen_hatirlat[user_id]
        return

    # Tarihli İşlemler
    if user_id in bekleyen_gecmis_tarih:
        del bekleyen_gecmis_tarih[user_id]
        kayitlar = history_oku()
        if not kayitlar:
            await message.reply("❌ Kayıt yok")
            return
        aranan = tarih_convert(text)
        tarih_kayitlari = []
        for idx, r in enumerate(kayitlar):
            if r.get('Tarih','') == aranan:
                tarih_kayitlari.append((idx+1, r))
        if not tarih_kayitlari:
            await message.reply(f"❌ {text} tarihinde kayıt yok")
            return
        mesaj = f"📜 **{text} TARİHİNDEKİ İŞLEMLER**\n\n"
        for kayit_id, r in tarih_kayitlari[:15]:
            mesaj += f"**ID: {kayit_id}** | {r.get('Islem','-')}\n   {r.get('Kullanilan_Malzeme_Miktar','-')}\n\n"
        for parca in mesaj_parcala(mesaj):
            await message.reply(parca)
        return

    # İşlem Sil
    if user_id in bekleyen_gecmis_sil:
        del bekleyen_gecmis_sil[user_id]
        try:
            kayit_id = int(text)
            kayitlar = history_oku()
            if kayit_id < 1 or kayit_id > len(kayitlar):
                await message.reply(f"❌ Geçersiz ID (1-{len(kayitlar)})")
                return
            history_sheet.delete_rows(kayit_id + 1)
            await message.reply(f"✅ {kayit_id} ID'li kayıt silindi.")
        except:
            await message.reply("❌ Lütfen sayı girin.")
        return

    # Hatırlatma Sil
    if user_id in bekleyen_hatirlat_sil:
        del bekleyen_hatirlat_sil[user_id]
        try:
            idx = int(text) - 1
            kayitlar = reminders_sheet.get_all_records()
            if idx < 0 or idx >= len(kayitlar):
                await message.reply("❌ Geçersiz ID")
                return
            reminders_sheet.delete_rows(idx + 2)
            await message.reply(f"✅ {text} ID'li hatırlatma silindi.")
        except:
            await message.reply("❌ Lütfen sayı girin.")
        return

    # pH Sil
    if user_id in bekleyen_ph_sil:
        del bekleyen_ph_sil[user_id]
        try:
            idx = int(text) - 1
            kayitlar = ph_sheet.get_all_records()
            if idx < 0 or idx >= len(kayitlar):
                await message.reply("❌ Geçersiz ID")
                return
            ph_sheet.delete_rows(idx + 2)
            await message.reply(f"✅ {text} ID'li pH kaydı silindi.")
        except:
            await message.reply("❌ Lütfen sayı girin.")
        return

    else:
        await message.reply("❓ Anlamadım. /menu yazarak ana menüyü açabilirsiniz.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
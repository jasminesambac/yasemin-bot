import os
import logging
import asyncio
import requests
import json
from datetime import datetime
from openai import OpenAI
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import gspread
from oauth2client.service_account import ServiceAccountCredentials

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")

# Google Sheets yetkilendirmesi
SHEET_ID = os.getenv("SHEET_ID")
CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS")

creds_dict = json.loads(CREDENTIALS_JSON)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gc = gspread.authorize(creds)

sh = gc.open_by_key(SHEET_ID)
inventory_sheet = sh.worksheet("inventory")
history_sheet = sh.worksheet("history")
ph_sheet = sh.worksheet("ph_records")
reminders_sheet = sh.worksheet("reminders")

son_kayit_geri_al = None
stok_uyarilari = {}
baglam_metinleri = {}
sulama_oturum = {}
bekleyen_silme = {}
bekleyen_ekleme = {}
bekleyen_ph = {}
bekleyen_hatirlat = {}
bekleyen_islem = {}          # İşlem ekle için
bekleyen_ai = {}
bekleyen_gecmis_tarih = {}
bekleyen_rapor_aylik = {}
bekleyen_grafik = {}
bekleyen_ph_ekle = {}

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
            messages.append({"role": "system", "content": f"Önceki konuşma geçmişi:\n{baglam}"})
        messages.append({"role": "user", "content": question})
        response = client.chat.completions.create(
            model="agnes-2.0-flash",
            messages=messages,
            max_tokens=3000
        )
        cevap = response.choices[0].message.content
        return cevap
    except Exception as e:
        return f"Agnes hatası: {str(e)[:100]}"

def stok_oku():
    try:
        return inventory_sheet.get_all_records()
    except Exception as e:
        print(f"Stok okuma hatası: {e}")
        return []

def stok_kaydet(stok_listesi):
    try:
        inventory_sheet.clear()
        if stok_listesi:
            headers = list(stok_listesi[0].keys())
            inventory_sheet.append_row(headers)
            for row in stok_listesi:
                inventory_sheet.append_row(list(row.values()))
        return True
    except Exception as e:
        print(f"Stok kayıt hatası: {e}")
        return False

def history_ekle(islem, malzeme_adi, miktar, birim, ph="", not_metni=""):
    try:
        tarih = tarih_format()
        history_sheet.append_row([tarih, islem, f"{miktar} {birim} {malzeme_adi}", ph, not_metni])
        return True
    except Exception as e:
        print(f"History kayıt hatası: {e}")
        return False

def history_oku():
    try:
        return history_sheet.get_all_records()
    except Exception as e:
        print(f"History okuma hatası: {e}")
        return []

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
        reminders_sheet.append_row([tarih, saat, islem, "bekliyor"])
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

def stoktan_dus_kontrol(malzeme_adi, miktar, birim):
    stoklar = stok_oku()
    for item in stoklar:
        if malzeme_adi.lower() in item.get('Malzeme / Alet', '').lower():
            try:
                kalan_str = str(item['Kalan Miktar']).replace(',', '.').strip()
                if kalan_str == 'Stok bol':
                    return True, "Stok bol", "Stok bol", "Stok bol"
                kalan = float(kalan_str)
                if kalan >= miktar:
                    yeni_kalan = kalan - miktar
                    eski_kalan = kalan
                    item['Kalan Miktar'] = str(yeni_kalan).replace('.', ',')
                    kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
                    item['Kullanılan'] = str(kullanilan + miktar).replace('.', ',')
                    stok_kaydet(stoklar)
                    uyari_var, esik, uyari_birimi = stok_uyari_kontrol(malzeme_adi, yeni_kalan, birim)
                    if uyari_var:
                        return True, yeni_kalan, esik, uyari_birimi
                    return True, yeni_kalan, None, None
                else:
                    return False, kalan, None, None
            except:
                return False, None, None, None
    return False, None, None, None

# --------------------------- MENÜLER ---------------------------------
def iptal_menusu(geri_callback="menu_ana"):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("❌ İptal", callback_data=geri_callback))
    return kb

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
        InlineKeyboardButton("🔄 İşlemi Tekrar Uygula", callback_data="gecmis_tekrar_ac"),
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

def sehir_menu():
    sehirler = ["İstanbul", "Ankara", "İzmir", "Bursa", "Antalya", "Adana", "Konya", "Trabzon", "Samsun", "Diyarbakır", "Van", "Erzurum", "Gaziantep", "Mersin", "Kayseri", "Eskişehir", "Denizli", "Sivas", "Malatya", "Elazığ"]
    kb = InlineKeyboardMarkup(row_width=3)
    for sehir in sehirler:
        kb.add(InlineKeyboardButton(sehir, callback_data=f"sehir_{sehir}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="menu_hava"))
    return kb

def su_miktar_menu():
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("1 L", callback_data="su_1"),
        InlineKeyboardButton("5 L", callback_data="su_5"),
        InlineKeyboardButton("10 L", callback_data="su_10"),
        InlineKeyboardButton("20 L", callback_data="su_20"),
        InlineKeyboardButton("50 L", callback_data="su_50"),
        InlineKeyboardButton("✏️ Özel", callback_data="su_ozel"),
        InlineKeyboardButton("🔙 Geri", callback_data="stok_menu")
    )
    return kb

def malzeme_listesi_menu(malzemeler, page=0, action="sorgula"):
    kb = InlineKeyboardMarkup(row_width=2)
    sayfa_malzemeler = malzemeler[page*8:(page+1)*8]
    for item in sayfa_malzemeler:
        malzeme_adi = item.get('Malzeme / Alet', '-')
        kb.add(InlineKeyboardButton(malzeme_adi[:30], callback_data=f"{action}_{malzeme_adi}"))
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Önceki", callback_data=f"malzeme_page_{action}_{page-1}"))
    if len(malzemeler) > (page+1)*8:
        nav_buttons.append(InlineKeyboardButton("Sonraki ▶️", callback_data=f"malzeme_page_{action}_{page+1}"))
    if nav_buttons:
        kb.row(*nav_buttons)
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="stok_menu"))
    return kb

def kategori_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("Katı", callback_data="kategori_katı"),
        InlineKeyboardButton("Sıvı", callback_data="kategori_sıvı"),
        InlineKeyboardButton("Alet", callback_data="kategori_alet"),
        InlineKeyboardButton("Mekanik", callback_data="kategori_mekanik"),
        InlineKeyboardButton("Cihaz", callback_data="kategori_cihaz"),
        InlineKeyboardButton("🔙 Geri", callback_data="stok_menu")
    )
    return kb

def birim_menu():
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("gr", callback_data="birim_gr"),
        InlineKeyboardButton("ml", callback_data="birim_ml"),
        InlineKeyboardButton("L", callback_data="birim_L"),
        InlineKeyboardButton("adet", callback_data="birim_adet"),
        InlineKeyboardButton("🔙 Geri", callback_data="stok_ekle_ac")
    )
    return kb

def teneke_menu(tenekeler, action="ph_son"):
    kb = InlineKeyboardMarkup(row_width=4)
    for t in sorted(set(tenekeler), key=lambda x: int(x) if x.isdigit() else 0):
        kb.add(InlineKeyboardButton(t, callback_data=f"{action}_{t}"))
    kb.add(InlineKeyboardButton("🔙 Geri", callback_data="menu_ph"))
    return kb

# --------------------------- KOMUTLAR ---------------------------------
@dp.message_handler(commands=['menu', 'start'])
async def menu(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan**\n\nNe yapmak istersin?", reply_markup=ana_menu())

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor (Google Sheets modu).")

@dp.message_handler(commands=['sor'])
async def sor_command(message: types.Message):
    soru = message.get_args()
    if not soru:
        await message.reply("Bir soru yaz: /sor [sorunuz]")
        return
    user_id = str(message.from_user.id)
    msg = await message.reply("🤔 Agnes düşünüyor...")
    cevap = ask_agnes(soru, user_id)
    baglam_guncelle(user_id, soru, cevap)
    for parca in mesaj_parcala(cevap):
        await bot.send_message(chat_id=message.chat.id, text=f"🤖 **Agnes AI:**\n\n{parca}")

@dp.message_handler(commands=['kaydet'])
async def kaydet_command(message: types.Message):
    global son_kayit_geri_al
    islem = message.get_args()
    if not islem:
        await message.reply("Örnek: /kaydet 5 gr NPK veya /kaydet Sera kuruldu")
        return
    parcalar = islem.split()
    if len(parcalar) >= 3 and parcalar[0].replace('.', '').replace(',', '').isdigit():
        try:
            miktar = float(parcalar[0].replace(',', '.'))
            birim = parcalar[1]
            malzeme_aranan = " ".join(parcalar[2:])
        except:
            history_ekle("İşlem", islem, "-", "-")
            await message.reply(f"✅ İşlem kaydedildi:\n📝 {islem}")
            return
        stoklar = stok_oku()
        eslesenler = malzeme_bul(malzeme_aranan, stoklar)
        if not eslesenler:
            history_ekle("İşlem", islem, "-", "-")
            await message.reply(f"✅ İşlem kaydedildi (stokta bulunamadı):\n📝 {islem}")
            return
        if len(eslesenler) > 1:
            liste = "\n".join([f"• {item.get('Malzeme / Alet')}" for item in eslesenler[:5]])
            await message.reply(f"⚠️ '{malzeme_aranan}' için birden fazla malzeme bulundu:\n\n{liste}\n\nLütfen tam adını yazın.\n\nİşlem yine de kaydedildi.")
            history_ekle("İşlem", islem, "-", "-")
            return
        item = eslesenler[0]
        malzeme_adi = item.get('Malzeme / Alet')
        try:
            kalan_str = str(item['Kalan Miktar']).replace(',', '.').strip()
            if kalan_str == 'Stok bol':
                item['Kalan Miktar'] = 'Stok bol'
                stok_kaydet(stoklar)
                son_kayit_geri_al = {'malzeme': malzeme_adi, 'eski_kalan': 'Stok bol', 'kullanilan': miktar, 'birim': birim}
                history_ekle("Kullanım", malzeme_adi, miktar, birim)
                await message.reply(f"✅ {miktar:.1f} {birim} {malzeme_adi} kullanıldı. (Stok bol, tükenmez)")
                return
            kalan = float(kalan_str)
            if kalan >= miktar:
                yeni_kalan = kalan - miktar
                eski_kalan = kalan
                item['Kalan Miktar'] = str(yeni_kalan).replace('.', ',')
                kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
                item['Kullanılan'] = str(kullanilan + miktar).replace('.', ',')
                stok_kaydet(stoklar)
                son_kayit_geri_al = {'malzeme': malzeme_adi, 'eski_kalan': eski_kalan, 'kullanilan': miktar, 'birim': birim}
                history_ekle("Kullanım", malzeme_adi, miktar, birim)
                uyari_var, esik, uyari_birimi = stok_uyari_kontrol(malzeme_adi, yeni_kalan, birim)
                if uyari_var:
                    await message.reply(f"✅ {miktar:.1f} {birim} {malzeme_adi} kullanıldı.\n📊 Kalan: {yeni_kalan:.1f} {birim}\n\n⚠️ **STOK UYARISI!** {malzeme_adi} {esik} {uyari_birimi} altına düştü!")
                else:
                    await message.reply(f"✅ {miktar:.1f} {birim} {malzeme_adi} kullanıldı.\n📊 Kalan: {yeni_kalan:.1f} {birim}")
                return
            else:
                await message.reply(f"❌ Yetersiz stok! Kalan: {kalan:.1f} {birim}\n\nİşlem yine de kaydedildi.")
                history_ekle("İşlem", islem, "-", "-")
                return
        except Exception as e:
            await message.reply(f"❌ Hata: {e}\n\nİşlem yine de kaydedildi.")
            history_ekle("İşlem", islem, "-", "-")
            return
    else:
        history_ekle("İşlem", islem, "-", "-")
        await message.reply(f"✅ İşlem kaydedildi:\n📝 {islem}")

@dp.message_handler(commands=['stok'])
async def stok_command(message: types.Message):
    param = message.get_args()
    stoklar = stok_oku()
    if not stoklar:
        await message.reply("❌ Stok dosyası okunamadı veya boş.")
        return
    if param:
        eslesenler = malzeme_bul(param, stoklar)
        if not eslesenler:
            await message.reply(f"❌ '{param}' ile eşleşen malzeme bulunamadı.")
            return
        if len(eslesenler) == 1:
            item = eslesenler[0]
            cevap = f"📦 **{item.get('Malzeme / Alet')}**\n📊 Kalan: {item.get('Kalan Miktar')} {item.get('Birim')}\n📝 Görevi: {item.get('Görevi / Not', '-')}\n\n"
            try:
                kayitlar = history_oku()
                gecmisler = [row for row in kayitlar if param.lower() in row.get('Kullanilan_Malzeme_Miktar', '').lower()]
                if gecmisler:
                    cevap += "📜 **TÜM KULLANIMLAR:**\n"
                    for row in gecmisler[:10]:
                        cevap += f"   • {row.get('Tarih', '-')}: {row.get('Kullanilan_Malzeme_Miktar', '-')}\n"
                else:
                    cevap += "📜 **Geçmiş kullanım kaydı yok.**"
            except:
                cevap += "📜 History okunamadı."
            await message.reply(cevap)
        else:
            cevap = f"🔍 **'{param}' için bulunan malzemeler:**\n\n"
            for item in eslesenler[:10]:
                cevap += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
            await message.reply(cevap)
    else:
        mesaj = "📦 **ENVANTER LİSTESİ**\n\n"
        for item in stoklar[:30]:
            mesaj += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
        await message.reply(mesaj)

@dp.message_handler(commands=['ekle'])
async def ekle_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ekle NPK;1000;gr;Gübre")
        return
    parcalar = param.split(';')
    if len(parcalar) < 3:
        await message.reply("Format: Ad;Miktar;Birim;Görev\nÖrnek: YeniGubre;500;gr;Deneme")
        return
    malzeme_adi = parcalar[0].strip()
    miktar = parcalar[1].strip()
    birim = parcalar[2].strip()
    gorev = parcalar[3].strip() if len(parcalar) > 3 else "-"
    stoklar = stok_oku()
    for item in stoklar:
        if item.get('Malzeme / Alet', '').lower() == malzeme_adi.lower():
            await message.reply(f"❌ '{malzeme_adi}' zaten envanterde var.")
            return
    if birim.lower() in ['ml', 'l', 'litre']:
        kategori = 'Sıvı'
    elif birim.lower() in ['adet']:
        kategori = 'Alet'
    else:
        kategori = 'Katı'
    yeni_kayit = {'Kategori': kategori, 'Malzeme / Alet': malzeme_adi, 'Başlangıç Miktarı': miktar, 'Kullanılan': '0', 'Kalan Miktar': miktar, 'Birim': birim, 'Görevi / Not': gorev}
    stoklar.append(yeni_kayit)
    if stok_kaydet(stoklar):
        await message.reply(f"✅ **'{malzeme_adi}'** envantere eklendi!\n\n📦 Miktar: {miktar} {birim}\n📝 Görevi: {gorev}")
        history_ekle("ENVANTERE EKLENDİ", malzeme_adi, miktar, birim)
    else:
        await message.reply("❌ Ekleme sırasında hata oluştu.")

@dp.message_handler(commands=['sil'])
async def sil_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /sil NPK")
        return
    stoklar = stok_oku()
    eslesenler = malzeme_bul(param, stoklar)
    if not eslesenler:
        await message.reply(f"❌ '{param}' ile eşleşen malzeme bulunamadı.")
        return
    if len(eslesenler) > 1:
        liste = "\n".join([f"• {item.get('Malzeme / Alet')}" for item in eslesenler[:5]])
        await message.reply(f"⚠️ '{param}' için birden fazla malzeme bulundu:\n\n{liste}\n\nLütfen tam adını yazın.")
        return
    malzeme = eslesenler[0]
    bekleyen_silme[message.from_user.id] = malzeme
    await message.reply(f"⚠️ **{malzeme.get('Malzeme / Alet')}** silinsin mi?\n\n📊 Miktar: {malzeme.get('Kalan Miktar')} {malzeme.get('Birim')}\n\nBu işlem GERİ DÖNÜŞÜMSÜZDÜR!\n\n30 saniye içinde /evet yazın.")
    await asyncio.sleep(30)
    if message.from_user.id in bekleyen_silme:
        del bekleyen_silme[message.from_user.id]
        await message.reply("⏰ Silme iptal edildi.")

@dp.message_handler(commands=['evet'])
async def evet_command(message: types.Message):
    if message.from_user.id not in bekleyen_silme:
        await message.reply("❌ Silinecek malzeme yok. Önce /sil komutunu kullanın.")
        return
    malzeme = bekleyen_silme[message.from_user.id]
    malzeme_adi = malzeme.get('Malzeme / Alet')
    stoklar = stok_oku()
    yeni_stoklar = [item for item in stoklar if item.get('Malzeme / Alet') != malzeme_adi]
    if stok_kaydet(yeni_stoklar):
        await message.reply(f"✅ **'{malzeme_adi}'** envanterden silindi.")
        history_ekle("ENVANTERDEN SİLİNDİ", malzeme_adi, "-", "-")
    else:
        await message.reply("❌ Silme işlemi sırasında hata oluştu.")
    del bekleyen_silme[message.from_user.id]

@dp.message_handler(commands=['kaydet_geri_al'])
async def kaydet_geri_al_command(message: types.Message):
    global son_kayit_geri_al
    if not son_kayit_geri_al:
        await message.reply("❌ Geri alınacak kayıt yok.")
        return
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
            await message.reply(f"✅ Geri alındı:\n📦 {son_kayit_geri_al['malzeme']}\n➕ +{son_kayit_geri_al['kullanilan']} {son_kayit_geri_al['birim']}")
            son_kayit_geri_al = None
            return
    await message.reply("❌ Malzeme bulunamadı.")

# --------------------------- HAVA DURUMU ---------------------------------
@dp.message_handler(commands=['hava'])
async def hava_command(message: types.Message):
    sehir = message.get_args()
    if not sehir:
        sehir = "Istanbul"
    try:
        url = f"https://wttr.in/{sehir}?format=%C+%t+%w+%h&m"
        response = requests.get(url, timeout=10)
        sonuc = response.text.strip()
        await message.reply(f"🌤️ **{sehir.upper()} - ŞU ANKİ HAVA**\n\n{sonuc}\n\n(°C, km/h)")
    except:
        await message.reply("❌ Hava durumu alınamadı.")

@dp.message_handler(commands=['hava_aylik'])
async def hava_aylik_command(message: types.Message):
    sehir = message.get_args()
    if not sehir:
        sehir = "Istanbul"
    try:
        url = f"https://wttr.in/{sehir}?m&format=%l:+%t+%C"
        response = requests.get(url, timeout=10)
        await message.reply(f"📊 **{sehir.upper()} - AYLIK HAVA ÖZETİ**\n\n{response.text.strip()}")
    except:
        await message.reply("❌ Hava durumu alınamadı.")

# --------------------------- RAPORLAR ---------------------------------
@dp.message_handler(commands=['istatistik'])
async def istatistik_command(message: types.Message):
    try:
        kayitlar = history_oku()
        toplam_islem = len(kayitlar)
        malzeme_sayilari = {}
        for row in kayitlar:
            malzeme_str = row.get('Kullanilan_Malzeme_Miktar', '')
            if malzeme_str and malzeme_str != "-":
                for m in malzeme_str.split(','):
                    parcalar = m.strip().split()
                    if len(parcalar) >= 3:
                        malzeme = " ".join(parcalar[2:])
                        malzeme_sayilari[malzeme] = malzeme_sayilari.get(malzeme, 0) + 1
        en_cok = sorted(malzeme_sayilari.items(), key=lambda x: x[1], reverse=True)[:5]
        istatistik = f"📊 **GENEL İSTATİSTİK**\n\n📝 Toplam işlem: {toplam_islem}\n\n🔧 En çok kullanılan malzemeler:\n"
        for malzeme, sayi in en_cok:
            istatistik += f"   • {malzeme}: {sayi} kez\n"
        await message.reply(istatistik)
    except Exception as e:
        await message.reply(f"❌ İstatistik alınamadı: {e}")

@dp.message_handler(commands=['rapor_gunluk'])
async def rapor_gunluk_command(message: types.Message):
    bugun = tarih_format()
    try:
        kayitlar = history_oku()
        gunun_islemleri = [row for row in kayitlar if row.get('Tarih', '') == bugun]
        if not gunun_islemleri:
            await message.reply(f"📅 **{bugun} GÜNLÜK RAPOR**\n\nBugün hiç işlem yapılmamış.")
            return
        rapor = f"📅 **{bugun} GÜNLÜK RAPOR**\n\n📝 Toplam işlem: {len(gunun_islemleri)}\n\n"
        for row in gunun_islemleri[:15]:
            rapor += f"• {row.get('Islem', '-')}: {row.get('Kullanilan_Malzeme_Miktar', '-')[:50]}\n"
        await message.reply(rapor)
    except Exception as e:
        await message.reply(f"❌ Rapor alınamadı: {e}")

@dp.message_handler(commands=['rapor_aylik'])
async def rapor_aylik_command(message: types.Message):
    ay_param = message.get_args()
    if not ay_param:
        await message.reply("Örnek: /rapor_aylik 05-2026")
        return
    try:
        kayitlar = history_oku()
        if not kayitlar:
            await message.reply("❌ Henüz hiç kayıt yok.")
            return
        ay_kontrol1 = f"{ay_param[3:]}-{ay_param[:2]}" if '-' in ay_param else ""
        ay_kontrol2 = f"-{ay_param[3:]}-{ay_param[:2]}" if '-' in ay_param else ""
        ay_kontrol3 = ay_param
        ay_kayitlari = [row for row in kayitlar if ay_kontrol1 in row.get('Tarih', '') or ay_kontrol2 in row.get('Tarih', '') or ay_kontrol3 in row.get('Tarih', '')]
        if not ay_kayitlari:
            await message.reply(f"❌ {ay_param} ayında işlem bulunamadı.")
            return
        toplam_islem = len(ay_kayitlari)
        islem_turleri = {}
        malzeme_kullanimlari = {}
        toplam_miktar = 0
        miktar_sayac = 0
        for row in ay_kayitlari:
            tur = row.get('Islem', 'Bilinmiyor')
            islem_turleri[tur] = islem_turleri.get(tur, 0) + 1
            malzeme_str = row.get('Kullanilan_Malzeme_Miktar', '')
            if malzeme_str and malzeme_str != "-":
                parcalar = malzeme_str.split()
                if len(parcalar) >= 3:
                    try:
                        miktar = float(parcalar[0].replace(',', '.'))
                        malzeme = " ".join(parcalar[2:])
                        toplam_miktar += miktar
                        miktar_sayac += 1
                        malzeme_kullanimlari[malzeme] = malzeme_kullanimlari.get(malzeme, 0) + 1
                    except:
                        pass
        en_cok_malzeme = max(malzeme_kullanimlari.items(), key=lambda x: x[1])[0] if malzeme_kullanimlari else "Yok"
        ortalama_miktar = toplam_miktar / miktar_sayac if miktar_sayac > 0 else 0
        rapor = f"📊 **{ay_param} AYLIK RAPORU**\n\n📝 Toplam işlem: {toplam_islem}\n🔧 En çok kullanılan malzeme: {en_cok_malzeme}\n📦 Ortalama kullanım: {ortalama_miktar:.1f} gr\n\n📋 İşlem türleri:\n"
        for tur, sayi in sorted(islem_turleri.items(), key=lambda x: x[1], reverse=True):
            rapor += f"   • {tur}: {sayi} kez\n"
        await message.reply(rapor)
    except Exception as e:
        await message.reply(f"❌ Rapor alınamadı: {e}")

@dp.message_handler(commands=['grafik'])
async def grafik_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /grafik NPK")
        return
    try:
        kayitlar = history_oku()
        gecmisler = [row for row in kayitlar if param.lower() in row.get('Kullanilan_Malzeme_Miktar', '').lower()]
        if not gecmisler:
            await message.reply(f"❌ '{param}' için geçmiş kayıt bulunamadı.")
            return
        sonlar = gecmisler[-10:][::-1]
        grafik = f"📊 **'{param.upper()}' STOK GRAFİĞİ (Son 10 kullanım)**\n\n"
        for row in sonlar:
            grafik += f"📅 {row.get('Tarih', '-')}: {row.get('Kullanilan_Malzeme_Miktar', '-')}\n"
        await message.reply(grafik)
    except Exception as e:
        await message.reply(f"❌ Grafik alınamadı: {e}")

# --------------------------- HATIRLATMA ---------------------------------
@dp.message_handler(commands=['hatirlat'])
async def hatirlat_command(message: types.Message):
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
async def list_hatirlatmalar_command(message: types.Message):
    try:
        kayitlar = reminders_sheet.get_all_records()
        if not kayitlar:
            await message.reply("Henüz hatırlatma yok.")
            return
        bekleyenler = [(i, row) for i, row in enumerate(kayitlar, 1) if row.get('Durum') == "bekliyor"]
        if not bekleyenler:
            await message.reply("✅ Bekleyen hatırlatma yok.")
            return
        mesaj = "📅 **BEKLEYEN HATIRLATMALAR**\n\n"
        for i, row in bekleyenler:
            mesaj += f"**ID: {i}** | {row.get('Tarih')} {row.get('Saat')} - {row.get('Islem')}\n"
        await message.reply(mesaj[:4000])
    except:
        await message.reply("Dosya okuma hatası.")

@dp.message_handler(commands=['hatirlat_sil'])
async def hatirlat_sil_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /hatirlat_sil 1")
        return
    try:
        kayitlar = reminders_sheet.get_all_records()
        if not kayitlar:
            await message.reply("❌ Hatırlatma yok.")
            return
        idx = int(param) - 1
        if idx < 0 or idx >= len(kayitlar):
            await message.reply("❌ Geçersiz ID.")
            return
        reminders_sheet.delete_rows(idx + 2)
        await message.reply(f"✅ Hatırlatma silindi.")
    except:
        await message.reply("❌ Hata oluştu.")

# --------------------------- YEDEKLEME ---------------------------------
@dp.message_handler(commands=['yedekle'])
async def yedekle_command(message: types.Message):
    await message.reply("📦 Yedekleme hazırlanıyor...")
    try:
        inventory_data = inventory_sheet.get_all_values()
        history_data = history_sheet.get_all_values()
        ph_data = ph_sheet.get_all_values()
        reminders_data = reminders_sheet.get_all_values()
        import csv, io, zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            inv_csv = io.StringIO()
            writer = csv.writer(inv_csv)
            writer.writerows(inventory_data)
            zip_file.writestr('inventory.csv', inv_csv.getvalue().encode('utf-8-sig'))
            hist_csv = io.StringIO()
            writer = csv.writer(hist_csv)
            writer.writerows(history_data)
            zip_file.writestr('history.csv', hist_csv.getvalue().encode('utf-8-sig'))
            ph_csv = io.StringIO()
            writer = csv.writer(ph_csv)
            writer.writerows(ph_data)
            zip_file.writestr('ph_records.csv', ph_csv.getvalue().encode('utf-8-sig'))
            rem_csv = io.StringIO()
            writer = csv.writer(rem_csv)
            writer.writerows(reminders_data)
            zip_file.writestr('reminders.csv', rem_csv.getvalue().encode('utf-8-sig'))
        zip_buffer.seek(0)
        await message.reply_document(document=('yasemin_yedek.zip', zip_buffer), caption="📦 Yedek dosyaları")
    except Exception as e:
        await message.reply(f"❌ Yedekleme hatası: {e}")

# --------------------------- PH ---------------------------------
@dp.message_handler(commands=['ph_ekle'])
async def ph_ekle_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ph_ekle 1 6.5")
        return
    parcalar = param.split(maxsplit=2)
    if len(parcalar) < 2:
        await message.reply("Format: /ph_ekle teneke_no pH [not]")
        return
    teneke = parcalar[0]
    ph = parcalar[1]
    not_metni = parcalar[2] if len(parcalar) > 2 else "Bot ile eklendi"
    try:
        ph_sheet.append_row([tarih_format(), teneke, "-", ph, not_metni])
        await message.reply(f"✅ pH kaydı eklendi!\n📅 {tarih_format()} - Teneke {teneke} - pH {ph}\n📝 {not_metni}")
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@dp.message_handler(commands=['ph'])
async def ph_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ph 1 - Son ölçüm\n/ph 1 hepsi - Tüm ölçümler")
        return
    parcalar = param.split()
    teneke_no = parcalar[0]
    tumu = len(parcalar) > 1 and parcalar[1].lower() == 'hepsi'
    try:
        kayitlar = ph_sheet.get_all_records()
        teneke_kayitlari = [row for row in kayitlar if str(row.get('Teneke_No', '')).strip() == teneke_no]
        if not teneke_kayitlari:
            await message.reply(f"❌ Teneke {teneke_no} için pH kaydı yok.")
            return
        if tumu:
            mesaj = f"📊 **Teneke {teneke_no} - TÜM pH ÖLÇÜMLERİ**\n\n"
            for k in sorted(teneke_kayitlari, key=lambda x: x.get('Tarih', ''), reverse=True):
                not_str = f" - {k.get('Not', '')}" if k.get('Not') else ""
                mesaj += f"📅 {k['Tarih']}: pH {k['pH']}{not_str}\n"
            await message.reply(mesaj)
        else:
            en_son = max(teneke_kayitlari, key=lambda x: x.get('Tarih', ''))
            await message.reply(f"📊 **Teneke {teneke_no} - Son pH**\n📅 {en_son['Tarih']}\n🔬 pH: {en_son['pH']}\n📝 {en_son.get('Not', '-')}")
    except Exception as e:
        await message.reply(f"Hata: {e}")

@dp.message_handler(commands=['ph_tumu'])
async def ph_tumu_command(message: types.Message):
    try:
        kayitlar = ph_sheet.get_all_records()
        if not kayitlar:
            await message.reply("❌ Hiç pH kaydı yok.")
            return
        tenekeler = {}
        for row in kayitlar:
            teneke = row.get('Teneke_No', 'Bilinmiyor')
            tenekeler.setdefault(teneke, []).append(row)
        cevap = "📊 **TÜM TENEKELER - TÜM pH**\n\n"
        for teneke in sorted(tenekeler.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            cevap += f"🔹 **Teneke {teneke}**\n"
            for k in sorted(tenekeler[teneke], key=lambda x: x.get('Tarih', ''), reverse=True)[:5]:
                cevap += f"   📅 {k['Tarih']}: pH {k['pH']}\n"
            cevap += "\n"
        await message.reply(cevap[:4000])
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@dp.message_handler(commands=['ph_sil'])
async def ph_sil_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ph_sil 1 - Son kaydı sil\n/ph_sil 1 hepsi - Tüm kayıtları sil")
        return
    parcalar = param.split()
    teneke_no = parcalar[0]
    try:
        kayitlar = ph_sheet.get_all_records()
        if not kayitlar:
            await message.reply("❌ Silinecek kayıt yok.")
            return
        teneke_kayitlari = [(idx+2, row) for idx, row in enumerate(kayitlar) if str(row.get('Teneke_No', '')).strip() == teneke_no]
        if not teneke_kayitlari:
            await message.reply(f"❌ Teneke {teneke_no} için pH kaydı yok.")
            return
        if len(parcalar) > 1 and parcalar[1].lower() == 'hepsi':
            for idx, row in reversed(teneke_kayitlari):
                ph_sheet.delete_rows(idx)
            await message.reply(f"✅ Teneke {teneke_no} için TÜM pH kayıtları silindi.")
            return
        son_idx, son_row = teneke_kayitlari[-1]
        ph_sheet.delete_rows(son_idx)
        await message.reply(f"✅ Son pH kaydı silindi:\n📅 {son_row['Tarih']} - Teneke {teneke_no} - pH {son_row['pH']}")
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

# --------------------------- GEÇMİŞ ---------------------------------
@dp.message_handler(commands=['gecmis'])
async def gecmis_command(message: types.Message):
    param = message.get_args()
    try:
        kayitlar = history_oku()
        if not kayitlar:
            await message.reply("📜 Henüz hiç kayıt yok.")
            return
        if not param:
            sonlar = kayitlar[-10:][::-1]
            mesaj = "📜 **SON 10 İŞLEM (ID ile)**\n\n"
            for i, row in enumerate(sonlar, 1):
                kayit_id = len(kayitlar) - i + 1
                mesaj += f"**ID: {kayit_id}** | 📅 {row.get('Tarih', '-')} - {row.get('Islem', '-')}\n   {row.get('Kullanilan_Malzeme_Miktar', '-')[:100]}\n\n"
            await message.reply(mesaj[:4000])
        elif param.lower() == 'hepsi':
            mesaj = "📜 **TÜM İŞLEMLER**\n\n"
            for row in kayitlar[-30:][::-1]:
                mesaj += f"📅 {row.get('Tarih', '-')} - {row.get('Islem', '-')}\n   {row.get('Kullanilan_Malzeme_Miktar', '-')[:100]}\n\n"
            await message.reply(mesaj[:4000])
        else:
            tarih_kayitlari = [(idx+1, row) for idx, row in enumerate(kayitlar) if row.get('Tarih', '') == param]
            if not tarih_kayitlari and '-' in param:
                parcalar = param.split('-')
                if len(parcalar) == 3:
                    if len(parcalar[0]) == 4:
                        ters_param = f"{parcalar[2]}-{parcalar[1]}-{parcalar[0]}"
                        tarih_kayitlari = [(idx+1, row) for idx, row in enumerate(kayitlar) if row.get('Tarih', '') == ters_param]
                    else:
                        ters_param = f"{parcalar[2]}-{parcalar[1]}-{parcalar[0]}"
                        tarih_kayitlari = [(idx+1, row) for idx, row in enumerate(kayitlar) if row.get('Tarih', '') == ters_param]
            if not tarih_kayitlari:
                await message.reply(f"❌ {param} tarihinde kayıt bulunamadı.")
                return
            mesaj = f"📜 **{param} TARİHİNDEKİ İŞLEMLER**\n\n"
            for kayit_id, row in tarih_kayitlari[:20]:
                mesaj += f"**ID: {kayit_id}** | 📅 {row.get('Tarih', '-')} - {row.get('Islem', '-')}\n   {row.get('Kullanilan_Malzeme_Miktar', '-')[:100]}\n\n"
            await message.reply(mesaj[:4000])
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@dp.message_handler(commands=['gecmis_sil'])
async def gecmis_sil_command(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /gecmis_sil 5")
        return
    try:
        kayitlar = history_oku()
        if not kayitlar:
            await message.reply("❌ Silinecek kayıt yok.")
            return
        kayit_id = int(param)
        if kayit_id < 1 or kayit_id > len(kayitlar):
            await message.reply(f"❌ Geçersiz ID. 1 ile {len(kayitlar)} arasında sayı girin.")
            return
        history_sheet.delete_rows(kayit_id + 1)
        await message.reply(f"✅ Kayıt silindi.")
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

# --------------------------- BUTON CALLBACK HANDLER (TAMAMEN YENİLENDİ) ---------------------------------
@dp.callback_query_handler(lambda c: True)
async def process_callback(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    data = callback_query.data
    msg = callback_query.message
    user_id = callback_query.from_user.id

    # ========== ANA MENÜ ==========
    if data == "menu_ana":
        await bot.edit_message_text("🌿 **Yasemin Asistan**\n\nNe yapmak istersin?", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=ana_menu())
        return
    
    elif data == "menu_stok":
        await bot.edit_message_text("📦 **STOK YÖNETİMİ**\n\nNe yapmak istersin?", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=stok_menu())
        return
    
    elif data == "menu_gecmis":
        await bot.edit_message_text("📜 **GEÇMİŞ YÖNETİMİ**\n\nNe yapmak istersin?", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=gecmis_menu())
        return
    
    elif data == "menu_rapor":
        await bot.edit_message_text("📊 **RAPORLAR**\n\nNe yapmak istersin?", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=rapor_menu())
        return
    
    elif data == "menu_hatirlat":
        await bot.edit_message_text("⏰ **HATIRLATMALAR**\n\nNe yapmak istersin?", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=hatirlatma_menu())
        return
    
    elif data == "menu_hava":
        await bot.edit_message_text("🌤️ **HAVA DURUMU**\n\nNe yapmak istersin?", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=hava_menu())
        return
    
    elif data == "menu_ai":
        await bot.edit_message_text("🤖 **YAPAY ZEKA**\n\nNe sormak istersin?", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=ai_menu())
        return
    
    elif data == "menu_yedek":
        await bot.edit_message_text("💾 **YEDEKLEME**\n\nYedek almak ister misin?", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=yedekle_menu())
        return
    
    elif data == "menu_ph":
        await bot.edit_message_text("🔬 **pH YÖNETİMİ**\n\nNe yapmak istersin?", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=ph_menu())
        return

    # ========== STOK ==========
    elif data == "stok_liste":
        stoklar = stok_oku()
        if not stoklar:
            await bot.edit_message_text("❌ Stok dosyası okunamadı veya boş.", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        mesaj = "📦 **ENVANTER LİSTESİ**\n\n"
        for item in stoklar[:25]:
            mesaj += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
        await bot.edit_message_text(mesaj, chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data == "stok_sorgula_ac":
        stoklar = stok_oku()
        if not stoklar:
            await bot.edit_message_text("❌ Stok dosyası okunamadı.", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        await bot.edit_message_text("🔍 **Sorgulamak istediğin malzemeyi seç:**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=malzeme_listesi_menu(stoklar, 0, "sorgula"))
        return
    
    elif data == "stok_sil_ac":
        stoklar = stok_oku()
        if not stoklar:
            await bot.edit_message_text("❌ Stok dosyası okunamadı.", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        await bot.edit_message_text("❌ **Silmek istediğin malzemeyi seç:**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=malzeme_listesi_menu(stoklar, 0, "sil"))
        return
    
    elif data == "stok_ekle_ac":
        bekleyen_ekleme[user_id] = {}
        await bot.edit_message_text("➕ **YENİ MALZEME EKLE**\n\nKategori seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=kategori_menu())
        return
    
    elif data == "stok_dus":
        await bot.edit_message_text("⚠️ Bu özellik hazırlanıyor. /kaydet komutunu kullanabilirsin.", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data == "stok_geri_al":
        if son_kayit_geri_al:
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
                    await bot.edit_message_text(f"✅ Geri alındı:\n📦 {son_kayit_geri_al['malzeme']}\n➕ +{son_kayit_geri_al['kullanilan']} {son_kayit_geri_al['birim']}", chat_id=msg.chat.id, message_id=msg.message_id)
                    son_kayit_geri_al = None
                    return
        await bot.edit_message_text("❌ Geri alınacak işlem yok.", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    elif data.startswith("sorgula_"):
        malzeme_adi = data.replace("sorgula_", "")
        stoklar = stok_oku()
        for item in stoklar:
            if item.get('Malzeme / Alet') == malzeme_adi:
                cevap = f"📦 **{item.get('Malzeme / Alet')}**\n📊 Kalan: {item.get('Kalan Miktar')} {item.get('Birim')}\n📝 Görevi: {item.get('Görevi / Not', '-')}"
                await bot.edit_message_text(cevap, chat_id=msg.chat.id, message_id=msg.message_id)
                return
        await bot.edit_message_text(f"❌ '{malzeme_adi}' bulunamadı.", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    elif data.startswith("sil_"):
        malzeme_adi = data.replace("sil_", "")
        stoklar = stok_oku()
        for item in stoklar:
            if item.get('Malzeme / Alet') == malzeme_adi:
                bekleyen_silme[user_id] = item
                await bot.edit_message_text(f"⚠️ **{malzeme_adi}** silinsin mi?\n\n📊 Miktar: {item.get('Kalan Miktar')} {item.get('Birim')}\n\nBu işlem GERİ DÖNÜŞÜMSÜZDÜR!\n\n30 saniye içinde /evet yazın.", chat_id=msg.chat.id, message_id=msg.message_id)
                await asyncio.sleep(30)
                if user_id in bekleyen_silme:
                    del bekleyen_silme[user_id]
                    await bot.send_message(msg.chat.id, "⏰ Silme iptal edildi.")
                return
        await bot.edit_message_text(f"❌ '{malzeme_adi}' bulunamadı.", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    elif data.startswith("kategori_"):
        kategori = data.replace("kategori_", "")
        bekleyen_ekleme[user_id]['kategori'] = kategori
        await bot.edit_message_text(f"📝 Kategori: {kategori}\n\nMalzeme adını yazın:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("stok_ekle_ac"))
        return

    # ========== GEÇMİŞ ==========
    elif data == "gecmis_son":
        kayitlar = history_oku()
        if not kayitlar:
            await bot.edit_message_text("📜 Henüz hiç kayıt yok.", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        sonlar = kayitlar[-10:][::-1]
        mesaj = "📜 **SON 10 İŞLEM (ID ile)**\n\n"
        for i, row in enumerate(sonlar, 1):
            kayit_id = len(kayitlar) - i + 1
            mesaj += f"**ID: {kayit_id}** | 📅 {row.get('Tarih', '-')} - {row.get('Islem', '-')}\n   {row.get('Kullanilan_Malzeme_Miktar', '-')[:100]}\n\n"
        await bot.edit_message_text(mesaj[:4000], chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data == "gecmis_hepsi":
        kayitlar = history_oku()
        if not kayitlar:
            await bot.edit_message_text("📜 Henüz hiç kayıt yok.", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        mesaj = "📜 **TÜM İŞLEMLER**\n\n"
        for row in kayitlar[-30:][::-1]:
            mesaj += f"📅 {row.get('Tarih', '-')} - {row.get('Islem', '-')}\n   {row.get('Kullanilan_Malzeme_Miktar', '-')[:100]}\n\n"
        await bot.edit_message_text(mesaj[:4000], chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data == "gecmis_tarih_ac":
        bekleyen_gecmis_tarih[user_id] = True
        await bot.edit_message_text("📅 **Tarihli İşlemler**\n\nTarihi yazınız (örn: 12-06-2026):", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_gecmis"))
        return
    
    elif data == "gecmis_sil_ac":
        await bot.edit_message_text("❌ **İşlem Sil**\n\nSilmek istediğiniz işlemin ID'sini yazınız.\n\nID'leri görmek için /gecmis yazın.", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_gecmis"))
        return
    
    elif data == "gecmis_tekrar_ac":
        await bot.edit_message_text("🔄 **İşlemi Tekrar Uygula**\n\nTekrar uygulamak istediğiniz işlemin ID'sini yazınız.\n\nID'leri görmek için /gecmis yazın.", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_gecmis"))
        return
    
    elif data == "islem_ekle":
        bekleyen_islem[user_id] = True
        await bot.edit_message_text("📝 **İŞLEM EKLE**\n\nEklemek istediğin işlemi yaz:\n\nÖrnek: Sera temizliği yapıldı", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_gecmis"))
        return

    # ========== RAPOR ==========
    elif data == "rapor_aylik_ac":
        await bot.edit_message_text("📊 **Aylık Rapor**\n\nAy ve yıl yazınız (örn: 06-2026):", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_rapor"))
        return
    
    elif data == "rapor_gunluk":
        bugun = tarih_format()
        kayitlar = history_oku()
        gunun_islemleri = [row for row in kayitlar if row.get('Tarih', '') == bugun]
        if not gunun_islemleri:
            await bot.edit_message_text(f"📅 **{bugun} GÜNLÜK RAPOR**\n\nBugün hiç işlem yapılmamış.", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        rapor = f"📅 **{bugun} GÜNLÜK RAPOR**\n\n📝 Toplam işlem: {len(gunun_islemleri)}\n\n"
        for row in gunun_islemleri[:15]:
            rapor += f"• {row.get('Islem', '-')}: {row.get('Kullanilan_Malzeme_Miktar', '-')[:50]}\n"
        await bot.edit_message_text(rapor, chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data == "rapor_istatistik":
        kayitlar = history_oku()
        toplam_islem = len(kayitlar)
        malzeme_sayilari = {}
        for row in kayitlar:
            malzeme_str = row.get('Kullanilan_Malzeme_Miktar', '')
            if malzeme_str and malzeme_str != "-":
                for m in malzeme_str.split(','):
                    parcalar = m.strip().split()
                    if len(parcalar) >= 3:
                        malzeme = " ".join(parcalar[2:])
                        malzeme_sayilari[malzeme] = malzeme_sayilari.get(malzeme, 0) + 1
        en_cok = sorted(malzeme_sayilari.items(), key=lambda x: x[1], reverse=True)[:5]
        istatistik = f"📊 **GENEL İSTATİSTİK**\n\n📝 Toplam işlem: {toplam_islem}\n\n🔧 En çok kullanılan malzemeler:\n"
        for malzeme, sayi in en_cok:
            istatistik += f"   • {malzeme}: {sayi} kez\n"
        await bot.edit_message_text(istatistik, chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data == "rapor_grafik_ac":
        await bot.edit_message_text("📉 **Stok Grafiği**\n\nGrafiğini görmek istediğin malzeme adını yaz:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_rapor"))
        return

    # ========== HATIRLATMA ==========
    elif data == "hatirlat_ekle_ac":
        await bot.edit_message_text("➕ **Hatırlatma Ekle**\n\nFormat: gun-ay-yil saat islem\nÖrnek: 30-07-2026 10:00 Sula", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_hatirlat"))
        return
    
    elif data == "hatirlat_liste":
        kayitlar = reminders_sheet.get_all_records()
        if not kayitlar:
            await bot.edit_message_text("Henüz hatırlatma yok.", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        bekleyenler = [(i, row) for i, row in enumerate(kayitlar, 1) if row.get('Durum') == "bekliyor"]
        if not bekleyenler:
            await bot.edit_message_text("✅ Bekleyen hatırlatma yok.", chat_id=msg.chat.id, message_id=msg.message_id)
            return
        mesaj = "📅 **BEKLEYEN HATIRLATMALAR**\n\n"
        for i, row in bekleyenler:
            mesaj += f"**ID: {i}** | {row.get('Tarih')} {row.get('Saat')} - {row.get('Islem')}\n"
        await bot.edit_message_text(mesaj[:4000], chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data == "hatirlat_sil_ac":
        await bot.edit_message_text("❌ **Hatırlatma Sil**\n\nSilmek istediğin hatırlatmanın ID'sini yaz:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_hatirlat"))
        return

    # ========== HAVA ==========
    elif data == "hava_anlik_ac":
        await bot.edit_message_text("🌤️ **Anlık Hava**\n\nŞehir adını yaz:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=sehir_menu())
        return
    
    elif data == "hava_aylik_ac":
        await bot.edit_message_text("📊 **Aylık Hava**\n\nŞehir adını yaz:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=sehir_menu())
        return

    elif data.startswith("sehir_"):
        sehir = data.replace("sehir_", "")
        if "anlik" in str(msg.text):
            try:
                url = f"https://wttr.in/{sehir}?format=%C+%t+%w+%h&m"
                response = requests.get(url, timeout=10)
                await bot.edit_message_text(f"🌤️ **{sehir.upper()} - ŞU ANKİ HAVA**\n\n{response.text.strip()}", chat_id=msg.chat.id, message_id=msg.message_id)
            except:
                await bot.edit_message_text("❌ Hava durumu alınamadı.", chat_id=msg.chat.id, message_id=msg.message_id)
        else:
            try:
                url = f"https://wttr.in/{sehir}?m&format=%l:+%t+%C"
                response = requests.get(url, timeout=10)
                await bot.edit_message_text(f"📊 **{sehir.upper()} - AYLIK HAVA ÖZETİ**\n\n{response.text.strip()}", chat_id=msg.chat.id, message_id=msg.message_id)
            except:
                await bot.edit_message_text("❌ Hava durumu alınamadı.", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    # ========== AI ==========
    elif data == "ai_sor_ac":
        bekleyen_ai[user_id] = True
        await bot.edit_message_text("🤖 **Agnes AI'ya Sor**\n\nSormak istediğin soruyu yaz:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_ai"))
        return

    # ========== YEDEKLE ==========
    elif data == "yedekle_yap":
        await bot.edit_message_text("📦 Yedekleme hazırlanıyor...", chat_id=msg.chat.id, message_id=msg.message_id)
        try:
            inventory_data = inventory_sheet.get_all_values()
            history_data = history_sheet.get_all_values()
            ph_data = ph_sheet.get_all_values()
            reminders_data = reminders_sheet.get_all_values()
            import csv, io, zipfile
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                inv_csv = io.StringIO()
                writer = csv.writer(inv_csv)
                writer.writerows(inventory_data)
                zip_file.writestr('inventory.csv', inv_csv.getvalue().encode('utf-8-sig'))
                hist_csv = io.StringIO()
                writer = csv.writer(hist_csv)
                writer.writerows(history_data)
                zip_file.writestr('history.csv', hist_csv.getvalue().encode('utf-8-sig'))
                ph_csv = io.StringIO()
                writer = csv.writer(ph_csv)
                writer.writerows(ph_data)
                zip_file.writestr('ph_records.csv', ph_csv.getvalue().encode('utf-8-sig'))
                rem_csv = io.StringIO()
                writer = csv.writer(rem_csv)
                writer.writerows(reminders_data)
                zip_file.writestr('reminders.csv', rem_csv.getvalue().encode('utf-8-sig'))
            zip_buffer.seek(0)
            await bot.send_document(msg.chat.id, document=('yasemin_yedek.zip', zip_buffer), caption="📦 Yedek dosyaları")
            await bot.delete_message(msg.chat.id, msg.message_id)
        except Exception as e:
            await bot.edit_message_text(f"❌ Yedekleme hatası: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    # ========== pH ==========
    elif data == "ph_son_ac":
        try:
            kayitlar = ph_sheet.get_all_records()
            if not kayitlar:
                await bot.edit_message_text("❌ Hiç pH kaydı yok.", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            tenekeler = sorted(set([str(row.get('Teneke_No', '')).strip() for row in kayitlar if row.get('Teneke_No')]), key=lambda x: int(x) if x.isdigit() else 0)
            if not tenekeler:
                await bot.edit_message_text("❌ Hiç pH kaydı yok.", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            await bot.edit_message_text("🔬 **Son pH Ölçümü**\n\nTeneke seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=teneke_menu(tenekeler, "ph_son"))
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data.startswith("ph_son_"):
        teneke = data.replace("ph_son_", "")
        try:
            kayitlar = ph_sheet.get_all_records()
            teneke_kayitlari = [row for row in kayitlar if str(row.get('Teneke_No', '')).strip() == teneke]
            if not teneke_kayitlari:
                await bot.edit_message_text(f"❌ Teneke {teneke} için pH kaydı yok.", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            en_son = max(teneke_kayitlari, key=lambda x: x.get('Tarih', ''))
            await bot.edit_message_text(f"📊 **Teneke {teneke} - Son pH**\n📅 {en_son['Tarih']}\n🔬 pH: {en_son['pH']}\n📝 {en_son.get('Not', '-')}", chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data == "ph_tumu_tek_ac":
        try:
            kayitlar = ph_sheet.get_all_records()
            if not kayitlar:
                await bot.edit_message_text("❌ Hiç pH kaydı yok.", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            tenekeler = sorted(set([str(row.get('Teneke_No', '')).strip() for row in kayitlar if row.get('Teneke_No')]), key=lambda x: int(x) if x.isdigit() else 0)
            await bot.edit_message_text("📊 **Tüm pH (Tek Teneke)**\n\nTeneke seçin:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=teneke_menu(tenekeler, "ph_tumu_tek"))
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data.startswith("ph_tumu_tek_"):
        teneke = data.replace("ph_tumu_tek_", "")
        try:
            kayitlar = ph_sheet.get_all_records()
            teneke_kayitlari = [row for row in kayitlar if str(row.get('Teneke_No', '')).strip() == teneke]
            if not teneke_kayitlari:
                await bot.edit_message_text(f"❌ Teneke {teneke} için pH kaydı yok.", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            mesaj = f"📊 **Teneke {teneke} - TÜM pH ÖLÇÜMLERİ**\n\n"
            for k in sorted(teneke_kayitlari, key=lambda x: x.get('Tarih', ''), reverse=True):
                not_str = f" - {k.get('Not', '')}" if k.get('Not') else ""
                mesaj += f"📅 {k['Tarih']}: pH {k['pH']}{not_str}\n"
            await bot.edit_message_text(mesaj, chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data == "ph_tumu":
        try:
            kayitlar = ph_sheet.get_all_records()
            if not kayitlar:
                await bot.edit_message_text("❌ Hiç pH kaydı yok.", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            tenekeler = {}
            for row in kayitlar:
                teneke = row.get('Teneke_No', 'Bilinmiyor')
                tenekeler.setdefault(teneke, []).append(row)
            cevap = "📊 **TÜM TENEKELER - TÜM pH**\n\n"
            for teneke in sorted(tenekeler.keys(), key=lambda x: int(x) if x.isdigit() else 0):
                cevap += f"🔹 **Teneke {teneke}**\n"
                for k in sorted(tenekeler[teneke], key=lambda x: x.get('Tarih', ''), reverse=True)[:5]:
                    cevap += f"   📅 {k['Tarih']}: pH {k['pH']}\n"
                cevap += "\n"
            await bot.edit_message_text(cevap[:4000], chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data == "ph_ekle_ac":
        bekleyen_ph_ekle[user_id] = {}
        await bot.edit_message_text("➕ **pH Ekle**\n\nTeneke numarasını yazınız:", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_ph"))
        return
    
    elif data == "ph_sil_ac":
        try:
            kayitlar = ph_sheet.get_all_records()
            if not kayitlar:
                await bot.edit_message_text("❌ Hiç pH kaydı yok.", chat_id=msg.chat.id, message_id=msg.message_id)
                return
            tenekeler = sorted(set([str(row.get('Teneke_No', '')).strip() for row in kayitlar if row.get('Teneke_No')]), key=lambda x: int(x) if x.isdigit() else 0)
            await bot.edit_message_text("❌ **pH Sil**\n\nHangi tenekedeki pH kaydını silmek istersin?", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=teneke_menu(tenekeler, "ph_sil_sec"))
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return
    
    elif data.startswith("ph_sil_sec_"):
        teneke = data.replace("ph_sil_sec_", "")
        bekleyen_ph_sil = {user_id: teneke}
        await bot.edit_message_text(f"❌ **Teneke {teneke} - pH Sil**\n\nSon kaydı silmek için: /ph_sil {teneke}\nTüm kayıtları silmek için: /ph_sil {teneke} hepsi", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=iptal_menusu("menu_ph"))
        return

# --------------------------- YAZI GİRİŞİ (TÜM BEKLEYENLER) ---------------------------------
@dp.message_handler(content_types=types.ContentTypes.TEXT)
async def handle_text_input(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    # İşlem Ekle
    if user_id in bekleyen_islem:
        del bekleyen_islem[user_id]
        history_ekle("İşlem Eklendi", "", "-", "-", "", text)
        await message.reply(f"✅ İşlem kaydedildi!\n\n📝 {text}")
        return

    # Geçmişe Not Ekle (eski, kaldırıldı ama kalırsa sorun olmasın)
    if user_id in bekleyen_not:
        del bekleyen_not[user_id]
        history_ekle("Not", "", "-", "-", "", text)
        await message.reply(f"✅ Not kaydedildi!\n\n📝 {text}")
        return

    # AI Sor
    if user_id in bekleyen_ai:
        del bekleyen_ai[user_id]
        msg = await message.reply("🤔 Agnes düşünüyor...")
        cevap = ask_agnes(text, str(user_id))
        baglam_guncelle(str(user_id), text, cevap)
        for parca in mesaj_parcala(cevap):
            await bot.send_message(chat_id=message.chat.id, text=f"🤖 **Agnes AI:**\n\n{parca}")
        await bot.delete_message(msg.chat.id, msg.message_id)
        return

    # Tarihli Geçmiş
    if user_id in bekleyen_gecmis_tarih:
        del bekleyen_gecmis_tarih[user_id]
        kayitlar = history_oku()
        tarih_kayitlari = [(idx+1, row) for idx, row in enumerate(kayitlar) if row.get('Tarih', '') == text]
        if not tarih_kayitlari and '-' in text:
            parcalar = text.split('-')
            if len(parcalar) == 3:
                if len(parcalar[0]) == 4:
                    ters_param = f"{parcalar[2]}-{parcalar[1]}-{parcalar[0]}"
                    tarih_kayitlari = [(idx+1, row) for idx, row in enumerate(kayitlar) if row.get('Tarih', '') == ters_param]
                else:
                    ters_param = f"{parcalar[2]}-{parcalar[1]}-{parcalar[0]}"
                    tarih_kayitlari = [(idx+1, row) for idx, row in enumerate(kayitlar) if row.get('Tarih', '') == ters_param]
        if not tarih_kayitlari:
            await message.reply(f"❌ {text} tarihinde kayıt bulunamadı.")
            return
        mesaj = f"📜 **{text} TARİHİNDEKİ İŞLEMLER**\n\n"
        for kayit_id, row in tarih_kayitlari[:20]:
            mesaj += f"**ID: {kayit_id}** | 📅 {row.get('Tarih', '-')} - {row.get('Islem', '-')}\n   {row.get('Kullanilan_Malzeme_Miktar', '-')[:100]}\n\n"
        await message.reply(mesaj[:4000])
        return

    # İşlem Sil (ID ile)
    if "gecmis_sil_ac" in str(message):
        try:
            kayit_id = int(text)
            kayitlar = history_oku()
            if kayit_id < 1 or kayit_id > len(kayitlar):
                await message.reply(f"❌ Geçersiz ID. 1 ile {len(kayitlar)} arasında sayı girin.")
                return
            history_sheet.delete_rows(kayit_id + 1)
            await message.reply(f"✅ {kayit_id} ID'li kayıt silindi.")
        except:
            await message.reply("❌ Geçersiz ID. Lütfen sayı giriniz.")
        return

    # İşlemi Tekrar Uygula
    if "gecmis_tekrar_ac" in str(message):
        try:
            kayit_id = int(text)
            kayitlar = history_oku()
            if kayit_id < 1 or kayit_id > len(kayitlar):
                await message.reply(f"❌ Geçersiz ID. 1 ile {len(kayitlar)} arasında sayı girin.")
                return
            row = kayitlar[kayit_id - 1]
            basarili, sonuc = islem_tekrar_uygula(row, kayit_id)
            if basarili:
                await message.reply(f"✅ {sonuc}")
            else:
                await message.reply(f"❌ {sonuc}")
        except:
            await message.reply("❌ Geçersiz ID.")
        return

    # Aylık Rapor
    if user_id in bekleyen_rapor_aylik:
        del bekleyen_rapor_aylik[user_id]
        try:
            kayitlar = history_oku()
            if not kayitlar:
                await message.reply("❌ Henüz hiç kayıt yok.")
                return
            ay_kontrol1 = f"{text[3:]}-{text[:2]}" if '-' in text else ""
            ay_kontrol2 = f"-{text[3:]}-{text[:2]}" if '-' in text else ""
            ay_kontro13 = text
            ay_kayitlari = [row for row in kayitlar if ay_kontrol1 in row.get('Tarih', '') or ay_kontrol2 in row.get('Tarih', '') or ay_kontro13 in row.get('Tarih', '')]
            if not ay_kayitlari:
                await message.reply(f"❌ {text} ayında işlem bulunamadı.")
                return
            toplam_islem = len(ay_kayitlari)
            islem_turleri = {}
            malzeme_kullanimlari = {}
            toplam_miktar = 0
            miktar_sayac = 0
            for row in ay_kayitlari:
                tur = row.get('Islem', 'Bilinmiyor')
                islem_turleri[tur] = islem_turleri.get(tur, 0) + 1
                malzeme_str = row.get('Kullanilan_Malzeme_Miktar', '')
                if malzeme_str and malzeme_str != "-":
                    parcalar = malzeme_str.split()
                    if len(parcalar) >= 3:
                        try:
                            miktar = float(parcalar[0].replace(',', '.'))
                            malzeme = " ".join(parcalar[2:])
                            toplam_miktar += miktar
                            miktar_sayac += 1
                            malzeme_kullanimlari[malzeme] = malzeme_kullanimlari.get(malzeme, 0) + 1
                        except:
                            pass
            en_cok_malzeme = max(malzeme_kullanimlari.items(), key=lambda x: x[1])[0] if malzeme_kullanimlari else "Yok"
            ortalama_miktar = toplam_miktar / miktar_sayac if miktar_sayac > 0 else 0
            rapor = f"📊 **{text} AYLIK RAPORU**\n\n📝 Toplam işlem: {toplam_islem}\n🔧 En çok kullanılan malzeme: {en_cok_malzeme}\n📦 Ortalama kullanım: {ortalama_miktar:.1f} gr\n\n📋 İşlem türleri:\n"
            for tur, sayi in sorted(islem_turleri.items(), key=lambda x: x[1], reverse=True):
                rapor += f"   • {tur}: {sayi} kez\n"
            await message.reply(rapor)
        except Exception as e:
            await message.reply(f"❌ Rapor alınamadı: {e}")
        return

    # Stok Grafiği
    if user_id in bekleyen_grafik:
        del bekleyen_grafik[user_id]
        try:
            kayitlar = history_oku()
            gecmisler = [row for row in kayitlar if text.lower() in row.get('Kullanilan_Malzeme_Miktar', '').lower()]
            if not gecmisler:
                await message.reply(f"❌ '{text}' için geçmiş kayıt bulunamadı.")
                return
            sonlar = gecmisler[-10:][::-1]
            grafik = f"📊 **'{text.upper()}' STOK GRAFİĞİ (Son 10 kullanım)**\n\n"
            for row in sonlar:
                grafik += f"📅 {row.get('Tarih', '-')}: {row.get('Kullanilan_Malzeme_Miktar', '-')}\n"
            await message.reply(grafik)
        except Exception as e:
            await message.reply(f"❌ Grafik alınamadı: {e}")
        return

    # Hatırlatma Ekle
    if user_id in bekleyen_hatirlat:
        del bekleyen_hatirlat[user_id]
        parcalar = text.split(maxsplit=2)
        if len(parcalar) < 3:
            await message.reply("❌ Format: gun-ay-yil saat islem")
            return
        tarih, saat, islem = parcalar
        if hatirlatma_ekle(tarih, saat, islem):
            await message.reply(f"✅ Hatırlatma eklendi!\n📅 {tarih} {saat}\n📝 {islem}")
        else:
            await message.reply("❌ Hata.")
        return

    # Hatırlatma Sil (ID ile)
    if user_id in bekleyen_hatirlat_sil:
        del bekleyen_hatirlat_sil[user_id]
        try:
            kayitlar = reminders_sheet.get_all_records()
            idx = int(text) - 1
            if idx < 0 or idx >= len(kayitlar):
                await message.reply("❌ Geçersiz ID.")
                return
            reminders_sheet.delete_rows(idx + 2)
            await message.reply(f"✅ Hatırlatma silindi.")
        except:
            await message.reply("❌ Hata oluştu.")
        return

    # Yeni Malzeme Ekle - Malzeme Adı
    if user_id in bekleyen_ekleme and 'kategori' in bekleyen_ekleme[user_id] and 'malzeme_adi' not in bekleyen_ekleme[user_id]:
        bekleyen_ekleme[user_id]['malzeme_adi'] = text
        await message.reply(f"📝 Malzeme adı: {text}\n\nMiktar yazınız (örn: 1000):", reply_markup=iptal_menusu("stok_ekle_ac"))
        return

    # Yeni Malzeme Ekle - Miktar
    if user_id in bekleyen_ekleme and 'malzeme_adi' in bekleyen_ekleme[user_id] and 'miktar' not in bekleyen_ekleme[user_id]:
        try:
            miktar = float(text.replace(',', '.'))
            bekleyen_ekleme[user_id]['miktar'] = str(miktar).replace('.', ',')
            await message.reply(f"📦 Miktar: {text}\n\nBirim seçin:", reply_markup=birim_menu())
        except:
            await message.reply("❌ Geçersiz miktar. Lütfen sayı giriniz.", reply_markup=iptal_menusu("stok_ekle_ac"))
        return

    # Yeni Malzeme Ekle - Görev
    if user_id in bekleyen_ekleme and 'birim' in bekleyen_ekleme[user_id] and 'gorev' not in bekleyen_ekleme[user_id]:
        bekleyen_ekleme[user_id]['gorev'] = text
        veri = bekleyen_ekleme[user_id]
        stoklar = stok_oku()
        yeni_kayit = {
            'Kategori': veri['kategori'],
            'Malzeme / Alet': veri['malzeme_adi'],
            'Başlangıç Miktarı': veri['miktar'],
            'Kullanılan': '0',
            'Kalan Miktar': veri['miktar'],
            'Birim': veri['birim'],
            'Görevi / Not': text
        }
        stoklar.append(yeni_kayit)
        if stok_kaydet(stoklar):
            await message.reply(f"✅ **'{veri['malzeme_adi']}'** envantere eklendi!\n\n📦 Miktar: {veri['miktar']} {veri['birim']}\n📝 Görevi: {text}")
            history_ekle("ENVANTERE EKLENDİ", veri['malzeme_adi'], veri['miktar'], veri['birim'])
        else:
            await message.reply("❌ Ekleme sırasında hata oluştu.")
        del bekleyen_ekleme[user_id]
        return

    # pH Ekle - Teneke No
    if user_id in bekleyen_ph_ekle and 'teneke' not in bekleyen_ph_ekle[user_id]:
        bekleyen_ph_ekle[user_id]['teneke'] = text
        await message.reply(f"🔬 Teneke: {text}\n\npH değerini yazınız (örn: 6.5):", reply_markup=iptal_menusu("menu_ph"))
        return

    # pH Ekle - pH Değeri
    if user_id in bekleyen_ph_ekle and 'teneke' in bekleyen_ph_ekle[user_id] and 'ph' not in bekleyen_ph_ekle[user_id]:
        bekleyen_ph_ekle[user_id]['ph'] = text
        await message.reply(f"🔬 pH: {text}\n\nVarsa not yazınız (isteğe bağlı):", reply_markup=iptal_menusu("menu_ph"))
        return

    # pH Ekle - Not (opsiyonel)
    if user_id in bekleyen_ph_ekle and 'ph' in bekleyen_ph_ekle[user_id]:
        teneke = bekleyen_ph_ekle[user_id]['teneke']
        ph = bekleyen_ph_ekle[user_id]['ph']
        not_metni = text if text else "Bot ile eklendi"
        try:
            ph_sheet.append_row([tarih_format(), teneke, "-", ph, not_metni])
            await message.reply(f"✅ pH kaydı eklendi!\n📅 {tarih_format()} - Teneke {teneke} - pH {ph}\n📝 {not_metni}")
        except Exception as e:
            await message.reply(f"❌ Hata: {e}")
        del bekleyen_ph_ekle[user_id]
        return

    # Diğer tüm mesajlar
    else:
        await message.reply("❓ Anlamadım. /menu yazarak ana menüyü açabilirsiniz.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
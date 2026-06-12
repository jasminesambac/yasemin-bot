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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

# Sulama akışı için geçici hafıza
sulama_oturum = {}  # {user_id: {'su': miktar, 'birim': birim, 'eklenenler': [], 'toplam_malzeme': []}}

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

def stoktan_dus_kontrol(malzeme_adi, miktar, birim):
    """Stoktan düşer ve uyarı varsa döndürür"""
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

# ==================== BUTONLU MENÜLER ====================

# Ana menü
def ana_menu():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📦 Stok", callback_data="menu_stok"),
        InlineKeyboardButton("🔬 pH", callback_data="menu_ph"),
        InlineKeyboardButton("📜 Geçmiş", callback_data="menu_gecmis"),
        InlineKeyboardButton("📊 Rapor", callback_data="menu_rapor"),
        InlineKeyboardButton("⏰ Hatırlatma", callback_data="menu_hatirlat"),
        InlineKeyboardButton("🌤️ Hava", callback_data="menu_hava"),
        InlineKeyboardButton("🤖 AI Sor", callback_data="menu_ai"),
        InlineKeyboardButton("💾 Yedekle", callback_data="menu_yedek")
    )
    return keyboard

# Stok alt menüsü
def stok_menu():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("📋 Stok Listesi", callback_data="stok_liste"),
        InlineKeyboardButton("🔍 Stok Sorgula", callback_data="stok_sorgula"),
        InlineKeyboardButton("⬇️ Stoktan Düş", callback_data="stok_dus"),
        InlineKeyboardButton("➕ Yeni Malzeme Ekle", callback_data="stok_ekle"),
        InlineKeyboardButton("❌ Malzeme Sil", callback_data="stok_sil"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_ana")
    )
    return keyboard

# Sulama (Stoktan düş için malzeme seçimi)
def malzeme_menu(malzemeler, page=0):
    keyboard = InlineKeyboardMarkup(row_width=2)
    sayfa_malzemeler = malzemeler[page*6:(page+1)*6]
    for m in sayfa_malzemeler:
        keyboard.add(InlineKeyboardButton(m.get('Malzeme / Alet', '-')[:30], callback_data=f"malzeme_sec_{m.get('Malzeme / Alet', '-')}"))
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Önceki", callback_data=f"malzeme_page_{page-1}"))
    if len(malzemeler) > (page+1)*6:
        nav_buttons.append(InlineKeyboardButton("Sonraki ▶️", callback_data=f"malzeme_page_{page+1}"))
    if nav_buttons:
        keyboard.row(*nav_buttons)
    
    keyboard.add(InlineKeyboardButton("🔙 Geri", callback_data="stok_dus"))
    return keyboard

# Miktar seçim menüsü
def miktar_menu(malzeme_adi, birim):
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        InlineKeyboardButton("1", callback_data=f"miktar_1_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("5", callback_data=f"miktar_5_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("10", callback_data=f"miktar_10_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("20", callback_data=f"miktar_20_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("50", callback_data=f"miktar_50_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("100", callback_data=f"miktar_100_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("✏️ Özel", callback_data=f"miktar_ozel_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("🔙 Geri", callback_data="stok_dus")
    )
    return keyboard

# Sulama akışı - su miktarı
def su_miktar_menu():
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        InlineKeyboardButton("1 L", callback_data="su_1"),
        InlineKeyboardButton("5 L", callback_data="su_5"),
        InlineKeyboardButton("10 L", callback_data="su_10"),
        InlineKeyboardButton("20 L", callback_data="su_20"),
        InlineKeyboardButton("50 L", callback_data="su_50"),
        InlineKeyboardButton("✏️ Özel", callback_data="su_ozel"),
        InlineKeyboardButton("🔙 Geri", callback_data="menu_ana")
    )
    return keyboard

# Sulama akışı - malzeme seçimi (ekleme için)
def sulama_malzeme_menu(malzemeler, page=0):
    keyboard = InlineKeyboardMarkup(row_width=2)
    sayfa_malzemeler = malzemeler[page*6:(page+1)*6]
    for m in sayfa_malzemeler:
        keyboard.add(InlineKeyboardButton(f"➕ {m.get('Malzeme / Alet', '-')[:25]}", callback_data=f"sulama_ekle_{m.get('Malzeme / Alet', '-')}"))
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Önceki", callback_data=f"sulama_page_{page-1}"))
    if len(malzemeler) > (page+1)*6:
        nav_buttons.append(InlineKeyboardButton("Sonraki ▶️", callback_data=f"sulama_page_{page+1}"))
    if nav_buttons:
        keyboard.row(*nav_buttons)
    
    keyboard.add(
        InlineKeyboardButton("✅ Kaydet ve Bitir", callback_data="sulama_kaydet"),
        InlineKeyboardButton("❌ İptal", callback_data="sulama_iptal")
    )
    return keyboard

# Sulama akışı - eklenen malzeme için miktar seçimi
def sulama_miktar_menu(malzeme_adi, birim):
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        InlineKeyboardButton("1", callback_data=f"sulama_miktar_1_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("5", callback_data=f"sulama_miktar_5_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("10", callback_data=f"sulama_miktar_10_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("20", callback_data=f"sulama_miktar_20_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("50", callback_data=f"sulama_miktar_50_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("100", callback_data=f"sulama_miktar_100_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("✏️ Özel", callback_data=f"sulama_miktar_ozel_{malzeme_adi}_{birim}"),
        InlineKeyboardButton("🔙 Geri", callback_data="sulama_geri")
    )
    return keyboard

# ==================== HAVA DURUMU ====================
@dp.message_handler(commands=['hava'])
async def hava(message: types.Message):
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
async def hava_aylik(message: types.Message):
    sehir = message.get_args()
    if not sehir:
        sehir = "Istanbul"
    try:
        url = f"https://wttr.in/{sehir}?m&format=%l:+%t+%C"
        response = requests.get(url, timeout=10)
        await message.reply(f"📊 **{sehir.upper()} - AYLIK HAVA ÖZETİ**\n\n{response.text.strip()}")
    except:
        await message.reply("❌ Hava durumu alınamadı.")

# ==================== KOMUTLAR ====================
@dp.message_handler(commands=['menu', 'start'])
async def menu(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan**\n\nNe yapmak istersin?", reply_markup=ana_menu())

@dp.message_handler(commands=['sor'])
async def sor(message: types.Message):
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

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

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

# ==================== KAYDET (Yazarak) ====================
@dp.message_handler(commands=['kaydet'])
async def kaydet(message: types.Message):
    global son_kayit_geri_al
    islem = message.get_args()
    if not islem:
        await message.reply("Örnek: /kaydet 5 gr NPK veya /kaydet Sera kuruldu\n\nVeya /menu ile butonlu menüyü kullan.")
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
                
                son_kayit_geri_al = {
                    'malzeme': malzeme_adi,
                    'eski_kalan': 'Stok bol',
                    'kullanilan': miktar,
                    'birim': birim
                }
                
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
                
                son_kayit_geri_al = {
                    'malzeme': malzeme_adi,
                    'eski_kalan': eski_kalan,
                    'kullanilan': miktar,
                    'birim': birim
                }
                
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
        return

# ==================== BUTON CALLBACK HANDLER ====================
@dp.callback_query_handler(lambda c: True)
async def process_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    await bot.answer_callback_query(callback_query.id)
    
    # Ana menü
    if data == "menu_ana":
        await bot.edit_message_text("🌿 **Yasemin Asistan**\n\nNe yapmak istersin?", 
                                    chat_id=callback_query.message.chat.id, 
                                    message_id=callback_query.message.message_id,
                                    reply_markup=ana_menu())
    
    elif data == "menu_stok":
        await bot.edit_message_text("📦 **STOK YÖNETİMİ**\n\nNe yapmak istersin?",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    reply_markup=stok_menu())
    
    elif data == "stok_liste":
        stoklar = stok_oku()
        if not stoklar:
            await bot.edit_message_text("❌ Stok dosyası okunamadı veya boş.",
                                        chat_id=callback_query.message.chat.id,
                                        message_id=callback_query.message.message_id)
            return
        mesaj = "📦 **ENVANTER LİSTESİ**\n\n"
        for item in stoklar[:25]:
            mesaj += f"• {item.get('Malzeme / Alet')}: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
        await bot.edit_message_text(mesaj,
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
        await asyncio.sleep(10)
        await bot.send_message(callback_query.message.chat.id, "📦 Ana menüye dönmek için /menu yazın.")
    
    elif data == "stok_sorgula":
        await bot.edit_message_text("🔍 Malzeme adını yazın:\n\nÖrnek: NPK",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    elif data == "stok_dus":
        stoklar = stok_oku()
        if not stoklar:
            await bot.edit_message_text("❌ Stok dosyası okunamadı.",
                                        chat_id=callback_query.message.chat.id,
                                        message_id=callback_query.message.message_id)
            return
        
        # Sulama akışını başlat
        sulama_oturum[user_id] = {'su': None, 'birim': 'L', 'eklenenler': [], 'toplam_malzeme': []}
        await bot.edit_message_text("💧 **SULAMA İŞLEMİ**\n\nSu miktarını seçin:",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    reply_markup=su_miktar_menu())
    
    elif data == "stok_ekle":
        await bot.edit_message_text("➕ **YENİ MALZEME EKLE**\n\nFormat: Ad;Miktar;Birim;Görev\n\nÖrnek: NPK;1000;gr;Gübre",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    elif data == "stok_sil":
        await bot.edit_message_text("❌ Silmek istediğin malzemenin adını yazın:\n\nÖrnek: Test",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    # Sulama akışı - su miktarı seçimi
    elif data.startswith("su_"):
        miktar = data.split("_")[1]
        if miktar == "ozel":
            await bot.edit_message_text("💧 Özel su miktarını L cinsinden yazın:\n\nÖrnek: 15",
                                        chat_id=callback_query.message.chat.id,
                                        message_id=callback_query.message.message_id)
            return
        
        sulama_oturum[user_id]['su'] = float(miktar)
        sulama_oturum[user_id]['birim'] = 'L'
        
        # Malzeme listesini göster
        stoklar = stok_oku()
        malzemeler = [item for item in stoklar if item.get('Kalan Miktar') != '0' and item.get('Kalan Miktar') != 'Stok bol']
        sulama_oturum[user_id]['malzeme_listesi'] = malzemeler
        sulama_oturum[user_id]['sayfa'] = 0
        
        await bot.edit_message_text(f"💧 **SULAMA İŞLEMİ**\n\nSu: {miktar} L\n\n🌿 Eklemek istediğin malzemeyi seç:",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    reply_markup=sulama_malzeme_menu(malzemeler, 0))
    
    # Sulama akışı - sayfalama
    elif data.startswith("sulama_page_"):
        page = int(data.split("_")[2])
        malzemeler = sulama_oturum[user_id]['malzeme_listesi']
        sulama_oturum[user_id]['sayfa'] = page
        
        su = sulama_oturum[user_id]['su']
        await bot.edit_message_text(f"💧 **SULAMA İŞLEMİ**\n\nSu: {su} L\n\n🌿 Eklemek istediğin malzemeyi seç:",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    reply_markup=sulama_malzeme_menu(malzemeler, page))
    
    # Sulama akışı - malzeme ekleme
    elif data.startswith("sulama_ekle_"):
        malzeme_adi = data.replace("sulama_ekle_", "")
        # Malzemenin birimini bul
        stoklar = stok_oku()
        birim = "gr"
        for item in stoklar:
            if item.get('Malzeme / Alet') == malzeme_adi:
                birim = item.get('Birim', 'gr')
                break
        
        sulama_oturum[user_id]['secili_malzeme'] = malzeme_adi
        sulama_oturum[user_id]['secili_birim'] = birim
        
        await bot.edit_message_text(f"⚙️ **{malzeme_adi}** için miktar seçin ({birim}):",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    reply_markup=sulama_miktar_menu(malzeme_adi, birim))
    
    # Sulama akışı - miktar seçimi
    elif data.startswith("sulama_miktar_"):
        parts = data.split("_")
        miktar = parts[2]
        malzeme_adi = parts[3]
        birim = parts[4]
        
        if miktar == "ozel":
            await bot.edit_message_text(f"✏️ **{malzeme_adi}** için miktarı {birim} cinsinden yazın:\n\nÖrnek: 25",
                                        chat_id=callback_query.message.chat.id,
                                        message_id=callback_query.message.message_id)
            return
        
        miktar_float = float(miktar)
        
        # Stoktan düş
        basarili, sonuc, esik, uyari_birimi = stoktan_dus_kontrol(malzeme_adi, miktar_float, birim)
        
        if not basarili:
            await bot.edit_message_text(f"❌ Yetersiz stok! Kalan: {sonuc} {birim}",
                                        chat_id=callback_query.message.chat.id,
                                        message_id=callback_query.message.message_id)
            return
        
        # Eklenenleri kaydet
        sulama_oturum[user_id]['eklenenler'].append(f"{miktar_float} {birim} {malzeme_adi}")
        sulama_oturum[user_id]['toplam_malzeme'].append((malzeme_adi, miktar_float, birim))
        
        # Stok uyarısı varsa göster
        uyari_mesaji = ""
        if esik:
            uyari_mesaji = f"\n\n⚠️ **STOK UYARISI!** {malzeme_adi} {esik} {uyari_birimi} altına düştü!"
        
        # Devam et
        su = sulama_oturum[user_id]['su']
        malzemeler = sulama_oturum[user_id]['malzeme_listesi']
        page = sulama_oturum[user_id].get('sayfa', 0)
        
        eklenen_text = "\n".join([f"   • {e}" for e in sulama_oturum[user_id]['eklenenler']])
        
        await bot.edit_message_text(f"💧 **SULAMA İŞLEMİ**\n\nSu: {su} L\n\n✅ Eklendi: {miktar_float} {birim} {malzeme_adi}{uyari_mesaji}\n\n📝 Eklenenler:\n{eklenen_text}\n\n🌿 Devam et:",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    reply_markup=sulama_malzeme_menu(malzemeler, page))
    
    # Sulama akışı - geri
    elif data == "sulama_geri":
        su = sulama_oturum[user_id]['su']
        malzemeler = sulama_oturum[user_id]['malzeme_listesi']
        page = sulama_oturum[user_id].get('sayfa', 0)
        
        await bot.edit_message_text(f"💧 **SULAMA İŞLEMİ**\n\nSu: {su} L\n\n🌿 Eklemek istediğin malzemeyi seç:",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    reply_markup=sulama_malzeme_menu(malzemeler, page))
    
    # Sulama akışı - kaydet
    elif data == "sulama_kaydet":
        su = sulama_oturum[user_id]['su']
        eklenenler = sulama_oturum[user_id]['eklenenler']
        toplam_malzeme = sulama_oturum[user_id]['toplam_malzeme']
        
        if eklenenler:
            malzeme_str = " + ".join(eklenenler)
            islem_metni = f"Sulama: {su} L" + (f" + {malzeme_str}" if malzeme_str else "")
        else:
            islem_metni = f"Sulama: {su} L (sadece su)"
        
        history_ekle("İşlem", islem_metni, "-", "-")
        
        # Sulama oturumunu temizle
        if user_id in sulama_oturum:
            del sulama_oturum[user_id]
        
        await bot.edit_message_text(f"✅ **İşlem kaydedildi!**\n\n📝 {islem_metni}",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    # Sulama akışı - iptal
    elif data == "sulama_iptal":
        if user_id in sulama_oturum:
            del sulama_oturum[user_id]
        await bot.edit_message_text("❌ İşlem iptal edildi.",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    # Diğer menüler
    elif data == "menu_ph":
        await bot.edit_message_text("🔬 **pH KOMUTLARI**\n\n/ph [teneke] - Son pH\n/ph [teneke] hepsi - Tüm pH\n/ph_tumu - Tüm tenekeler\n/ph_ekle [teneke] [ph] - pH ekle",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    elif data == "menu_gecmis":
        await bot.edit_message_text("📜 **GEÇMİŞ KOMUTLARI**\n\n/gecmis - Son 10 işlem\n/gecmis hepsi - Tüm geçmiş\n/gecmis [tarih] - Tarihli işlemler\n/gecmis_sil [id] - İşlem sil",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    elif data == "menu_rapor":
        await bot.edit_message_text("📊 **RAPOR KOMUTLARI**\n\n/rapor_aylik [aa-yyyy] - Aylık rapor\n/rapor_gunluk - Günlük rapor\n/istatistik - Genel istatistik\n/grafik [malzeme] - Stok grafiği",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    elif data == "menu_hatirlat":
        await bot.edit_message_text("⏰ **HATIRLATMA KOMUTLARI**\n\n/hatirlat [gun-ay-yil] [saat] [işlem] - Hatırlatma ekle\n/hatirlatmalar - Bekleyen hatırlatmalar\n/hatirlat_sil [id] - Hatırlatma sil",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    elif data == "menu_hava":
        await bot.edit_message_text("🌤️ **HAVA DURUMU**\n\n/hava [şehir] - Anlık hava\n/hava_aylik [şehir] - Aylık hava",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    elif data == "menu_ai":
        await bot.edit_message_text("🤖 **YAPAY ZEKA**\n\n/sor [soru] - Agnes AI'ya sor",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)
    
    elif data == "menu_yedek":
        await bot.edit_message_text("💾 **YEDEKLEME**\n\n/yedekle - Tüm CSV'leri yedekle",
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id)

# ==================== DİĞER KOMUTLAR (Kısayollar) ====================
@dp.message_handler(commands=['stok'])
async def stok(message: types.Message):
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
            cevap = f"📦 **{item.get('Malzeme / Alet')}**\n"
            cevap += f"📊 Kalan: {item.get('Kalan Miktar')} {item.get('Birim')}\n"
            cevap += f"📝 Görevi: {item.get('Görevi / Not', '-')}\n\n"
            
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
async def ekle_envanter(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ekle NPK;1000;gr;Gübre\n\nFormat: Ad;Miktar;Birim;Görevi")
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
        await message.reply(f"✅ **'{malzeme_adi}'** envantere eklendi!\n\n📦 Miktar: {miktar} {birim}\n📝 Görevi: {gorev}")
        history_ekle("ENVANTERE EKLENDİ", malzeme_adi, miktar, birim)
    else:
        await message.reply("❌ Ekleme sırasında hata oluştu.")

@dp.message_handler(commands=['sil'])
async def sil_stok(message: types.Message):
    global silinecek_malzeme
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /sil Test")
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
    
    silinecek_malzeme = eslesenler[0]
    await message.reply(f"⚠️ **{silinecek_malzeme.get('Malzeme / Alet')}** silinsin mi?\n\n"
                       f"📊 Miktar: {silinecek_malzeme.get('Kalan Miktar')} {silinecek_malzeme.get('Birim')}\n\n"
                       f"**Bu işlem GERİ DÖNÜŞÜMSÜZDÜR!**\n\n"
                       f"30 saniye içinde `/evet` yazın.")
    await asyncio.sleep(30)
    if silinecek_malzeme:
        silinecek_malzeme = None
        await message.reply("⏰ Silme iptal edildi.")

@dp.message_handler(commands=['evet'])
async def evet_sil(message: types.Message):
    global silinecek_malzeme
    if not silinecek_malzeme:
        await message.reply("❌ Silinecek malzeme yok. Önce /sil komutunu kullanın.")
        return
    
    stoklar = stok_oku()
    malzeme_adi = silinecek_malzeme.get('Malzeme / Alet')
    miktar = silinecek_malzeme.get('Kalan Miktar')
    birim = silinecek_malzeme.get('Birim')
    
    yeni_stoklar = [item for item in stoklar if item.get('Malzeme / Alet') != malzeme_adi]
    
    if stok_kaydet(yeni_stoklar):
        await message.reply(f"✅ **'{malzeme_adi}'** envanterden silindi.\n\n📊 Miktar: {miktar} {birim}")
        history_ekle("ENVANTERDEN SİLİNDİ", malzeme_adi, miktar, birim)
    else:
        await message.reply("❌ Silme işlemi sırasında hata oluştu.")
    
    silinecek_malzeme = None

# ==================== pH KOMUTLARI ====================
@dp.message_handler(commands=['ph_ekle'])
async def ph_ekle(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ph_ekle 1 6.5\n\nNot eklemek için: /ph_ekle 1 6.5 Çamur testi")
        return
    
    parcalar = param.split(maxsplit=2)
    if len(parcalar) < 2:
        await message.reply("Format: /ph_ekle teneke_no pH [not]")
        return
    
    teneke = parcalar[0]
    ph = parcalar[1]
    not_metni = parcalar[2] if len(parcalar) > 2 else "Bot ile eklendi"
    
    try:
        with open('ph_records.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih_format(), teneke, "-", ph, not_metni])
        await message.reply(f"✅ pH kaydı eklendi!\n📅 {tarih_format()} - Teneke {teneke} - pH {ph}\n📝 {not_metni}")
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
            kayitlar = [row for row in reader if row.get('Teneke_No', '').strip() == teneke_no]
        
        if not kayitlar:
            await message.reply(f"❌ Teneke {teneke_no} için pH kaydı yok.")
            return
        
        if tumu:
            mesaj = f"📊 **Teneke {teneke_no} - TÜM pH ÖLÇÜMLERİ**\n\n"
            for k in sorted(kayitlar, key=lambda x: x.get('Tarih', ''), reverse=True):
                not_str = f" - {k.get('Not', '')}" if k.get('Not') else ""
                bolge_str = f" ({k.get('Bolge', '-')})" if k.get('Bolge') and k.get('Bolge') != '-' else ""
                mesaj += f"📅 {k['Tarih']}: pH {k['pH']}{bolge_str}{not_str}\n"
                if len(mesaj) > 3800:
                    mesaj += "\n*Devamı için /ph 1 devam*"
                    break
            await message.reply(mesaj)
        else:
            en_son = max(kayitlar, key=lambda x: x.get('Tarih', ''))
            not_str = f"\n📝 Not: {en_son.get('Not', '-')}" if en_son.get('Not') else ""
            bolge_str = f"📍 Bölge: {en_son.get('Bolge', '-')}\n" if en_son.get('Bolge') and en_son.get('Bolge') != '-' else ""
            await message.reply(
                f"📊 **Teneke {teneke_no} - Son pH**\n"
                f"📅 {en_son['Tarih']}\n"
                f"🔬 pH: {en_son['pH']}\n"
                f"{bolge_str}{not_str}"
            )
    except Exception as e:
        await message.reply(f"Hata: {e}")

@dp.message_handler(commands=['ph_tumu'])
async def ph_tumu(message: types.Message):
    try:
        with open('ph_records.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=',')
            tum_kayitlar = list(reader)
        
        if not tum_kayitlar:
            await message.reply("❌ Hiç pH kaydı yok.")
            return
        
        tenekeler = {}
        for row in tum_kayitlar:
            teneke = row.get('Teneke_No', 'Bilinmiyor')
            if teneke not in tenekeler:
                tenekeler[teneke] = []
            tenekeler[teneke].append(row)
        
        cevap = "📊 **TÜM TENEKELER - TÜM pH ÖLÇÜMLERİ**\n\n"
        
        for teneke in sorted(tenekeler.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            cevap += f"🔹 **Teneke {teneke}**\n"
            kayitlar = sorted(tenekeler[teneke], key=lambda x: x.get('Tarih', ''), reverse=True)
            for k in kayitlar[:10]:
                not_str = f" - {k.get('Not', '')}" if k.get('Not') else ""
                bolge_str = f" ({k.get('Bolge', '-')})" if k.get('Bolge') and k.get('Bolge') != '-' else ""
                cevap += f"   📅 {k['Tarih']}: pH {k['pH']}{bolge_str}{not_str}\n"
            if len(kayitlar) > 10:
                cevap += f"   *Toplam {len(kayitlar)} kayıt var*\n"
            cevap += "\n"
            
            if len(cevap) > 3800:
                await message.reply(cevap)
                cevap = ""
        
        if cevap:
            await message.reply(cevap)
            
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@dp.message_handler(commands=['ph_sil'])
async def ph_sil(message: types.Message):
    global silinecek_ph_kayitlari
    param = message.get_args()
    if not param:
        await message.reply("Örnek:\n/ph_sil 1 - Son kaydı sil\n/ph_sil 1 hepsi - Tüm kayıtları sil\n/ph_sil 1 19-05-2026 - Tarihli kaydı sil")
        return
    
    parcalar = param.split()
    teneke_no = parcalar[0]
    
    try:
        with open('ph_records.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ Silinecek kayıt yok.")
            return
        
        basliklar = satirlar[0]
        veriler = satirlar[1:]
        
        teneke_kayitlari = []
        for i, row in enumerate(veriler):
            if len(row) > 1 and row[1] == teneke_no:
                teneke_kayitlari.append((i, row))
        
        if not teneke_kayitlari:
            await message.reply(f"❌ Teneke {teneke_no} için pH kaydı bulunamadı.")
            return
        
        if len(parcalar) > 1 and parcalar[1].lower() == 'hepsi':
            silinecek_ph_kayitlari = teneke_kayitlari
            await message.reply(f"⚠️ **Teneke {teneke_no} için TÜM pH kayıtları** silinecek ({len(teneke_kayitlari)} kayıt).\n\nBu işlem GERİ DÖNÜŞÜMSÜZDÜR!\n\n30 saniye içinde `/ph_evet` yazın.")
            await asyncio.sleep(30)
            if silinecek_ph_kayitlari == teneke_kayitlari:
                silinecek_ph_kayitlari = None
                await message.reply("⏰ Silme iptal edildi.")
            return
        
        if len(parcalar) > 1:
            tarih = parcalar[1]
            bulunan = None
            for i, row in teneke_kayitlari:
                if len(row) > 0 and row[0] == tarih:
                    bulunan = (i, row)
                    break
            
            if not bulunan:
                await message.reply(f"❌ Teneke {teneke_no} için {tarih} tarihinde kayıt bulunamadı.")
                return
            
            silinen = veriler.pop(bulunan[0])
            with open('ph_records.csv', 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(basliklar)
                writer.writerows(veriler)
            
            await message.reply(f"✅ pH kaydı silindi:\n📅 {silinen[0]} - Teneke {silinen[1]} - pH {silinen[3]}")
            return
        
        son_kayit = teneke_kayitlari[-1]
        veriler.pop(son_kayit[0])
        
        with open('ph_records.csv', 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(basliklar)
            writer.writerows(veriler)
        
        await message.reply(f"✅ Son pH kaydı silindi:\n📅 {son_kayit[1][0]} - Teneke {son_kayit[1][1]} - pH {son_kayit[1][3]}")
        
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@dp.message_handler(commands=['ph_evet'])
async def ph_evet(message: types.Message):
    global silinecek_ph_kayitlari
    if not silinecek_ph_kayitlari:
        await message.reply("❌ Silinecek kayıt yok. Önce /ph_sil komutunu kullanın.")
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
        
        await message.reply(f"✅ Teneke {silinecek_ph_kayitlari[0][1][1]} için TÜM pH kayıtları silindi.")
        silinecek_ph_kayitlari = None
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")
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
            await message.reply("📜 Henüz hiç kayıt yok.")
            return
        
        veriler = satirlar[1:]
        
        if not param:
            sonlar = veriler[-10:][::-1]
            mesaj = "📜 **SON 10 İŞLEM (ID ile)**\n\n"
            for i, row in enumerate(sonlar, 1):
                kayit_id = len(veriler) - i + 1
                mesaj += f"**ID: {kayit_id}** | 📅 {row[0]} - {row[1]}\n   {row[2][:100]}\n\n"
            await message.reply(mesaj[:4000])
        
        elif param.lower() == 'hepsi':
            for i in range(0, len(veriler), 10):
                blok = veriler[i:i+10]
                mesaj = "📜 **TÜM İŞLEMLER (ID ile)**\n\n"
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
                await message.reply(f"❌ {param} tarihinde kayıt bulunamadı.\n\nDene: /gecmis 14-05-2026 veya /gecmis 2026-05-14")
                return
            
            mesaj = f"📜 **{param} TARİHİNDEKİ İŞLEMLER (ID ile)**\n\n"
            for kayit_id, row in tarih_kayitlari[:20]:
                mesaj += f"**ID: {kayit_id}** | 📅 {row[0]} - {row[1]}\n   {row[2][:100]}\n\n"
            await message.reply(mesaj[:4000])
            
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@dp.message_handler(commands=['gecmis_sil'])
async def gecmis_sil(message: types.Message):
    global silinecek_gecmis_id, silinecek_gecmis_hepsi
    param = message.get_args()
    if not param:
        await message.reply("Örnek:\n/gecmis_sil 5 - ID ile sil (ID'yi /gecmis ile görebilirsin)\n/gecmis_sil hepsi - Tüm geçmişi sil")
        return
    
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ Silinecek kayıt yok.")
            return
        
        basliklar = satirlar[0]
        veriler = satirlar[1:]
        
        if param.lower() == 'hepsi':
            silinecek_gecmis_hepsi = True
            await message.reply(f"⚠️ **TÜM geçmiş kayıtları** silinecek ({len(veriler)} kayıt).\n\nBu işlem GERİ DÖNÜŞÜMSÜZDÜR!\n\n30 saniye içinde `/gecmis_evet` yazın.")
            await asyncio.sleep(30)
            if silinecek_gecmis_hepsi:
                silinecek_gecmis_hepsi = None
                await message.reply("⏰ Silme iptal edildi.")
            return
        
        try:
            kayit_id = int(param)
            if kayit_id < 1 or kayit_id > len(veriler):
                await message.reply(f"❌ Geçersiz ID. 1 ile {len(veriler)} arasında bir sayı girin.")
                return
            
            idx = kayit_id - 1
            silinecek_gecmis_id = (idx, veriler[idx])
            await message.reply(f"⚠️ **ID: {kayit_id}** kaydı silinecek:\n\n📅 {veriler[idx][0]} - {veriler[idx][1]}\n   {veriler[idx][2][:200]}\n\nBu işlem GERİ DÖNÜŞÜMSÜZDÜR!\n\n30 saniye içinde `/gecmis_evet` yazın.")
            await asyncio.sleep(30)
            if silinecek_gecmis_id == (idx, veriler[idx]):
                silinecek_gecmis_id = None
                await message.reply("⏰ Silme iptal edildi.")
            return
        except ValueError:
            await message.reply("❌ ID sayı olmalı. Örnek: /gecmis_sil 5")
            
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

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
            await message.reply("✅ Tüm geçmiş kayıtları silindi.")
            silinecek_gecmis_hepsi = None
            return
        
        if silinecek_gecmis_id:
            idx, silinen = silinecek_gecmis_id
            veriler.pop(idx)
            with open('history.csv', 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(basliklar)
                writer.writerows(veriler)
            await message.reply(f"✅ Kayıt silindi:\n📅 {silinen[0]} - {silinen[1]}\n   {silinen[2][:200]}")
            silinecek_gecmis_id = None
            return
        
        await message.reply("❌ Silinecek kayıt yok. Önce /gecmis_sil komutunu kullanın.")
        
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")
        silinecek_gecmis_id = None
        silinecek_gecmis_hepsi = None

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
        
        istatistik = f"📊 **GENEL İSTATİSTİK**\n\n"
        istatistik += f"📝 Toplam işlem: {toplam_islem}\n\n"
        istatistik += f"🔧 En çok kullanılan malzemeler:\n"
        for malzeme, sayi in en_cok:
            istatistik += f"   • {malzeme}: {sayi} kez\n"
        
        await message.reply(istatistik)
    except Exception as e:
        await message.reply(f"❌ İstatistik alınamadı: {e}")

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
            await message.reply(f"📅 **{bugun} GÜNLÜK RAPOR**\n\nBugün hiç işlem yapılmamış.")
            return
        
        rapor = f"📅 **{bugun} GÜNLÜK RAPOR**\n\n"
        rapor += f"📝 Toplam işlem: {len(gunun_islemleri)}\n\n"
        for row in gunun_islemleri[:15]:
            rapor += f"• {row[1]}: {row[2][:50]}\n"
        await message.reply(rapor)
    except Exception as e:
        await message.reply(f"❌ Rapor alınamadı: {e}")

# ==================== AYLIK RAPOR ====================
@dp.message_handler(commands=['rapor_aylik'])
async def rapor_aylik(message: types.Message):
    ay_param = message.get_args()
    if not ay_param:
        await message.reply("Örnek: /rapor_aylik 05-2026")
        return
    
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ Henüz hiç kayıt yok.")
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
            await message.reply(f"❌ {ay_param} ayında işlem bulunamadı.")
            return
        
        toplam_islem = len(ay_kayitlari)
        islem_turleri = {}
        malzeme_kullanimlari = {}
        toplam_miktar = 0
        miktar_sayac = 0
        
        for row in ay_kayitlari:
            tur = row[1] if len(row) > 1 else "Bilinmiyor"
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
        
        en_cok_malzeme = max(malzeme_kullanimlari.items(), key=lambda x: x[1])[0] if malzeme_kullanimlari else "Yok"
        ortalama_miktar = toplam_miktar / miktar_sayac if miktar_sayac > 0 else 0
        
        ay_adi = ay_param
        rapor = f"📊 **{ay_adi} AYLIK RAPORU**\n\n"
        rapor += f"📝 Toplam işlem: {toplam_islem}\n"
        rapor += f"🔧 En çok kullanılan malzeme: {en_cok_malzeme}\n"
        rapor += f"📦 Ortalama kullanım: {ortalama_miktar:.1f} gr\n\n"
        rapor += f"📋 İşlem türleri:\n"
        for tur, sayi in sorted(islem_turleri.items(), key=lambda x: x[1], reverse=True):
            rapor += f"   • {tur}: {sayi} kez\n"
        
        await message.reply(rapor)
        
    except Exception as e:
        await message.reply(f"❌ Rapor alınamadı: {e}")

# ==================== GRAFİK ====================
@dp.message_handler(commands=['grafik'])
async def grafik(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /grafik NPK\n\nBir malzemenin stok geçmişini basit grafikle gösterir.")
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
            await message.reply(f"❌ '{param}' için geçmiş kayıt bulunamadı.")
            return
        
        sonlar = kayitlar[-10:][::-1]
        grafik = f"📊 **'{param.upper()}' STOK GRAFİĞİ (Son 10 kullanım)**\n\n"
        for row in sonlar:
            grafik += f"📅 {row[0]}: {row[2]}\n"
        
        await message.reply(grafik)
    except Exception as e:
        await message.reply(f"❌ Grafik alınamadı: {e}")

# ==================== HATIRLATMA ====================
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
            await message.reply("Henüz hatırlatma yok. /hatirlat ile ekleyebilirsin.")
            return
        
        bekleyenler = []
        for i, row in enumerate(satirlar[1:], 1):
            if len(row) >= 4 and row[3] == "bekliyor":
                bekleyenler.append((i, row))
        
        if not bekleyenler:
            await message.reply("✅ Bekleyen hatırlatma yok.")
            return
        
        mesaj = "📅 **BEKLEYEN HATIRLATMALAR (ID ile)**\n\n"
        for i, row in bekleyenler:
            mesaj += f"**ID: {i}** | {row[0]} {row[1]} - {row[2]}\n"
        await message.reply(mesaj[:4000])
    except:
        await message.reply("Dosya okuma hatası. reminders.csv dosyası var mı?")

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
            await message.reply("❌ Geri alınacak kayıt yok.")
            return
        
        basliklar = satirlar[0]
        veriler = satirlar[1:]
        
        if not veriler:
            await message.reply("❌ Geri alınacak kayıt yok.")
            return
        
        if param and param.isdigit():
            kayit_id = int(param)
            if kayit_id < 1 or kayit_id > len(veriler):
                await message.reply(f"❌ Geçersiz ID. 1 ile {len(veriler)} arasında bir sayı girin.\n\nID'leri /gecmis ile görebilirsin.")
                return
            
            idx = kayit_id - 1
            silinecek_kayit_id = (idx, veriler[idx], kayit_id)
            
            await message.reply(f"⚠️ **DİKKAT!**\n\n"
                               f"ID: {kayit_id} numaralı işlem silinecek:\n"
                               f"📅 {veriler[idx][0]} - {veriler[idx][1]}\n"
                               f"📝 {veriler[idx][2][:200]}\n\n"
                               f"**Bu işlem GERİ DÖNÜŞÜMSÜZDÜR!**\n\n"
                               f"30 saniye içinde `/kaydet_evet` yazın.")
            
            await asyncio.sleep(30)
            if silinecek_kayit_id == (idx, veriler[idx], kayit_id):
                silinecek_kayit_id = None
                await message.reply("⏰ Silme iptal edildi.")
            return
        
        elif param and param.lower() == 'hepsi':
            silinecek_kayit_hepsi = veriler.copy()
            await message.reply(f"⚠️ **DİKKAT!**\n\n"
                               f"TÜM geçmiş kayıtları silinecek ({len(veriler)} kayıt).\n\n"
                               f"**Bu işlem GERİ DÖNÜŞÜMSÜZDÜR!**\n\n"
                               f"30 saniye içinde `/kaydet_evet` yazın.")
            await asyncio.sleep(30)
            if silinecek_kayit_hepsi:
                silinecek_kayit_hepsi = None
                await message.reply("⏰ Silme iptal edildi.")
            return
        
        son_islem = veriler[-1]
        kayit_id = len(veriler)
        silinecek_kayit_id = (len(veriler)-1, son_islem, kayit_id)
        
        await message.reply(f"⚠️ **DİKKAT!**\n\n"
                           f"SON işlem silinecek:\n"
                           f"📅 {son_islem[0]} - {son_islem[1]}\n"
                           f"📝 {son_islem[2][:200]}\n\n"
                           f"**Bu işlem GERİ DÖNÜŞÜMSÜZDÜR!**\n\n"
                           f"30 saniye içinde `/kaydet_evet` yazın.")
        
        await asyncio.sleep(30)
        if silinecek_kayit_id == (len(veriler)-1, son_islem, kayit_id):
            silinecek_kayit_id = None
            await message.reply("⏰ Silme iptal edildi.")
        
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@dp.message_handler(commands=['kaydet_evet'])
async def kaydet_evet(message: types.Message):
    global silinecek_kayit_id, silinecek_kayit_hepsi, son_kayit_geri_al
    
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ Silinecek kayıt yok.")
            silinecek_kayit_id = None
            silinecek_kayit_hepsi = None
            return
        
        basliklar = satirlar[0]
        veriler = satirlar[1:]
        
        if silinecek_kayit_hepsi:
            with open('history.csv', 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(basliklar)
            await message.reply(f"✅ Tüm geçmiş kayıtları silindi.")
            son_kayit_geri_al = None
            silinecek_kayit_hepsi = None
            return
        
        if silinecek_kayit_id:
            idx, silinen_islem, kayit_id = silinecek_kayit_id
            if idx < len(veriler):
                veriler.pop(idx)
                
                if son_kayit_geri_al and son_kayit_geri_al.get('malzeme') and silinen_islem[1] == "Kullanım":
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
                
                await message.reply(f"✅ ID {kayit_id} numaralı işlem silindi:\n📅 {silinen_islem[0]} - {silinen_islem[1]}\n📝 {silinen_islem[2][:200]}")
                silinecek_kayit_id = None
                return
        
        await message.reply("❌ Silinecek kayıt bulunamadı.")
        silinecek_kayit_id = None
        
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")
        silinecek_kayit_id = None
        silinecek_kayit_hepsi = None

# ==================== STOK UYARISI ====================
@dp.message_handler(commands=['stok_uyari'])
async def stok_uyari_ekle(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /stok_uyari \"NPK\" 100 gr")
        return
    
    parcalar = param.split()
    if len(parcalar) < 3:
        await message.reply("Örnek: /stok_uyari \"NPK\" 100 gr")
        return
    
    try:
        esik = float(parcalar[-2])
        birim = parcalar[-1].lower()
        malzeme_aranan = " ".join(parcalar[:-2]).strip('"')
    except:
        await message.reply("Örnek: /stok_uyari \"NPK\" 100 gr")
        return
    
    stoklar = stok_oku()
    eslesenler = malzeme_bul(malzeme_aranan, stoklar)
    
    if not eslesenler:
        await message.reply(f"❌ '{malzeme_aranan}' envanterde bulunamadı.")
        return
    
    if len(eslesenler) > 1:
        liste = "\n".join([f"• {item.get('Malzeme / Alet')}" for item in eslesenler[:5]])
        await message.reply(f"⚠️ '{malzeme_aranan}' için birden fazla malzeme bulundu:\n\n{liste}\n\nLütfen tam adını yazın.")
        return
    
    malzeme_adi = eslesenler[0].get('Malzeme / Alet')
    stok_uyarilari[malzeme_adi] = {'esik': esik, 'birim': birim}
    await message.reply(f"✅ Stok uyarısı eklendi:\n📦 {malzeme_adi}\n⚠️ {esik} {birim} altında uyarı verilecek.")

@dp.message_handler(commands=['stok_uyari_sil'])
async def stok_uyari_sil(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /stok_uyari_sil NPK")
        return
    
    silinecekler = []
    for malzeme in stok_uyarilari.keys():
        if param.lower() in malzeme.lower():
            silinecekler.append(malzeme)
    
    if not silinecekler:
        await message.reply(f"❌ '{param}' için stok uyarısı bulunamadı.")
        return
    
    if len(silinecekler) > 1:
        liste = "\n".join([f"• {m}" for m in silinecekler])
        await message.reply(f"⚠️ '{param}' için birden fazla uyarı bulundu:\n\n{liste}\n\nLütfen tam adını yazın.")
        return
    
    del stok_uyarilari[silinecekler[0]]
    await message.reply(f"✅ {silinecekler[0]} için stok uyarısı kaldırıldı.")

@dp.message_handler(commands=['stok_uyari_liste'])
async def stok_uyari_liste(message: types.Message):
    if not stok_uyarilari:
        await message.reply("📋 Aktif stok uyarısı yok.\n\n/stok_uyari \"NPK\" 100 gr ile ekleyebilirsin.")
        return
    
    mesaj = "📋 **AKTİF STOK UYARILARI**\n\n"
    stoklar = stok_oku()
    for malzeme, veri in stok_uyarilari.items():
        kalan = "?"
        for item in stoklar:
            if item.get('Malzeme / Alet') == malzeme:
                kalan = f"{item.get('Kalan Miktar')} {item.get('Birim')}"
                break
        mesaj += f"📦 {malzeme}\n   ⚠️ Eşik: {veri['esik']} {veri['birim']} | 📊 Güncel: {kalan}\n\n"
    await message.reply(mesaj)

@dp.message_handler(commands=['stok_uyari_temizle'])
async def stok_uyari_temizle(message: types.Message):
    global stok_uyari_temizlik_onay
    if not stok_uyarilari:
        await message.reply("❌ Silinecek stok uyarısı yok.")
        return
    
    stok_uyari_temizlik_onay = True
    await message.reply(f"⚠️ **DİKKAT!**\n\n"
                       f"TÜM stok uyarıları silinecek ({len(stok_uyarilari)} uyarı).\n\n"
                       f"**Bu işlem GERİ DÖNÜŞÜMSÜZDÜR!**\n\n"
                       f"30 saniye içinde `/stok_uyari_evet` yazın.")
    
    await asyncio.sleep(30)
    if stok_uyari_temizlik_onay:
        stok_uyari_temizlik_onay = False
        await message.reply("⏰ Silme iptal edildi.")

@dp.message_handler(commands=['stok_uyari_evet'])
async def stok_uyari_evet(message: types.Message):
    global stok_uyari_temizlik_onay, stok_uyarilari
    if not stok_uyari_temizlik_onay:
        await message.reply("❌ Silinecek uyarı yok veya süresi doldu. Önce /stok_uyari_temizle komutunu kullanın.")
        return
    
    stok_uyarilari.clear()
    stok_uyari_temizlik_onay = False
    await message.reply("✅ Tüm stok uyarıları silindi.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
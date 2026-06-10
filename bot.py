import os
import logging
import csv
import re
import asyncio
from datetime import datetime
from openai import OpenAI
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")

# Silinecek malzeme için geçici hafıza
silinecek_malzeme = None

# Agnes AI istemcisi
client = OpenAI(
    base_url="https://apihub.agnes-ai.com/v1",
    api_key=AGNES_API_KEY
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ==================== STOK FONKSİYONLARI ====================
def stok_oku():
    """inventory.csv dosyasını okur"""
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
    """inventory.csv dosyasını kaydeder"""
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
    """Belirtilen malzemeden stok düşer"""
    stoklar = stok_oku()
    
    for item in stoklar:
        if malzeme_adi.lower() in item['Malzeme / Alet'].lower():
            try:
                kalan = float(str(item['Kalan Miktar']).replace(',', '.'))
                miktar_float = float(str(miktar).replace(',', '.'))
                
                if kalan >= miktar_float:
                    yeni_kalan = kalan - miktar_float
                    item['Kalan Miktar'] = str(yeni_kalan).replace('.', ',')
                    
                    kullanilan = float(str(item.get('Kullanılan', '0')).replace(',', '.'))
                    item['Kullanılan'] = str(kullanilan + miktar_float).replace('.', ',')
                    
                    stok_kaydet(stoklar)
                    return True, f"{yeni_kalan:.1f} {birim}"
                else:
                    return False, f"Yetersiz stok! Kalan: {kalan:.1f} {birim}"
            except:
                return False, "Miktar okunamadı"
    
    return False, f"'{malzeme_adi}' envanterde bulunamadı"

def islemi_kaydet(islem_metni, malzemeler):
    """history.csv'ye işlem kaydeder"""
    try:
        tarih = datetime.now().strftime("%Y-%m-%d")
        malzeme_str = ", ".join([f"{m['miktar']} {m['birim']} {m['ad']}" for m in malzemeler])
        
        with open('history.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih, islem_metni, malzeme_str, "-", "Bot tarafından eklendi"])
        return True
    except Exception as e:
        print(f"History kayıt hatası: {e}")
        return False

def parse_metin(text):
    """'10 lt su + 5 gr NPK + 8 gr Yosun' gibi metni ayrıştırır"""
    pattern = r'(\d+(?:\.\d+)?)\s*([a-zA-Zğüşıöç]+)\s+(.+?)(?=\s*\+|\s*$)'
    malzemeler = []
    matches = re.findall(pattern, text, re.IGNORECASE)
    
    for miktar, birim, ad in matches:
        malzemeler.append({
            'miktar': miktar,
            'birim': birim,
            'ad': ad.strip()
        })
    return malzemeler

# ==================== AGNES AI ====================
def ask_agnes(question):
    try:
        response = client.chat.completions.create(
            model="agnes-2.0-flash",
            messages=[{"role": "user", "content": question}],
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Agnes hatası: {str(e)[:100]}"

# ==================== KOMUTLAR ====================
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan** hazır!\n\n📌 **Komutlar:**\n/sor [soru] - Agnes AI'ya sor\n/stok [malzeme] - Stok sorgula\n/kaydet [işlem] - Stok düş ve kaydet\n/ph [teneke_no] - pH sorgula\n/gecmis - Son işlemleri göster\n/sil [malzeme] - Malzeme sil\n/test - Bot testi")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

@dp.message_handler(commands=['sor'])
async def sor(message: types.Message):
    soru = message.get_args()
    if not soru:
        await message.reply("Bir soru yaz: /sor [soru]")
        return
    
    msg = await message.reply("🤔 Agnes düşünüyor...")
    cevap = ask_agnes(soru)
    
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=msg.message_id,
        text=f"🤖 **Agnes AI:**\n\n{cevap}"
    )

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
        if len(stoklar) > 20:
            mesaj += f"\n*Toplam {len(stoklar)} malzeme var. Detay için /stok [malzeme]"
        await message.reply(mesaj)

@dp.message_handler(commands=['kaydet'])
async def kaydet(message: types.Message):
    islem = message.get_args()
    if not islem:
        await message.reply("Örnek: /kaydet 10 lt su + 5 gr NPK 20 20 20 + 8 gr Yosun")
        return
    
    msg = await message.reply("📝 İşlem işleniyor...")
    malzemeler = parse_metin(islem)
    
    if not malzemeler:
        await bot.edit_message_text("⚠️ Malzeme bulunamadı. Örnek: 5 gr NPK", chat_id=message.chat.id, message_id=msg.message_id)
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
    
    # History'ye kaydet
    islemi_kaydet("Sulama/Gübreleme", malzemeler)
    
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=msg.message_id,
        text=f"✅ **İşlem kaydedildi!**\n\n📝 {islem}\n\n" + "\n".join(sonuclar)
    )

@dp.message_handler(commands=['ph'])
async def ph_sorgula(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Bir teneke numarası yaz: /ph 1")
        return
    
    try:
        with open('ph_records.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=',')
            teneke_kayitlari = []
            
            for row in reader:
                if row.get('Teneke_No', '') == param:
                    teneke_kayitlari.append(row)
            
            if teneke_kayitlari:
                # En son kaydı bul
                en_son = max(teneke_kayitlari, key=lambda x: x.get('Tarih', ''))
                await message.reply(
                    f"📊 **Teneke {param} - Son pH Ölçümü**\n\n"
                    f"📅 Tarih: {en_son['Tarih']}\n"
                    f"🔬 pH: {en_son['pH']}\n"
                    f"📍 Bölge: {en_son.get('Bolge', '-')}\n"
                    f"📝 Not: {en_son.get('Not', '-')}"
                )
            else:
                await message.reply(f"❌ Teneke {param} için pH kaydı bulunamadı.")
    except Exception as e:
        await message.reply(f"Dosya okuma hatası: {e}")

@dp.message_handler(commands=['gecmis'])
async def gecmis(message: types.Message):
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("Henüz hiç kayıt yok.")
            return
        
        # Son 10 işlemi al (başlık satırını atla)
        son_kayitlar = satirlar[-10:][::-1]  # Ters çevir, en yeni önce gelsin
        
        mesaj = "📜 **SON 10 İŞLEM**\n\n"
        for row in son_kayitlar:
            if len(row) >= 3:
                mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:50]}\n\n"
        
        await message.reply(mesaj[:4000])
    except Exception as e:
        await message.reply(f"Dosya okuma hatası: {e}")

# ==================== SİLME KOMUTLARI ====================
@dp.message_handler(commands=['sil'])
async def sil_stok(message: types.Message):
    global silinecek_malzeme
    
    param = message.get_args()
    if not param:
        await message.reply("Silmek istediğin malzemenin adını yaz: /sil NPK")
        return
    
    stoklar = stok_oku()
    bulunan = None
    
    for item in stoklar:
        if param.lower() in item['Malzeme / Alet'].lower():
            bulunan = item
            break
    
    if not bulunan:
        await message.reply(f"❌ '{param}' envanterde bulunamadı.")
        return
    
    # Silinecek malzemeyi hafızaya al
    silinecek_malzeme = bulunan
    
    # Onay iste
    await message.reply(
        f"⚠️ **DİKKAT!**\n\n"
        f"📦 Malzeme: **{bulunan['Malzeme / Alet']}**\n"
        f"📊 Kalan Miktar: {bulunan['Kalan Miktar']} {bulunan['Birim']}\n\n"
        f"**Bu işlem GERİ DÖNÜŞÜMSÜZDÜR!**\n\n"
        f"Emin misin? 30 saniye içinde `/evet` yaz."
    )
    
    # 30 saniye sonra temizle
    await asyncio.sleep(30)
    if silinecek_malzeme == bulunan:
        silinecek_malzeme = None
        await message.reply("⏰ Silme onay süresi doldu. İşlem iptal edildi.")

@dp.message_handler(commands=['evet'])
async def evet_sil(message: types.Message):
    global silinecek_malzeme
    
    if not silinecek_malzeme:
        await message.reply("❌ Silme onayı bulunamadı veya süresi doldu. Lütfen /sil komutunu tekrar dene.")
        return
    
    stoklar = stok_oku()
    malzeme_adi = silinecek_malzeme['Malzeme / Alet']
    
    # Malzemeyi listeden çıkar
    yeni_stoklar = [item for item in stoklar if item['Malzeme / Alet'] != malzeme_adi]
    
    if len(yeni_stoklar) == len(stoklar):
        await message.reply(f"❌ '{malzeme_adi}' bulunamadı.")
        silinecek_malzeme = None
        return
    
    # Yeni listeyi kaydet
    if stok_kaydet(yeni_stoklar):
        await message.reply(f"✅ **'{malzeme_adi}'** envanterden silindi.")
        
        # History'ye silme işlemini kaydet
        try:
            with open('history.csv', 'a', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([datetime.now().strftime("%Y-%m-%d"), "MALZEME SİLİNDİ", malzeme_adi, "-", "Bot ile silindi"])
        except:
            pass
    else:
        await message.reply(f"❌ Silme işlemi sırasında hata oluştu.")
    
    silinecek_malzeme = None

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

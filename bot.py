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

# ==================== HATIRLATICI FONKSİYONLARI ====================
def hatirlatma_ekle(tarih, islem, detay):
    try:
        with open('reminders.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([tarih, islem, detay, "bekliyor"])
        return True
    except Exception as e:
        print(f"Hatırlatma ekleme hatası: {e}")
        return False

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
    await message.answer("🌿 **Yasemin Asistan** hazır!\n\n📌 **Komutlar:**\n"
                         "/sor [soru] - Agnes AI'ya sor\n"
                         "/stok [malzeme] - Stok sorgula\n"
                         "/kaydet [işlem] - Stok düş ve kaydet\n"
                         "/geri_al - Son işlemi geri al\n"
                         "/ekle Ad;Miktar;Birim;Görev - Yeni malzeme ekle\n"
                         "/ph [teneke] - pH sorgula (hepsi için /ph 1 hepsi)\n"
                         "/gecmis [ay/hepsi] - Geçmiş işlemler\n"
                         "/sil [malzeme] - Malzeme sil\n"
                         "/hatirlat [tarih] [işlem] - Hatırlatma ekle\n"
                         "/hatirlatmalar - Bekleyen hatırlatmalar\n"
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

@dp.message_handler(commands=['geri_al'])
async def geri_al(message: types.Message):
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("❌ Geri alınacak işlem yok.")
            return
        
        son_islem = satirlar[-1]
        onceki_islemler = satirlar[:-1]
        
        with open('history.csv', 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(onceki_islemler)
        
        await message.reply(f"✅ Son işlem geri alındı:\n\n📅 {son_islem[0]} - {son_islem[1]}\n📝 {son_islem[2]}")
        
    except Exception as e:
        await message.reply(f"Hata: {e}")

@dp.message_handler(commands=['ekle'])
async def ekle_envanter(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ekle Malzeme Adı;1000;gr;Görevi\n\nNot: Noktalı virgül (;) ile ayırın.")
        return
    
    parcalar = param.split(';')
    if len(parcalar) < 3:
        await message.reply("Format: Ad;Miktar;Birim;Görevi\nÖrnek: Yeni Gübre;500;gr;Deneme")
        return
    
    malzeme_adi = parcalar[0].strip()
    miktar = parcalar[1].strip()
    birim = parcalar[2].strip()
    gorev = parcalar[3].strip() if len(parcalar) > 3 else "-"
    
    stoklar = stok_oku()
    
    for item in stoklar:
        if item['Malzeme / Alet'].lower() == malzeme_adi.lower():
            await message.reply(f"❌ '{malzeme_adi}' zaten var. Güncelleme için /guncelle kullan.")
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
        await message.reply(f"✅ **'{malzeme_adi}'** envantere eklendi!\n\n📦 Miktar: {miktar} {birim}\n📝 Görevi: {gorev}")
        
        with open('history.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([datetime.now().strftime("%Y-%m-%d"), "ENVANTERE EKLENDİ", f"{malzeme_adi}: {miktar} {birim}", "-", "Bot ile eklendi"])
    else:
        await message.reply("❌ Ekleme sırasında hata oluştu.")

@dp.message_handler(commands=['ph'])
async def ph_sorgula(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Bir teneke numarası yaz: /ph 1\nTüm kayıtlar için: /ph 1 hepsi")
        return
    
    parcalar = param.split()
    teneke_no = parcalar[0]
    tumu = len(parcalar) > 1 and parcalar[1].lower() == 'hepsi'
    
    try:
        with open('ph_records.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=',')
            teneke_kayitlari = []
            
            for row in reader:
                if row.get('Teneke_No', '') == teneke_no:
                    teneke_kayitlari.append(row)
            
            if not teneke_kayitlari:
                await message.reply(f"❌ Teneke {teneke_no} için pH kaydı bulunamadı.")
                return
            
            if tumu:
                mesaj = f"📊 **Teneke {teneke_no} - TÜM pH ÖLÇÜMLERİ**\n\n"
                for kayit in sorted(teneke_kayitlari, key=lambda x: x.get('Tarih', ''), reverse=True):
                    mesaj += f"📅 {kayit['Tarih']}: pH {kayit['pH']} ({kayit.get('Bolge', '-')})\n"
                    if len(mesaj) > 3800:
                        mesaj += "\n*Devamı için /ph 1 devam*"
                        break
                await message.reply(mesaj)
            else:
                en_son = max(teneke_kayitlari, key=lambda x: x.get('Tarih', ''))
                await message.reply(
                    f"📊 **Teneke {teneke_no} - Son pH Ölçümü**\n\n"
                    f"📅 Tarih: {en_son['Tarih']}\n"
                    f"🔬 pH: {en_son['pH']}\n"
                    f"📍 Bölge: {en_son.get('Bolge', '-')}\n"
                    f"📝 Not: {en_son.get('Not', '-')}"
                )
    except Exception as e:
        await message.reply(f"Dosya okuma hatası: {e}")

@dp.message_handler(commands=['gecmis'])
async def gecmis(message: types.Message):
    param = message.get_args()
    
    try:
        with open('history.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("Henüz hiç kayıt yok.")
            return
        
        veriler = satirlar[1:]
        
        if not param:
            son_kayitlar = veriler[-10:][::-1]
            mesaj = "📜 **SON 10 İŞLEM**\n\n"
            for row in son_kayitlar:
                if len(row) >= 3:
                    mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:50]}\n\n"
            await message.reply(mesaj[:4000])
            return
        
        if param.lower() == 'hepsi':
            mesaj = "📜 **TÜM İŞLEMLER**\n\n"
            for row in veriler[::-1]:
                if len(row) >= 3:
                    mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:50]}\n\n"
                    if len(mesaj) > 3800:
                        mesaj += "\n*Çok fazla kayıt var, devamı için /gecmis devam*"
                        break
            await message.reply(mesaj[:4000])
            return
        
        if re.match(r'\d{4}-\d{2}', param):
            ay_kayitlari = [row for row in veriler if row[0].startswith(param)]
            if not ay_kayitlari:
                await message.reply(f"❌ {param} ayında kayıt bulunamadı.")
                return
            
            mesaj = f"📜 **{param} AYINDAKİ İŞLEMLER**\n\n"
            for row in ay_kayitlari[::-1]:
                if len(row) >= 3:
                    mesaj += f"📅 {row[0]} - {row[1]}\n   {row[2][:50]}\n\n"
            await message.reply(mesaj[:4000])
            return
        
        await message.reply("Geçersiz komut. Kullanım:\n/gecmis - Son 10 işlem\n/gecmis hepsi - Tüm işlemler\n/gecmis 2026-05 - Belirli ay")
        
    except Exception as e:
        await message.reply(f"Dosya okuma hatası: {e}")

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
    
    silinecek_malzeme = bulunan
    
    await message.reply(
        f"⚠️ **DİKKAT!**\n\n"
        f"📦 Malzeme: **{bulunan['Malzeme / Alet']}**\n"
        f"📊 Kalan Miktar: {bulunan['Kalan Miktar']} {bulunan['Birim']}\n\n"
        f"**Bu işlem GERİ DÖNÜŞÜMSÜZDÜR!**\n\n"
        f"Emin misin? 30 saniye içinde `/evet` yaz."
    )
    
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
    
    yeni_stoklar = [item for item in stoklar if item['Malzeme / Alet'] != malzeme_adi]
    
    if len(yeni_stoklar) == len(stoklar):
        await message.reply(f"❌ '{malzeme_adi}' bulunamadı.")
        silinecek_malzeme = None
        return
    
    if stok_kaydet(yeni_stoklar):
        await message.reply(f"✅ **'{malzeme_adi}'** envanterden silindi.")
        
        with open('history.csv', 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([datetime.now().strftime("%Y-%m-%d"), "MALZEME SİLİNDİ", malzeme_adi, "-", "Bot ile silindi"])
    else:
        await message.reply(f"❌ Silme işlemi sırasında hata oluştu.")
    
    silinecek_malzeme = None

@dp.message_handler(commands=['hatirlat'])
async def hatirlat(message: types.Message):
    parametre = message.get_args()
    if not parametre:
        await message.reply("Örnek: /hatirlat 2026-07-30 10 lt su + 5 gr NPK 20 20 20")
        return
    
    parcalar = parametre.split(maxsplit=1)
    if len(parcalar) < 2:
        await message.reply("Lütfen tarih ve işlem yaz: /hatirlat 2026-07-30 Sulama yap")
        return
    
    tarih = parcalar[0]
    islem = parcalar[1]
    
    try:
        datetime.strptime(tarih, "%Y-%m-%d")
    except:
        await message.reply("Tarih formatı yanlış. Doğru: YYYY-MM-DD (örnek: 2026-07-30)")
        return
    
    if hatirlatma_ekle(tarih, islem, ""):
        await message.reply(f"✅ Hatırlatma eklendi!\n\n📅 Tarih: {tarih}\n📝 İşlem: {islem}")
    else:
        await message.reply("❌ Hatırlatma eklenirken hata oluştu.")

@dp.message_handler(commands=['hatirlatmalar'])
async def list_hatirlatmalar(message: types.Message):
    try:
        with open('reminders.csv', 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            satirlar = list(reader)
        
        if len(satirlar) <= 1:
            await message.reply("Henüz hiç hatırlatma yok. /hatirlat ile ekleyebilirsin.")
            return
        
        bekleyenler = [row for row in satirlar if len(row) >= 4 and row[3] == "bekliyor"]
        
        if not bekleyenler:
            await message.reply("✅ Bekleyen hatırlatma yok.")
            return
        
        mesaj = "📅 **BEKLEYEN HATIRLATMALAR**\n\n"
        for row in bekleyenler[:15]:
            mesaj += f"• {row[0]}: {row[1]}\n"
        
        await message.reply(mesaj[:4000])
    except Exception as e:
        await message.reply(f"Dosya okuma hatası: {e}")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

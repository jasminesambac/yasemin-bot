import os
import logging
import csv
from datetime import datetime
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

son_kayit_geri_al = None
silinecek_malzeme = None

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

def tarih_format():
    return datetime.now().strftime("%d-%m-%Y")

def stok_oku():
    stok_listesi = []
    try:
        with open('inventory.csv', 'r', encoding='utf-8-sig') as f:
            # Dosyanın tamamını oku
            icerik = f.read()
            print(f"DEBUG - Dosya içeriği uzunluğu: {len(icerik)} karakter")
            
            # Satırları ayır
            satirlar = icerik.strip().split('\n')
            if not satirlar:
                return []
            
            # Başlıkları al
            basliklar = satirlar[0].split(';')
            print(f"DEBUG - Başlıklar: {basliklar}")
            
            # Her satır için
            for satir in satirlar[1:]:
                if satir.strip():
                    degerler = satir.split(';')
                    # Eksik sütunları boşlukla doldur
                    while len(degerler) < len(basliklar):
                        degerler.append('')
                    satir_sozluk = {}
                    for i, baslik in enumerate(basliklar):
                        satir_sozluk[baslik] = degerler[i].strip()
                    stok_listesi.append(satir_sozluk)
            
            print(f"DEBUG - Toplam {len(stok_listesi)} malzeme okundu")
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
        print(f"DEBUG - {len(stok_listesi)} malzeme kaydedildi")
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

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan** hazır!\n\n"
                         "/stok - Envanter listesi\n"
                         "/stok lena - Malzeme sorgula\n"
                         "/kaydet 5 gr NPK - Stoktan düş\n"
                         "/kaydet_geri_al - Son işlemi geri al\n"
                         "/ekle NPK 20-20-20;1000;gr;Gübre - Yeni malzeme ekle\n"
                         "/test - Bot testi")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

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
        malzeme_aranan = " ".join(parcalar[2:])
    except:
        await message.reply("Hatalı format. Örnek: /kaydet 5 gr NPK")
        return
    
    stoklar = stok_oku()
    eslesenler = malzeme_bul(malzeme_aranan, stoklar)
    
    if not eslesenler:
        await message.reply(f"❌ '{malzeme_aranan}' ile eşleşen malzeme bulunamadı.")
        return
    
    if len(eslesenler) > 1:
        liste = "\n".join([f"• {item.get('Malzeme / Alet')}" for item in eslesenler[:5]])
        await message.reply(f"⚠️ '{malzeme_aranan}' için birden fazla malzeme bulundu:\n\n{liste}\n\nLütfen tam adını yazın.")
        return
    
    item = eslesenler[0]
    malzeme_adi = item.get('Malzeme / Alet')
    
    try:
        kalan_str = str(item['Kalan Miktar']).replace(',', '.').strip()
        if kalan_str == 'Stok bol':
            # Sonsuz stok için kontrol yapma
            yeni_kalan = 'Stok bol'
            eski_kalan = 'Stok bol'
            item['Kalan Miktar'] = yeni_kalan
            stok_kaydet(stoklar)
            
            son_kayit_geri_al = {
                'malzeme': malzeme_adi,
                'eski_kalan': eski_kalan,
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
            
            await message.reply(f"✅ {miktar:.1f} {birim} {malzeme_adi} kullanıldı.\n📊 Kalan: {yeni_kalan:.1f} {birim}")
            return
        else:
            await message.reply(f"❌ Yetersiz stok! Kalan: {kalan:.1f} {birim}")
            return
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")
        return

@dp.message_handler(commands=['kaydet_geri_al'])
async def kaydet_geri_al(message: types.Message):
    global son_kayit_geri_al
    if not son_kayit_geri_al:
        await message.reply("❌ Geri alınacak kayıt yok")
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
            
            miktar = son_kayit_geri_al['kullanilan']
            birim = son_kayit_geri_al['birim']
            malzeme = son_kayit_geri_al['malzeme']
            son_kayit_geri_al = None
            await message.reply(f"✅ Geri alındı: {malzeme} +{miktar:.1f} {birim}")
            return
    await message.reply("❌ Malzeme bulunamadı")

@dp.message_handler(commands=['ekle'])
async def ekle_envanter(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /ekle NPK 20-20-20;1000;gr;Dengeli gübre\n\n"
                           "Format: Ad;Miktar;Birim;Görevi")
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
    
    # Aynı malzeme var mı kontrol et
    for item in stoklar:
        if item.get('Malzeme / Alet', '').lower() == malzeme_adi.lower():
            await message.reply(f"❌ '{malzeme_adi}' zaten envanterde var.")
            return
    
    # Kategori belirleme
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
        
        # Doğrulama
        kontrol = stok_oku()
        for item in kontrol:
            if item.get('Malzeme / Alet') == malzeme_adi:
                await message.reply(f"✅ Doğrulama: {malzeme_adi} envanterde. Miktar: {item.get('Kalan Miktar')} {item.get('Birim')}")
                return
    else:
        await message.reply("❌ Ekleme sırasında hata oluştu.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
import os
import logging
import csv
from datetime import datetime
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Geçici hafızalar
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

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan** hazır!\n\n"
                         "/stok - Envanter listesi\n"
                         "/stok lena - Malzeme sorgula\n"
                         "/kaydet 5 gr NPK - Stoktan düş\n"
                         "/kaydet_geri_al - Son işlemi geri al\n"
                         "/ekle NPK;1000;gr;Gübre - Yeni malzeme ekle\n"
                         "/sil Test - Malzeme sil (onay için /evet)\n"
                         "/ph 1 - Son pH ölçümü\n"
                         "/ph 1 hepsi - Tüm pH ölçümleri (çamur testleri dahil)\n"
                         "/ph_ekle 1 6.5 - Yeni pH ekle\n"
                         "/test - Bot testi")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

# ==================== STOK ====================
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

# ==================== KAYDET ====================
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

# ==================== EKLE ====================
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

# ==================== SİLME ====================
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
                       f"Bu işlem GERİ DÖNÜŞÜMSÜZDÜR!\n\n"
                       f"30 saniye içinde `/evet` yazın.")

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

# ==================== pH ====================
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
        await message.reply("Örnek: /ph 1 - Son ölçüm\n/ph 1 hepsi - Tüm ölçümler (çamur testleri dahil)")
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

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
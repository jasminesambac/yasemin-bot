import os
import logging
import csv
import io
import zipfile
from datetime import datetime
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Geçici hafızalar
son_kayit_geri_al = None
silinecek_malzeme = None
silinecek_ph_kayitlari = None
silinecek_gecmis_id = None
silinecek_gecmis_hepsi = None

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

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan** hazır!\n\n"
                         "/stok - Envanter listesi\n"
                         "/stok lena - Malzeme sorgula\n"
                         "/kaydet 5 gr NPK - Stoktan düş\n"
                         "/kaydet Sera kuruldu - İşlem kaydet (stok etkilemez)\n"
                         "/kaydet_geri_al - Son işlemi geri al\n"
                         "/ekle NPK;1000;gr;Gübre - Yeni malzeme ekle\n"
                         "/sil Test - Malzeme sil (onay için /evet)\n"
                         "/ph 1 - Son pH ölçümü\n"
                         "/ph 1 hepsi - Tüm pH ölçümleri\n"
                         "/ph_tumu - Tüm tenekelerin tüm pH\n"
                         "/ph_ekle 1 6.5 - Yeni pH ekle\n"
                         "/ph_sil 1 - Son pH kaydını sil\n"
                         "/gecmis - Son 10 işlem (ID ile)\n"
                         "/gecmis hepsi - Tüm geçmiş (ID ile)\n"
                         "/gecmis 14-05-2026 - Tarihli işlemler\n"
                         "/gecmis_sil 5 - ID ile işlem sil (onay için /gecmis_evet)\n"
                         "/hatirlat 30-07-2026 10:00 Sula - Hatırlatma ekle\n"
                         "/hatirlatmalar - Bekleyen hatırlatmalar (ID ile)\n"
                         "/hatirlat_sil 1 - Hatırlatma sil\n"
                         "/yedekle - Tüm CSV'leri yedekle\n"
                         "/test - Bot testi")

@dp.message_handler(commands=['test'])
async def test(message: types.Message):
    await message.answer("✅ Bot çalışıyor!")

# ==================== YEDEKLEME ====================
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

# ==================== HATIRLATMA ====================
@dp.message_handler(commands=['hatirlat'])
async def hatirlat(message: types.Message):
    param = message.get_args()
    if not param:
        await message.reply("Örnek: /hatirlat 30-07-2026 10:00 Sula")
        return
    
    parcalar = param.split(maxsplit=2)
    if len(parcalar) < 3:
        await message.reply("Format: /hatirlat gun-ay-yil saat islem\nÖrnek: /hatirlat 30-07-2026 10:00 Sula")
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

# ==================== KAYDET ====================
@dp.message_handler(commands=['kaydet'])
async def kaydet(message: types.Message):
    global son_kayit_geri_al
    islem = message.get_args()
    if not islem:
        await message.reply("Örnek: /kaydet 5 gr NPK veya /kaydet Sera kuruldu")
        return
    
    # Sayı ile başlıyorsa (örn: 5 gr NPK) stok işlemi dene
    parcalar = islem.split()
    if len(parcalar) >= 3 and parcalar[0].replace('.', '').replace(',', '').isdigit():
        try:
            miktar = float(parcalar[0].replace(',', '.'))
            birim = parcalar[1]
            malzeme_aranan = " ".join(parcalar[2:])
        except:
            # Sayı okunamadı, sadece history'ye kaydet
            history_ekle("İşlem", islem, "-", "-")
            await message.reply(f"✅ İşlem kaydedildi:\n📝 {islem}")
            return
        
        stoklar = stok_oku()
        eslesenler = malzeme_bul(malzeme_aranan, stoklar)
        
        if not eslesenler:
            # Stokta bulunamadı, sadece history'ye kaydet
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
        # Sayı ile başlamıyorsa (Çit döşendi, Sera kuruldu, vb.)
        history_ekle("İşlem", islem, "-", "-")
        await message.reply(f"✅ İşlem kaydedildi:\n📝 {islem}")
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

# ==================== pH EKLE ====================
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

# ==================== pH SORGULA ====================
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

# ==================== TÜM TENEKELERİN TÜM pH ====================
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

# ==================== pH SİLME ====================
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
            
            import asyncio
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

# ==================== GEÇMİŞ SİLME ====================
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
            
            import asyncio
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
            
            import asyncio
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

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
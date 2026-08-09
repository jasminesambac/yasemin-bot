# Yasemin Bot - Test / Kontrol Listesi

Render'da deploy tamamlandıktan sonra, aşağıdaki maddeleri sırayla botta deneyerek işaretleyebilirsin. Her madde: ne yapılacağını, nasıl test edileceğini ve beklenen sonucu açıklıyor.

## 1. Hatırlatma kayıt anında hemen bildirim gitmemesi (bug düzeltmesi)

- **Neden test edilmeli:** Daha önce, seçtiğin saat o gün için geçmişse (ör. şu an 18:00 ve sen "her gün 17:00" diye kurmuşsan), kayıttan hemen sonra yanlışlıkla bir bildirim geliyordu.
- **Nasıl test edilir:** Şu andan geçmişte kalacak bir saatle (ör. şu an 15:00'ıysa, 09:00) günlük/haftalık/aylık/aralıklı bir hatırlatma kur.
- **Beklenen sonuç:** Kayıttan hemen sonra bildirim GELMEMELİ. Hatırlatma, tarihi bir sonraki uygun güne (yarın 09:00, ya da haftalık/aylıksa bir sonraki uygun tarihe) otomatik atlamalı. "Bekleyen Hatırlatmalar" listesinden tarihi kontrol edebilirsin.

## 2. Aralıklı ("Her X Günde Bir") hatırlatmada başlangıç tarihi sorusu

- **Nasıl test edilir:** Hatırlatma Ekle → tarih seçiminde "Her X Günde Bir" → gün sayısı yaz (ör. 3).
- **Beklenen sonuç:** Artık otomatik "bugün" almak yerine "Başlangıç tarihi seç: Bugün / Yarın / Özel Tarih" sorulmalı. "Özel Tarih" seçince tarih yazman istenmeli (ör. 14-06-2026), ardından saat seçimi gelmeli.

## 3. Menü dışı yazdığın mesajlara AI cevap vermesi

- **Nasıl test edilir:** Herhangi bir menü/form açık değilken (ana ekrandayken) düz bir soru yaz, ör. "domates ne zaman ekilir" veya "merhaba nasılsın".
- **Beklenen sonuç:** "Lütfen menüden bir buton seç" YERİNE doğrudan bir AI cevabı gelmeli (Gemini/Groq/Agnes sırayla denenir).
- **Karışma kontrolü (önemli):** Stok ekleme, hatırlatma kurma, gözlem kaydı gibi bir formun ORTASINDAYKEN (ör. "malzeme adını yaz" dediği an) bir şey yaz. Bu durumda AI cevap VERMEMELİ, yazdığın şey normal şekilde o formun ilgili alanına gitmeli (ör. malzeme adı olarak kaydedilmeli).

## 4. Doğal dille otomatik kayıt AI cevabından önce denenmeli

- **Nasıl test edilir:** Menü dışında "3 kg gübre stoğa ekledim" gibi kayıt niyeti belli bir cümle yaz.
- **Beklenen sonuç:** Serbest AI cevabı değil, ✅ Onayla / ❌ İptal butonlu bir özet gelmeli (madde 3'teki genel AI cevabı sadece bunu tanımadığında devreye girmeli). Onayla'ya basmadan hiçbir şey kaydedilmemeli.

## 5. Sesli mesajlara da direkt AI cevabı

- **Nasıl test edilir:** Menü dışında (ana ekrandayken) bir sesli mesaj kaydedip gönder.
- **Beklenen sonuç:** Otomatik olarak metne çevrilip ("Ses metni: ...") altına AI cevabı gelmeli — önceden "Sesli Sor" menüsüne girmen gerekmiyor artık.
- **Karışma kontrolü:** Bir formun ortasındayken (ör. stok eklerken) sesli mesaj gönderirsen, bot buna hiç tepki vermemeli (form bozulmamalı).
- **Not:** Bu özellik `GROQ_API_KEY` gerektirir; Render'da tanımlı değilse kısa bir bilgi mesajı görürsün.

## 6. Kritik stok bildirimi tek seferlik

- **Nasıl test edilir:** Bir malzemeyi kritik seviyenin altına düşür (stok kullan) ve bekle (arka plan kontrolü ~60 sn'de bir çalışıyor).
- **Beklenen sonuç:** Sadece **1 defa** anlık uyarı gelmeli, art arda tekrar tekrar gelmemeli. Stok tekrar kritik seviyenin üstüne çıkıp tekrar düşerse yeniden 1 defa gelmeli.

## 7. Malzeme son kullanma tarihi takibi

- **Nasıl test edilir:** Stok Ekle akışında not adımından sonra son kullanma tarihi sor (ör. bugünden 10 gün sonrası bir tarih yaz).
- **Beklenen sonuç:** "📍 Bugün" ve "🧭 Durum" ekranlarında "Son Kullanma Tarihi Yaklaşan" bölümünde bu malzeme görünmeli. Bildirim sadece 1 defa gelmeli (spam olmamalı).

## 8. pH ve stok grafik görselleri

- **Nasıl test edilir:** Rapor menüsü → "🔬 pH Grafiği" (bir teneke seç) ve "📉 Stok Grafiği".
- **Beklenen sonuç:** Gerçek bir PNG çizgi grafiği gelmeli. Yeterli veri yoksa hataya düşmeden eski metin listesine dönmeli.

## 9. PlantNet bitki tanıma + hastalık/zararlı tespiti

- **Nasıl test edilir:** Bitki Tanı akışına bir yaprak/çiçek fotoğrafı gönder; ayrıca Gözlem → AI Gözlem akışına bir fotoğraf gönder.
- **Beklenen sonuç:** Bitki Tanı'da tür adı, eşleşme yüzdesi ve familya bilgisi gelmeli. AI Gözlem'de Gemini yorumuna ek olarak (varsa) hastalık/zararlı olasılığı eklenmeli. Fotoğraf net değilse/bulunamazsa anlaşılır bir hata mesajı gelmeli, bot çökmemeli.

## 10. Hava durumuna göre sulama notu

- **Nasıl test edilir:** Önce Hava Durumu'ndan bir şehir sorgula. Sonra metninde "sula" geçen bir hatırlatma kur ve zamanı gelmesini bekle (ya da yakın bir saate kur).
- **Beklenen sonuç:** O gün yağmur bekleniyorsa hatırlatma mesajına otomatik bir not eklenmeli ("Bugün için yağmur bekleniyor..."). Hava durumu alınamazsa hatırlatma yine de normal şekilde gelmeli.

## 11. Haftalık otomatik yedekleme

- **Nasıl test edilir:** Bu, sadece her Pazartesi ~08:00'de otomatik çalışıyor — bir sonraki Pazartesi kontrol edebilirsin. Acil test istersen manuel "💾 Yedekle" butonu hâlâ çalışıyor.
- **Beklenen sonuç:** Pazartesi sabahı elle bir şey yapmadan zip dosyası Telegram'a gelmeli.

## 12. AI kalıcı hafıza

- **Nasıl test edilir:** AI Sor (Gemini/Groq/Agnes) ile birkaç soru sor, sonra ana menüye dön, tekrar AI menüsüne gir ve devam eden bir soru sor (ör. "az önce ne demiştim").
- **Beklenen sonuç:** Bot önceki soruları hatırlıyor gibi cevap vermeli. "AI Hafızayı Temizle" butonuna basınca bu hafıza gerçekten silinmeli, bir sonraki soruda eski konuşma geri gelmemeli.

## 13. Bot hata/çökme bildirimi

- **Nasıl test edilir:** Doğrudan tetiklemesi zor; arka planda bir hata olursa (ör. Sheets geçici erişilemez olursa) kendi sohbetine kısa bir "⚠️ Bot hatası" mesajı gelmesini bekleyebilirsin. Özel bir test gerekmiyor, sadece bilgi amaçlı.
- **Beklenen sonuç:** Aynı hata art arda gelirse 10 dakikada en fazla 1 bildirim almalısın (spam olmamalı).

## 14. Mevsimsel (yıllık) hatırlatma

- **Nasıl test edilir:** Hatırlatma Ekle → "🌱 Her Yıl (Mevsimsel)" → gün-ay yaz (ör. 15-03).
- **Beklenen sonuç:** Hatırlatma her yıl o tarihte tekrar etmeli; "Bekleyen Hatırlatmalar" listesinde "Yıllık (Mevsimsel)" etiketiyle görünmeli.

## 15. Hızlı arama

- **Nasıl test edilir:** Sistem menüsü → 🔍 Hızlı Arama → bir kelime yaz (ör. bir malzeme adı).
- **Beklenen sonuç:** İlgili kayıtlar (stok/geçmiş/kompost/plan vb.) anında listelenmeli, AI kullanılmamalı (hızlı olmalı).

## 16. Sabit "🏠 Menü" butonu

- **Nasıl test edilir:** Sohbetin altındaki sabit butona herhangi bir ekrandayken bas; mesajları temizleyip tekrar kontrol et.
- **Beklenen sonuç:** Buton her zaman görünür kalmalı ve her tıklandığında ana menüye dönmeli — mesaj geçmişi silinse bile kaybolmamalı.

## Genel / Son Kontrol

- [ ] Render deploy loglarında hata yok mu kontrol et.
- [ ] Bot `/start` ile açılıyor mu, ana menü ve sabit "🏠 Menü" butonu geliyor mu.
- [ ] Yukarıdaki maddelerden en az birkaçını gerçek verilerle dene (test verisi eklemekten çekinme, silmek istersen ilgili "sil/kapat" butonları var).
- [ ] `PLANTNET_API_KEY` ve (opsiyonel) `PLANTNET_PROJECT` Render Variables'da tanımlı mı.
- [ ] `GROQ_API_KEY` tanımlı mı (sesli mesaj ve bazı AI cevapları için gerekli).

# Yasemin Bot - Yapılan Değişiklikler

Bu doküman, bu konuşma boyunca `bot.py` üzerinde yapılan tüm değişiklikleri özetler. Sen bu süre boyunca sadece Render'a API key eklemekle uğraştın; kod tarafındaki her şey aşağıda listeli.

## 1. Hatırlatmalara "Her X Günde Bir" tekrar tipi

Daha önce hatırlatmalarda sadece Her Gün / Haftalık / Aylık tekrar seçenekleri vardı. Artık serbest aralıklı bir tekrar tipi de var.

- Tarih seçim menüsüne "Her X Günde Bir" butonu eklendi.
- Seçilince kaç günde bir tekrarlanacağı soruluyor, ardından diğerleri gibi saat seçimi geliyor.
- Sheets'teki `reminders` sayfasına `Gun_Araligi` sütunu otomatik eklendi (bot ilk çalıştığında kendisi ekler, elle bir şey yapmana gerek yok).
- Arka plandaki hatırlatma kontrolcüsü (`reminder_worker`) bu aralığa göre bir sonraki tarihi otomatik hesaplayıp tekrar kuruyor.

## 2. Hatırlatmalarda bitiş tarihi / tekrar sayısı sınırı

Tekrarlı hatırlatmalar (günlük/haftalık/aylık/aralıklı) artık sonsuza kadar sürmek zorunda değil.

- Saat seçildikten sonra, tekrarlı bir hatırlatmaysa "Sınırsız / Bitiş Tarihi Belirle / Tekrar Sayısı Belirle" soruluyor.
- Sheets'e `Bitis_Tarihi` ve `Kalan_Tekrar` sütunları otomatik eklendi.
- Sınıra ulaşınca hatırlatma otomatik olarak durup "gönderildi" durumuna geçiyor.
- "Bekleyen Hatırlatmalar" listesinde artık sınır bilgisi de görünüyor (ör. "Haftalık, 3 tekrar kaldı" veya "30-09-2026 tarihine kadar").

## 3. Kritik stok için otomatik hatırlatma + bug düzeltmesi

- **Bug düzeltmesi:** Kritik stok uyarı sistemi (`stock_alert_worker`) kodda tanımlıydı ama hiçbir yerde başlatılmıyordu, yani hiç çalışmıyordu. `post_init` fonksiyonuna eklenerek bu düzeltildi — artık kritik stok uyarıları gerçekten gönderiliyor.
- Bir malzeme kritik seviyeye düştüğünde, mevcut anlık uyarı mesajına ek olarak 30 dakika sonrasına otomatik bir hatırlatma kaydı da oluşturuluyor. Böylece "Bugün" ekranında ve "Bekleyen Hatırlatmalar" listesinde de görünüyor, unutulmuyor.

## 4. AI: Kayıtlara doğal dille soru sorma

- AI menüsüne "📊 Verilerime Sor" seçeneği eklendi.
- Stok, geçmiş işlemler, kompost, pH kayıtları, bekleyen planlar, açık sorunlar, aktif esanslar, son günlük notları ve bekleyen hatırlatmalar özetlenip Gemini/Groq'a veriliyor.
- Böylece "bu ay en çok neyi kullandım", "teneke 3'ün son pH'ı ne", "açık sorun var mı" gibi sorular doğrudan kayıtlara bakılarak cevaplanabiliyor.

## 5. Performans / Google Sheets kota iyileştirmesi

- Kayıt önbelleği (cache) süresi 2 saniyeden 15 saniyeye çıkarıldı; aynı verinin art arda tekrar tekrar Sheets'ten çekilmesi azaldı.
- `set_cells_by_header` adında yeni bir yardımcı fonksiyon eklendi: aynı satırdaki birden fazla hücreyi tek bir Sheets isteğiyle güncelliyor (öncesinde her hücre ayrı bir istekti).
- Bu toplu güncelleme; stoktan malzeme düşme, hatırlatma tekrarlarını yeniden planlama, uyarı durumlarını (`alerts`) güncelleme ve sorun kapatma gibi en sık çalışan yerlerde kullanılıyor. Sonuç: daha az API isteği, daha az kota riski, biraz daha hızlı yanıt.

## 6. PlantNet ile bitki tanıma (fotoğraf) entegrasyonu

- Önceden "Bitki Tanı" özelliği Perenual'ın identify API'sine bağlıydı ama sen bu API'ye hiç anahtar almadığın için hiç çalışmıyordu.
- Artık [PlantNet](https://plantnet.org) kullanılıyor (`PLANTNET_API_KEY` — Render'a eklediğin anahtar).
- Gönderilen fotoğraf PlantNet'in `v2/identify` uç noktasına yollanıyor, organ tipi "auto" bırakılıyor (PlantNet kendisi anlıyor: yaprak/çiçek/meyve vs.).
- Sonuç olarak en olası 5 tür; eşleşme yüzdesi, yaygın adlar ve familya bilgisiyle listeleniyor.
- Gemini veya Groq varsa, en olası tür üzerinden kısa bir Türkçe bakım tavsiyesi de ekleniyor.
- Bulunamama (404) ve anahtar hatası (400/401/403) durumları için ayrı, anlaşılır hata mesajları eklendi.

## 7. Kritik stok bildirimi tek seferle sınırlandı

- Bir önceki turda kritik stok tespit edilince hem anlık uyarı hem de 30 dk sonrasına ek bir hatırlatma oluşturuluyordu — bu, aynı sorun için 2 ayrı bildirim anlamına geliyordu.
- Senin isteğin üzerine bu ek hatırlatma kaldırıldı. Artık kritik stok başına yalnızca **tek** bir anlık uyarı mesajı gönderiliyor.
- Bunu tekrar tekrar göndermeyen asıl "bir kere bildir, stok düzelene kadar sessiz kal" mantığı (`stock_sent_v2` takip sistemi) hiç değiştirilmedi — o zaten önceden düzeltilmiş haliyle duruyordu, ben sadece üstüne (artık kaldırdığım) bir hatırlatma ekliyordum.
- Kritik stok kalıcı olarak görülmek istenirse zaten "Bugün" ekranı ve "🚨 Kritik Stok" butonu her açıldığında güncel listeyi gösteriyor — bildirim spam'i olmadan.

## 8. PlantNet ile hastalık/zararlı tespiti

- "📸 Fotoğrafı AI Yorumla" (Gözlem → AI Gözlem) akışına PlantNet'in ayrı hastalık/zararlı tespit API'si eklendi.
- Gönderdiğin fotoğraf hem genel Gemini yorumundan hem de PlantNet'in `v2/diseases/identify` uç noktasından geçiyor; olası hastalık/zararlı adları ve olasılık yüzdeleriyle mevcut AI yorumuna ekleniyor.
- Sonuç bulunamazsa veya API'de sorun olursa bu bölüm sessizce atlanıyor, gözlem kaydı normal şekilde devam ediyor (asla hata vermiyor).

## 9. Hava durumuna göre akıllı sulama hatırlatıcı

- Hava durumunu (📍Hava Durumu menüsünden) hangi şehir için sorgularsan, o şehir artık "bahçe şehri" olarak otomatik hatırlanıyor.
- Metninde "sula" geçen bir hatırlatma (ör. "Sulama yap", "Sulamayı unutma") tetiklendiğinde, bahçe şehrin için bugün yağmur ihtimali yüksekse mesaja otomatik bir not ekleniyor: "Bugün için yağmur bekleniyor, sulamayı erteleyebilirsin."
- Hava durumu sorgusu başarısız olursa hatırlatma yine normal şekilde gönderiliyor — bu özellik asla hatırlatmanın gitmesini engellemiyor, sadece bilgi ekliyor.

## 10. Haftalık otomatik yedekleme

- Daha önce yedek almak için elle "💾 Yedekle" butonuna basman gerekiyordu.
- Artık her Pazartesi sabah 08:00 civarında zip yedeği otomatik olarak Telegram'a gönderiliyor, elle bir şey yapmana gerek yok.
- Aynı hafta içinde tekrar göndermemesi için hangi haftanın yedeğinin gönderildiği ayrıca takip ediliyor.

## 11. AI için kalıcı hafıza

- Önceden Agnes/Gemini/Groq sohbet hafızası sadece `context.user_data` içindeydi; bot yeniden başladığında veya sen herhangi bir menüye dönüp AI menüsüne tekrar girdiğinde tamamen siliniyordu.
- Artık hafıza boşsa (ilk mesaj, bot restart olmuş, ya da menüden çıkıp girmişsin), o AI için kalıcı olarak Sheets'e kaydedilen son ~6 soru-cevabı (`ai_agnes_logs`, `ai_gemini_logs`, `ai_groq_logs` sayfalarından, sadece senin kendi geçmişin) otomatik geri yükleniyor.
- "AI Hafızayı Temizle" butonuna basarsan bu artık gerçekten temizliyor — bir sonraki soruda eski hafıza tekrar geri yüklenmiyor (öncesinde bu küçük bir çelişkiye yol açacaktı, düzelttim).
- Bu değişiklik sadece "AI Sor" ekranlarını (Agnes/Gemini/Groq/İkisine de Sor) etkiliyor; reçete önerisi, bitki bakım tavsiyesi, günlük özeti gibi tek seferlik yardımcı AI çağrılarına karışmıyor.

## 12. Bot hata/çökme bildirimi

- Önceden bir hata olduğunda sadece o an mesaj yazan kişi "bir hata oldu" görüyordu, sen (bot sahibi) haberdar olmuyordun; arka plan görevlerindeki (hatırlatma kontrolü, kritik stok kontrolü, haftalık yedekleme) hatalar ise sadece sunucu loglarında kalıyordu.
- Artık hem kullanıcı etkileşimlerinden gelen hatalarda hem de arka plan görevlerindeki hatalarda, kayıtlı sohbetine (aynı `stock_chat_id`) kısa bir uyarı mesajı gidiyor: "⚠️ Bot hatası (kaynak) — hata türü ve detay".
- Aynı hata art arda tekrar ederse spam olmasın diye, aynı kaynak+hata türü için 10 dakikada en fazla 1 bildirim gönderiliyor.

## 13. Mevsimsel (yıllık tekrar) hatırlatma

- Hatırlatma tarihi seçim ekranına "🌱 Her Yıl (Mevsimsel)" seçeneği eklendi.
- Seçince gün-ay formatında bir tarih yazman isteniyor (ör. 15-03 → her yıl 15 Mart), ardından diğer tekrar tipleriyle aynı akış: saat seçimi, isteğe bağlı bitiş tarihi/tekrar sayısı sınırı.
- Böylece "her ilkbahar gübreleme", "her sonbahar budama" gibi mevsimsel/yıllık görevleri tek seferde kurup her yıl otomatik hatırlatma alabilirsin.
- 29 Şubat gibi artık yıl kenar durumları da doğru şekilde bir sonraki uygun tarihe (28 Şubat) yuvarlanıyor.

## 14. Hızlı arama

- AI kullanmadan, doğrudan stok, geçmiş, kompost, plan, alan, sorun, günlük, reçete, esans, gözlem ve hatırlatma kayıtlarında anahtar kelime araması yapan bir özellik eklendi.
- Anında sonuç veriyor, AI kotası harcamıyor — hızlı bir "şunu nerede kaydetmiştim" sorgusu için ideal.
- **Nasıl kullanılır:** Sistem menüsü → 🔍 Hızlı Arama butonuna dokun, aramak istediğin kelimeyi yaz. (Komut yazmak isteyenler için `/ara kelime` de hâlâ çalışıyor ama artık zorunlu değil.)

## 15. Her zaman erişilebilir Menü butonu (komut yazmadan)

- Sohbetin altında, klavyenin hemen üstünde artık **🏠 Menü** adında sabit bir buton var — bu buton hiçbir zaman kaybolmuyor, hangi ekranda/akışta olursan ol her zaman görünür durumda.
- Bu butona dokunduğun an, o an ne yapıyor olursan ol (bir form dolduruyor, bir soruya cevap yazıyor olsan bile), doğrudan ana menüye dönüyorsun.
- Artık `/start` veya `/menu` yazmana hiç gerek yok — botu ilk açtığında Telegram zaten otomatik bir "BAŞLAT" butonu gösteriyor (dokunuşluk), ondan sonra her şey bu sabit Menü butonuyla buton bazlı devam ediyor.
- Not: Malzeme adı, miktar, not, tarih gibi form alanlarına hâlâ yazman gerekiyor (bunlar serbest metin olduğu için buton haline getirilemez) — ama menüler arası gezinme ve komutlar tamamen buton tabanlı.

## 16. Doğal dille otomatik kayıt (onaylı)

- Artık hiçbir menüde değilken düz bir cümle yazabilirsin, ör. "bugün 3 litre su ile sulama yaptım" veya "5 kg gübre stoğa ekledim" veya "teneke 3 pH 6.5 ölçtüm".
- AI bunu otomatik olarak yapısal bir işleme çeviriyor ve sana bir özet gösterip **✅ Onayla / ❌ İptal** butonlarını sunuyor.
- **Hiçbir şey senin onayın olmadan kaydedilmiyor** — AI sadece bir taslak hazırlıyor, gerçek kayıt/stok düşme işlemi sadece "Onayla" dediğinde, mevcut ve test edilmiş stok/pH fonksiyonları üzerinden yapılıyor.
- AI ne dediğini anlayamazsa (ya da sadece sohbet ediyorsan), normal şekilde ana menü gösteriliyor, hiçbir şey bozulmuyor.

## 17. Grafik/trend görselleri (yeni bağımlılık: matplotlib)

- Rapor menüsüne **🔬 pH Grafiği** eklendi: bir teneke seç (veya "Tümü" ile hepsini üst üste gör), zaman içindeki pH değişimini gerçek bir çizgi grafiği (PNG resim) olarak alıyorsun.
- Mevcut **📉 Stok Grafiği** artık gerçekten grafik çiziyor (öncesinde sadece metin listesiydi) — bir malzemenin kullanım miktarlarını zaman içinde çizgi grafiği olarak gösteriyor. Yeterli sayısal veri yoksa otomatik olarak eski metin listesine geri dönüyor, hata vermiyor.
- **Önemli:** Bu özellik için `requirements.txt`'ye `matplotlib` eklendi — Render'da bir sonraki deploy'da bu paket otomatik kurulacak, senin bir şey yapmana gerek yok, ama bu konuşmadaki **ilk `requirements.txt` değişikliği** bu, bilgin olsun.

## 18. Malzeme son kullanma tarihi takibi

- Stok ekleme akışına yeni bir opsiyonel adım eklendi: not girdikten sonra "Son kullanma tarihi var mı?" diye soruyor, yoksa '-' yazıp geçebilirsin.
- Son kullanma tarihine 14 gün ve daha az kalan (veya süresi geçmiş) malzemeler artık "📍 Bugün" ekranında ve "🧭 Durum" ekranında ayrı bir bölümde listeleniyor.
- Kritik stok bildirimindeki gibi, süresi yaklaşan bir malzeme için **sadece bir kere** bildirim gönderiliyor (senin "sürekli bildirim istemiyorum" tercihine sadık kalarak) — tekrar tekrar hatırlatmıyor.

## Render'a Eklenmesi Gereken Değişkenler

| Değişken | Zorunlu mu | Açıklama |
|---|---|---|
| `PLANTNET_API_KEY` | Evet (bitki tanıma + hastalık tespiti için) | PlantNet'ten aldığın anahtar |
| `PLANTNET_PROJECT` | Hayır (opsiyonel) | Varsayılan `all`; istersen `weurope` gibi bölgesel flora setleri kullanılabilir |

Diğer tüm değişiklikler (hatırlatma sınırları, kritik stok bildirimi, AI kayıt sorgusu, performans iyileştirmeleri, hava durumu entegrasyonu, haftalık yedekleme) mevcut environment değişkenlerinle otomatik çalışır, ek bir şey eklemene gerek yok.

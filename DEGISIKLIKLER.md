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

## 19. Hatırlatma: kayıt anında geçmişse hemen bildirim gitmesin (bug düzeltmesi)

- **Sorun:** Tekrarlı bir hatırlatma (günlük/haftalık/aylık/aralıklı/mevsimsel) kurarken seçtiğin saat o gün için zaten geçmişse (ör. "3 günde bir, saat 17:00" ama şu an saat 17:00'den sonraysa), hatırlatma kaydedildikten hemen sonra bir bildirim geliyordu — çünkü ilk tarih "bugün" olarak kaydediliyor ve arka plan kontrolcüsü bunu "zamanı geçmiş, hemen gönder" olarak görüyordu.
- **Düzeltme:** Yeni bir `adjust_initial_reminder_date` fonksiyonu eklendi. Hatırlatma kaydedilmeden hemen önce, seçilen ilk tarih+saat şu ana göre geçmişte kalıyorsa, tekrar tipine göre (günlük/haftalık/aylık/aralıklı/mevsimsel) bir sonraki uygun tarihe otomatik ileri sarılıyor. Böylece kayıt anında asla geçmiş bir tarih/saatle kaydolmuyor, ilk bildirim gerçekten doğru zamanda geliyor.
- Bu düzeltme, hatırlatma kaydının yapıldığı **tek** koddaki yerde uygulandığı için (kontrol edildi), tüm tekrar tiplerini kapsıyor — sadece aralıklı değil, günlük/haftalık/aylık/mevsimsel hatırlatmalarda da aynı sorun varsa artık düzeldi.

## 20. Aralıklı ("Her X Günde Bir") hatırlatmaya başlangıç tarihi sorusu

- Önceden "Her X Günde Bir" seçilince gün sayısını yazdıktan sonra başlangıç tarihi hep otomatik "bugün" olarak alınıyordu, sormuyordu.
- Artık gün sayısını yazdıktan sonra "Başlangıç tarihi seç: Bugün / Yarın / Özel Tarih" soruluyor, tıpkı diğer hatırlatma tiplerindeki akışlar gibi buton tabanlı.
- "Özel Tarih" seçilirse tarihi yazman isteniyor (ör. 14-06-2026), ardından her zamanki gibi saat seçimine geçiliyor.

## 21. Menü dışı serbest mesajlarda AI direkt cevap versin

- Artık hiçbir menü/form akışında değilken (yani `flow` boşken) düz bir mesaj yazdığında, önce doğal-dil otomatik kayıt (bkz. madde 16) deneniyor; o tanımıyorsa artık "Lütfen menüden bir buton seç" demek yerine mesajın **doğrudan AI cevabı** geliyor (Gemini varsa Gemini, yoksa Groq, o da yoksa Agnes).
- Bu cevaplar da diğer AI sohbetleri gibi ilgili log sayfasına (`ai_gemini_logs` / `ai_groq_logs` / `ai_agnes_logs`) kaydediliyor, kalıcı hafıza (madde 11) burada da geçerli.
- **Önemli — karışma yok:** Bu davranış sadece `flow` boşken (yani herhangi bir form/kayıt akışı açık değilken) devreye giriyor. Stok ekleme, hatırlatma kurma, gözlem kaydı gibi bir akışın ortasındayken yazdığın metinler her zamanki gibi o akışa gidiyor, AI araya girmiyor — bunu ayrıca kontrol ettim.

## 22. Sesli mesajlarda da aynı şekilde direkt AI cevabı

- Önceden sesli mesaj gönderdiğinde AI cevabı almak için önce AI menüsünden "🎙️ Sesli Sor" butonuna basman gerekiyordu.
- Artık madde 21'deki mantığın aynısı sesli mesajlar için de geçerli: hiçbir menü/form akışı açık değilken doğrudan bir sesli mesaj gönderirsen, otomatik olarak metne çevrilip (Groq Whisper) AI cevabı veriliyor ve `ai_voice_logs`'a kaydediliyor.
- Bir form/kayıt akışının ortasındaysan (ör. stok ekleme) sesli mesaj bu akışa karışmıyor, hiçbir şey yapmıyor — sadece akış boşken veya zaten "Sesli Sor" menüsündeyken çalışıyor.
- Groq ayarı (`GROQ_API_KEY`) yoksa sesli mesajlar işlenemez, bu durumda kısa bir bilgi mesajı gösteriliyor.

## 23. Bug düzeltmesi: AI sohbet hafızası "kirleniyordu", alakasız JSON cevabı geliyordu

- **Sorun (senin test ettiğin bug):** "Sulama yaptım" yazınca bot düz cevap yerine `{"action": "bilinmiyor"}` gibi ham JSON gönderiyordu; benzer şekilde başka bazı yerlerde de beklenmedik JSON/teknik metin görülüyordu.
- **Kök sebep:** Doğal dille otomatik kayıt özelliği (madde 16), arka planda AI'a "bu cümleyi şu JSON şablonlarından birine çevir" diye bir talimat gönderiyor. Bu iç/teknik istek, kodun bir hatası yüzünden **senin gerçek AI sohbet geçmişinle aynı hafızaya** kaydediliyordu. Sonuç: bu JSON talimatı bir kere hafızaya girdiğinde, ondan sonraki gerçek AI cevapların da JSON formatında gelmeye başlıyordu (AI kendi önceki "sadece JSON döndür" talimatını hafızada görüp onu taklit ediyordu).
- **Düzeltme:** Artık böyle iç/teknik AI çağrıları (doğal dil kayıt ayrıştırma, dosya özeti, "Verilerime Sor", günlük AI özeti, bitki bakım tavsiyesi, güncel arama özeti gibi tek seferlik işlemler) tamamen ayrı, hafızasız bir kanaldan gidiyor — artık senin gerçek AI Sohbet geçmişine hiç dokunmuyorlar. AI Sohbet (Agnes/Gemini/Groq/İkisine de Sor/Sesli Sor) ve Bitki AI Tavsiye ekranları hâlâ eskisi gibi hafızalı/sohbet tarzı çalışmaya devam ediyor.
- Bu, hem "Sulama yaptım" gibi menü dışı serbest mesajlarda hem de (dolaylı olarak) o sıradaki başka AI cevaplarında gördüğün tutarsız/JSON çıktısı sorununu kökten çözüyor.

## 24. Bug düzeltmesi: pH/Stok grafiği bazen donma yapıyor, bazen metne dönüyordu

- **Sorun:** Grafik oluşturulurken bot genel olarak "takılıyor", bazen grafik yerine eski "Son 10 Kullanım" metnine dönüyordu.
- **Kök sebep:** Grafik çizimi (matplotlib) senkron/bloklayan bir işlemdi ve doğrudan botun ana döngüsünde çalışıyordu. Bu süre boyunca (özellikle ilk çalıştırmada yazı tipi önbelleği kurulurken birkaç saniye sürebiliyor) **botun tamamı** — diğer mesajların işlenmesi, hatırlatma kontrolü, her şey — donuyordu. Bu gecikme bazen bir zaman aşımına yol açıp grafik başarısız gibi görünmesine ve metne düşülmesine sebep oluyordu.
- **Düzeltme:** Grafik çizimi artık ayrı bir arka plan iş parçacığında (thread) çalışıyor, bot donmuyor, diğer mesajlar/hatırlatmalar bu süreçten etkilenmiyor. Bu sayede grafik gönderimi de daha tutarlı çalışmalı (artık rastgele metne düşme olmamalı).

## 25. Bitki Ara / Bakım Bilgisi: veritabanında yoksa artık AI'a soruyor

- **Sorun:** "🔎 Bitki Ara" ve "📋 Bakım Bilgisi" (Bitki AI menüsü) sadece Perenual adlı bir bitki veritabanına bakıyordu. Bu veritabanı sınırlı olduğu için "Jasmine Sambac Grand Duke of Tuscany" gibi spesifik bir çeşit/kültivar aratıldığında "Bitki bulunamadı" dönüyordu.
- **Düzeltme:** Perenual'da sonuç bulunamazsa (veya `PERENUAL_API_KEY` hiç tanımlı değilse) artık otomatik olarak Gemini/Groq'a "bu bitkiyi tanıyor musun" diye soruluyor ve AI'ın genel bilgisinden Türkçe bir tanıtım/bakım tavsiyesi geliyor. Cevabın başında "(Perenual veritabanında bulunamadı, AI bilgisiyle cevaplandı)" notu olacak ki kaynağı bilesin. AI de tanımıyorsa bunu açıkça söylemesi isteniyor, uydurmuyor.
- Not: Bu, fotoğrafla bitki tanıma (PlantNet, madde 6) özelliğinden ayrı — bu madde sadece isimle arama/bakım sorgusu içindir.

## 26. AI menüsü daha düzenli gruplandı

- Önceden "🤖 AI Sor" menüsü tek ekranda 7 satır, birbirinden çok farklı 10 seçenek içeriyordu (sohbet, arama, dosya, kayıt sorgusu, log, hafıza temizleme hepsi karışıktı).
- Artık 4 net kategoriye ayrıldı: **💬 AI Sohbet** (Agnes/Gemini/Groq/İkisine de Sor/Sesli Sor), **🔎 Arama & Dosya** (Güncel Ara, Dosya Oku, Dosyaya Sor), **📊 Verilerime Sor** (tek başına, en sık kullanılan), **⚙️ AI Ayarları** (AI Kayıtlar, AI Hafızayı Temizle).
- Hiçbir özellik kaldırılmadı/taşınmadı, sadece daha az tıklamayla ve daha anlaşılır şekilde gruplandı.

## 27. Hava durumu / sulama notu nasıl çalıştığı netleştirildi

- Bu özellik (madde 9) sessiz çalıştığı için fark etmek zordu. Artık 📍Hava Durumu'ndan bir şehrin **anlık** hava durumunu sorguladığında, cevabın altına şu not otomatik ekleniyor: *"(ŞEHİR artık bahçe şehrin olarak kayıtlı. Metninde 'sula' geçen bir hatırlatma zamanı geldiğinde, o gün ŞEHİR için yağmur bekleniyorsa mesaja otomatik bir uyarı notu eklenecek.)"*
- Yani özelliğin çalışması için: (1) en az bir kere bir şehrin anlık hava durumunu sorgulamış olman, (2) hatırlatma metninde "sula" kelimesinin geçmesi, (3) o gün gerçekten yağmur ihtimali olması gerekiyor. Üçü de sağlanmazsa not sessizce eklenmiyor, hatırlatma yine normal şekilde gidiyor — bu bir hata değil, özelliğin tasarımı.

## Render'a Eklenmesi Gereken Değişkenler

| Değişken | Zorunlu mu | Açıklama |
|---|---|---|
| `PLANTNET_API_KEY` | Evet (bitki tanıma + hastalık tespiti için) | PlantNet'ten aldığın anahtar |
| `PLANTNET_PROJECT` | Hayır (opsiyonel) | Varsayılan `all`; istersen `weurope` gibi bölgesel flora setleri kullanılabilir |

## 28. Menü dışı mesajda artık otomatik değil, buton ile seçim

- Önceden menü dışında yazdığın her mesajda bot arka planda otomatik olarak önce "bu bir kayıt mı?" diye AI'a soruyordu, değilse otomatik genel AI cevabına geçiyordu. Bu, senin ne istediğini tahmin etmeye çalışıyordu ve bazen yanlış tahmin edebiliyordu.
- Artık menü dışında bir şey yazdığında bot hiç AI çağırmadan önce sana soruyor: **"📝 Kayda Ekle" / "🤖 AI'a Sor" / "❌ Vazgeç"**. Hangisini seçersen sadece o işlem için AI çağrılıyor.
- **Performans notu:** Bu aslında botu daha az yoruyor, daha çok değil. Eskiden sıradan bir sohbet mesajı (kayıt niyetli olmayan) için bile önce "kayıt mı" diye 1 AI çağrısı, sonra da genel cevap için 2. bir AI çağrısı yapılıyordu (mesaj başına 2 çağrı). Artık sen seçene kadar hiç AI çağrılmıyor, seçtikten sonra sadece 1 çağrı yapılıyor. Yani hem daha hızlı hem daha az AI kullanımı.

## 29. Gemini kotası dolunca (429 hatası) otomatik Groq'a geçiyor

- **Sorun:** Gemini'nin ücretsiz kotası dolduğunda (429 Too Many Requests) bot bu ham hatayı doğrudan sana gösteriyordu: "Gemini hatası: 429 Client Error...".
- **Düzeltme:** Artık Gemini 429 (kota doldu), 403 (yetki hatası) ya da 404 (model bulunamadı) döndürürse veya herhangi bir bağlantı hatası yaşanırsa, `GROQ_API_KEY` tanımlıysa bot **otomatik olarak Groq'a** soruyor. Sen hata mesajı görmüyorsun, sadece hangi AI cevap verdiyse onu görüyorsun. Bu, AI Sohbet, Verilerime Sor, Bitki AI, doğal dil kayıt gibi Gemini kullanan tüm ekranlarda geçerli.
- Groq da tanımlı değilse (veya o da başarısız olursa) eski gibi anlaşılır bir hata mesajı gösteriliyor — sonsuz döngüye girmeyecek şekilde tasarlandı (Groq'tan tekrar Gemini'ye dönmüyor).

## 30. Bitki AI baştan aşağı yenilendi: Bakım Bilgisi/Bitki Ara kaldırıldı, PlantNet odaklı hale geldi

- **Bakım Bilgisi ve Bitki Ara kaldırıldı.** Bu ikisi Perenual adlı sınırlı bir veritabanına bağlıydı. Artık Bitki AI menüsü sadece 3 buton: **📸 PlantNet ile Tanı/Gözlem**, **🤖 AI Tavsiye**, **📋 Tavsiyelerim**.
- **📸 PlantNet ile Tanı/Gözlem**, eski "Bitki Tanı" ve "Bitki Ara"nın yerini alan yeni, tek ve daha güçlü akış: fotoğraf(lar) gönderiyorsun, PlantNet tür tanıması yapıyor, AI kısa bakım tavsiyesi ekliyor, sonuç otomatik olarak **Gözlem kayıtlarına da ekleniyor** (senin istediğin gibi).
- **🤖 AI Tavsiye** artık Perenual değil, doğrudan bitki bakımına adanmış, kendi kalıcı hafızasına sahip bir AI kullanıyor (aşağıda madde 32).

## 31. Fotoğraflı gözlemde ve Bitki AI'da tek seferde 8-10 fotoğraf

- Hem **Gözlem** menüsündeki "📷 Fotoğraflı Gözlem Ekle" / "🤖 Fotoğrafı AI Yorumla", hem de **Bitki AI**'daki "📸 PlantNet ile Tanı/Gözlem" artık tek seferde en fazla **10 fotoğraf** kabul ediyor.
- Fotoğrafları art arda gönderebilirsin (Telegram'dan albüm olarak seçip de gönderebilirsin, tek tek de). Her fotoğraftan sonra "✅ Bitti (N foto)" butonu beliriyor - istediğin kadar fotoğraf gönderdikten sonra bu butona basınca **hepsi tek seferde, tek bir yorumda/tanımada** birleştiriliyor (mesaj uzunsa Telegram'ın izin verdiği ölçüde parçalara bölünüyor, ama tek bir bütün yorum olarak).
- **Davranış değişikliği:** Önceden tek fotoğraf gönderince otomatik kaydediyordu. Artık her zaman (tek fotoğraf olsa bile) "✅ Bitti" butonuna basman gerekiyor - bu, çoklu fotoğraf desteğinin doğal bir sonucu.
- 10 fotoğrafa ulaşırsan otomatik olarak işleme geçiyor, buton beklemiyor.

## 32. Bitki AI artık hiç unutmuyor (kalıcı, ayrı hafıza)

- Önceden "AI Tavsiye" sohbeti genel AI Sohbet ile aynı hafızayı paylaşıyordu (bu aslında genel sohbeti de kirletiyordu). Artık Bitki AI'nın **kendi ayrı ve kalıcı hafızası** var.
- Bot yeniden başlasa da, menüden çıkıp girsen de, Bitki AI önceki bitki bakımı konuşmalarını Sheets'ten (`ai_plant_logs` sayfası) otomatik geri yüklüyor - **"AI Hafızayı Temizle" butonundan etkilenmiyor**, bilinçli olarak sürekli hatırlıyor çünkü bitki bakımından sorumlu.
- Gemini kotası dolarsa (429) burada da otomatik Groq'a geçiyor (madde 29'daki gibi).

## 33. AI Tavsiye'yi kaydet, reçeteye çevir, Tavsiyelerim listesi

- "🤖 AI Tavsiye" cevabının altına iki yeni buton eklendi: **💾 Tavsiye Olarak Kaydet** ve **🧪 Reçete Olarak Kaydet**.
- "Tavsiye Olarak Kaydet" yeni bir `plant_advice_saved` sayfasına kaydediyor; Bitki AI menüsündeki **📋 Tavsiyelerim** butonundan bu kayıtları listeleyebilir, silebilirsin.
- "Reçete Olarak Kaydet" aynı tavsiyeyi doğrudan mevcut **Reçeteler** listesine ekliyor (Reçeteler menüsünden görebilir, uygulayabilirsin) - iki özellik birbiriyle koordineli çalışıyor.

## 34. Tavsiyelerimi Word/Excel olarak indirme

- **Tavsiyelerim** menüsüne **📄 Word Olarak Al** ve **📊 Excel Olarak Al** butonları eklendi - tüm kaydedilmiş tavsiyelerini tek bir `.docx` ya da `.xlsx` dosyası olarak indirebilirsin.
- **Önemli:** Bunun için `requirements.txt`'ye iki yeni bağımlılık eklendi: `python-docx` ve `openpyxl`. Render'da bir sonraki deploy'da otomatik kurulacaklar, senin bir şey yapmana gerek yok - ama bu konuşmadaki `requirements.txt` değişikliklerinden biri olduğu için bilgin olsun (matplotlib'ten sonraki ilk yeni bağımlılıklar).

## 35. Bug düzeltmesi: PlantNet çoklu fotoğrafta "en fazla 5 görsel" hatası + yanlış tasarım

- **Sorun 1 (senin düzeltmen):** İlk tasarımda gönderdiğin tüm fotoğrafları "aynı bitkinin farklı açıları" gibi TEK bir PlantNet isteğinde birleştiriyordum. Ama sen bahçende aynı türden farklı tenekelerin fotoğraflarını gönderiyorsun - her fotoğraf ayrı bir bitki/teneke, aynı bitkinin açıları değil.
- **Sorun 2 (teknik hata):** Bu yanlış tasarım yüzünden 5'ten fazla fotoğraf gönderdiğinde PlantNet API zaten hata veriyordu: "images must contain at most 5 items" - PlantNet'in kendisi tek istekte en fazla 5 görsele izin veriyor.
- **Düzeltme:** Artık gönderdiğin her fotoğraf PlantNet'e AYRI AYRI, bağımsız birer istekte soruluyor (10 fotoğraf = 10 ayrı tanıma). Her biri kendi Gözlem kaydına, kendi tanı sonucuyla kaydediliyor. En sonda hepsini özetleyen TEK bir genel AI değerlendirmesi/tavsiyesi ekleniyor (aynı türse tek tavsiye, farklı türlerse her biri için kısaca ayrı değiniyor).

## 36. Bug düzeltmesi: Fotoğraf biriktirirken her seferinde mesaj gelmesin

- **Sorun (senin bildirdiğin):** Çoklu fotoğraf gönderirken her fotoğraftan sonra bot yeni bir "N/10 fotoğraf eklendi" mesajı + "✅ Bitti / ❌ İptal" butonları gönderiyordu - 10 fotoğraf gönderince sohbet bu tekrar eden mesajlarla doluyordu.
- **Düzeltme:** Artık fotoğraf gönderirken hiçbir ara mesaj gelmiyor, bot sessizce arka planda biriktiriyor (sadece fotoğrafa küçük bir 👍 reaksiyonu ekliyor, Telegram bunu destekliyorsa). "✅ Bitti" butonu akışın en başında bir kere gönderiliyor ve istediğin zaman (kaç fotoğraf gönderirsen gönder) tıklanabilir kalıyor - tekrar tekrar gönderilmiyor.

## 37. Bug düzeltmesi: Gözlem kayıtları sohbette eksik/kesik görünüyordu

- **Sorun (senin bildirdiğin):** "Gözlem kaydında tam kayıt yapmıyor, karakter yetmiyor sanırım."
- **Kök sebep 1:** Gözlem listesi (📋 Gözlem Geçmişi / Tarihli Gözlemler) her kaydın AI yorumunu sohbette sadece **250 karakterde** kesiyordu. Kayıt Google Sheets'te tamdı, sadece bot ekranda kısaltılmış gösteriyordu - PlantNet artık daha uzun/detaylı sonuçlar ürettiği için bu artık gözle görülür şekilde eksik kalıyordu.
- **Kök sebep 2:** "📋 Gözlem Geçmişi" sayfası (6 kayıt/sayfa) toplam metin Telegram'ın 4096 karakter mesaj sınırını aşarsa mesajı **sessizce hiç gönderemiyordu** (hata da göstermiyordu).
- **Düzeltme:** Artık gözlem listelerinde AI yorumunun **tamamı** gösteriliyor, hiçbir yerde kesilmiyor. Sayfa başına kayıt sayısı 6'dan 4'e düşürüldü ve gerekirse sayfa içeriği otomatik olarak birden fazla mesaja bölünüyor (tek bir kayıt bile çok uzunsa artık sessizce kaybolmuyor, mutlaka gösteriliyor).
- Ayrıca gözlem kayıtlarına yazılan AI yorumuna, Google Sheets'in gerçek hücre sınırını aşıp kayıt hatası vermesin diye 45.000 karakterlik bir güvenlik payı eklendi (normal şartlarda hiçbir zaman bu kadar uzun olmaz, sadece uç durumlara karşı önlem).

## 38. Google Sheets geçici hatalarında (503) otomatik tekrar deneme

- **Sorun (senin bildirdiğin):** "⚠️ Bot hatası (reminder_worker) - APIError: [503] The service is currently unavailable." bildirimi geldi.
- **Açıklama:** Bu hata bot kodundan değil, Google Sheets sunucusundan geçici bir yoğunluk/bakım anında geliyor - nadiren olur, birkaç saniye içinde kendiliğinden düzelir. Önceki tasarımda bot bunu hemen "hata" sayıp sana bildirim gönderiyor ve o turu atlıyordu.
- **Düzeltme:** Artık Sheets'ten veri okurken 500/502/503/504 gibi geçici hatalarla karşılaşılırsa bot kısa bir bekleme ile (1.5, 3 saniye) otomatik olarak birkaç kez tekrar deniyor - genelde ikinci denemede sorun kendiliğinden düzeliyor ve sana hiç bildirim gitmiyor. Sorun gerçekten kalıcıysa (3 denemeden sonra hâlâ başarısızsa) eskisi gibi "Bot hatası" bildirimi gelmeye devam ediyor - bu güvenlik ağı kaldırılmadı.

## Render'a Artık Gerekmeyen Değişken

- `PERENUAL_API_KEY` ve `PERENUAL_IDENTIFY_API_KEY` artık hiçbir yerde kullanılmıyor (Bakım Bilgisi/Bitki Ara kaldırıldığı için). Render'da tanımlıysa durmasının bir zararı yok, silmek istersen silebilirsin, zorunlu değil.

Diğer tüm değişiklikler (hatırlatma sınırları, kritik stok bildirimi, AI kayıt sorgusu, performans iyileştirmeleri, hava durumu entegrasyonu, haftalık yedekleme) mevcut environment değişkenlerinle otomatik çalışır, ek bir şey eklemene gerek yok.

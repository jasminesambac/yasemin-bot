# Yasemin Telegram Bot

Bu sürüm PDF'deki kırık kodu kopyalamak yerine temiz bir `bot.py` olarak yeniden kuruldu.

## Gerekli ayarlar

Railway veya lokal ortam değişkenleri:

- `TELEGRAM_BOT_TOKEN`
- `SHEET_ID`
- `GOOGLE_SHEETS_CREDENTIALS`
- `AGNES_API_KEY` isteğe bağlıdır. AI Sor için gerekir.

Google Sheet içinde şu sayfalar yoksa bot ilk açılışta oluşturur:

- `inventory`
- `history`
- `ph_records`
- `reminders`

## Çalıştırma

```bash
pip install -r requirements.txt
python bot.py
```

Railway için `Procfile` hazırdır.

## Notlar

- Tarihler ekranda `14-06-2026` formatında gösterilir.
- Bot `14-06-2026`, `2026-06-14`, `14/06/2026` ve `14.06.2026` formatlarını anlar.
- Uzun listeler Telegram sınırına takılmaması için parçalara bölünür.
- Stoktan düşme ve Geçmiş > İşlem Ekle işlemleri stok miktarını otomatik azaltır.

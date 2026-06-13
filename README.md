# shortvideodownloader.com — Faz 1

Tek sayfa, güvenlik öncelikli video indirme sitesi. Şu an çalışan:
**canlı link doğrulama katmanı + video bilgisi + gerçek indirme (MP4/MP3)
+ otomatik dosya silme + güven veren arayüz.**

## Çalıştırma (local)

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# tarayıcı: http://127.0.0.1:8000
```

## Testler

```bash
pip install -r requirements-dev.txt
python -m pytest -v
```

## Güvenlik katmanı (app/validator.py)

Her URL motora ulaşmadan 8 süzgeçten geçer:

| # | Kontrol | Engellediği şey |
|---|---|---|
| 1 | Girdi temizliği | boş, aşırı uzun, kontrol karakteri, %0d%0a (CRLF) enjeksiyonu |
| 2 | Şema | `javascript:`, `data:`, `file:`, `ftp:` |
| 3 | Kimlik hilesi | `youtube.com@kotu-site.com` tarzı gizlenmiş adres |
| 4 | SSRF | IP adresi, `localhost`, `.internal/.local/.lan` iç ağ adresleri |
| 5 | Port | standart dışı portlar (örn. `:8443`) |
| 6 | Domain allowlist | sahte/benzer domainler (`evil-youtube.com`, punycode homograph) |
| 7 | Video yolu deseni | ana sayfa, profil, arama linkleri (kaynak israfı + saçma girdi) |
| 8 | Normalizasyon | takip (`utm_*`, `si`, `fbclid`...) ve playlist parametreleri |

API katmanında ek olarak: sıkı CSP + güvenlik başlıkları, kapalı API
dokümantasyonu, IP başına rate limit (doğrulama 30/dk, bilgi 10/dk).
Arayüzde: API verisi asla `innerHTML` ile basılmaz (XSS hijyeni), kapak
görseli yalnızca `https://` ise gösterilir, dış kaynak (font/ikon/CDN) yok.

## Yapı

```
app/
  main.py        FastAPI: endpoint'ler, güvenlik başlıkları, rate limit
  validator.py   Link güvenlik katmanı (8 kontrol)
  downloader.py  yt-dlp sarmalayıcı (bilgi çekme + indirme + otomatik temizlik)
  static/        index.html + style.css + app.js (tek sayfa arayüz)
tests/           validator saldırı testleri + API testleri
```

## İndirme güvenliği (yeni)

Format kimliği sıkı allowlist (mp3 | mp4-yükseklik), 2 GB dosya ve 3 saat
süre limiti, canlı yayın reddi, eşzamanlı indirme sınırı (3 slot),
IP başına 5 indirme/dk, izole iş klasörü → yanıt biter bitmez silinir,
1 saatten eski artıklar otomatik süpürülür, dosya adı sanitizasyonu
(RFC 5987 UTF-8 + ASCII fallback). MP3 ve kalite birleştirme için
sunucuda ffmpeg gerekir.

## Sonraki fazlar

1. Docker + Caddy (otomatik HTTPS) + Cloudflare → yayına alma
2. Gizlilik Politikası / Kullanım Şartları / Telif (DMCA) sayfaları
3. Tasarım cilası (logo, animasyonlar, koyu tema)

Üretim notu: yt-dlp'yi izole bir container'da, kısıtlı kaynak ve egress
kurallarıyla çalıştırın; yt-dlp güncel tutulmalı (platform değişiklikleri).

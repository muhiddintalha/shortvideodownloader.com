# Tarayıcıda Çalıştırma (Windows)

## En kolay yol

1. Bilgisayarında Python yüklü değilse: https://www.python.org/downloads/
   → kurulumda **"Add Python to PATH"** kutusunu işaretle.
2. `shortvideodownloader` klasöründeki **`baslat.bat`** dosyasına çift tıkla.
   - İlk çalıştırma 1-2 dk sürer (sanal ortam + paketler kurulur).
   - Tarayıcı otomatik açılır: **http://127.0.0.1:8000**
3. Kapatmak için açılan siyah pencerede `Ctrl+C` ya da pencereyi kapat.

## MP3 ve yüksek kalite birleştirme (isteğe bağlı)

MP4 indirme ffmpeg'siz de çalışır; **MP3** ve **1080p video+ses birleştirme**
için ffmpeg gerekir. PowerShell'de:

```powershell
winget install ffmpeg
```

Kurulumdan sonra `baslat.bat`'ı yeniden başlat.

## Test listesi (tarayıcıda sırayla dene)

| # | Deneme | Beklenen |
|---|---|---|
| 1 | Bir YouTube Shorts linki yapıştır | Yeşil "✓ YouTube bağlantısı doğrulandı" |
| 2 | Devam'a bas | Kapak + başlık + kalite butonları |
| 3 | MP4 butonuna bas | Dosya tarayıcının indirme listesine düşer |
| 4 | `https://evil-youtube.com/watch?v=x12345` yapıştır | Kırmızı "desteklenmiyor" uyarısı |
| 5 | `youtube.com` (ana sayfa) yapıştır | "video bağlantısına benzemiyor" uyarısı |
| 6 | Bir TikTok / Instagram Reels / X linki | Doğrulanır → indirilir |

Not: Instagram ve X bazı videolar için giriş (cookie) isteyebilir — bu hatayı
görürsen not al, çözümünü bir sonraki fazda ekleyeceğiz.

## Sorun çıkarsa

- "Python bulunamadı" → Python'u PATH ile kur, bilgisayarı yeniden başlat.
- Sayfa açılmıyor → siyah penceredeki hata satırını kopyala, bana gönder.
- Port doluysa → `baslat.bat` içindeki `8000`'i `8080` yap.

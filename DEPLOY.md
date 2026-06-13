# Deployment Guide — shortvideodownloader.com

Domain gelince (~15 Haziran) bu adımları sırayla uygula.
Toplam süre: ~30 dakika.

---

## Gereksinimler

- Ubuntu 22.04 LTS VPS (Hetzner CX22 veya DigitalOcean Basic — €5/ay)
- shortvideodownloader.com domaini (Cloudflare üzerinde)
- Yerel makinede: SSH erişimi

---

## Adım 1 — VPS Kur (ilk kez)

SSH ile bağlan:
```bash
ssh root@<VPS_IP>
```

Temel güvenlik + Docker kur:
```bash
# Güncellemeler
apt update && apt upgrade -y

# Firewall: sadece SSH + HTTP + HTTPS
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw enable

# Docker
curl -fsSL https://get.docker.com | sh

# docker compose plugin (v2)
apt install -y docker-compose-plugin

# Servisi başlat
systemctl enable docker && systemctl start docker
```

---

## Adım 2 — DNS (Cloudflare)

Cloudflare panelinde shortvideodownloader.com için:

| Type | Name | Content         | Proxy |
|------|------|-----------------|-------|
| A    | @    | `<VPS_IP>`      | ✅ Proxied |
| A    | www  | `<VPS_IP>`      | ✅ Proxied |

> **Önemli:** Cloudflare SSL/TLS ayarını **"Full (strict)"** yap.  
> (SSL/TLS → Overview → Full (strict))

DNS propagasyonunu kontrol et:
```bash
# Yerel makinende çalıştır
nslookup shortvideodownloader.com
```

---

## Adım 3 — Projeyi VPS'e Aktar

Yerel makinenden VPS'e kopyala:
```bash
# shortvideodownloader klasörünün bir üst dizininde çalıştır
scp -r shortvideodownloader root@<VPS_IP>:/opt/svd
```

Ya da Git kullanıyorsan:
```bash
# VPS üzerinde
git clone <repo_url> /opt/svd
```

---

## Adım 4 — Canlıya Al

VPS üzerinde:
```bash
cd /opt/svd

# Gerekirse .env dosyası oluştur
cp .env.example .env

# Build + başlat (ilk seferinde biraz uzun sürer — ffmpeg indirir)
docker compose up -d --build

# Logları izle
docker compose logs -f
```

Birkaç saniye bekle, sonra test et:
```bash
curl https://shortvideodownloader.com/healthz
# {"ok":true} görmen gerekiyor
```

---

## Adım 5 — SSL Kontrolü

Caddy otomatik olarak Let's Encrypt'ten sertifika alır.
Cloudflare → SSL/TLS → Overview → "Full (strict)" ayarlandıysa her şey çalışır.

Tarayıcıda `https://shortvideodownloader.com` aç — kilit ikonu görünmeli.

---

## Güncelleme (sonraki sürümler)

Yeni kod VPS'e aktarıldıktan sonra:
```bash
cd /opt/svd
docker compose up -d --build
```

Eski container otomatik durur, yeni container ayağa kalkar. Downtime yok.

---

## yt-dlp Güncelleme (önemli!)

Platformlar sık değişir. Haftada bir çalıştır:
```bash
docker compose exec app pip install --upgrade yt-dlp
docker compose restart app
```

Ya da cron'a ekle (VPS üzerinde `crontab -e`):
```
0 4 * * 1 cd /opt/svd && docker compose exec -T app pip install --upgrade yt-dlp && docker compose restart app
```

---

## Yararlı Komutlar

```bash
# Servislerin durumu
docker compose ps

# Uygulama logları (canlı)
docker compose logs -f app

# Caddy logları
docker compose logs -f caddy

# Tüm sistemi durdur
docker compose down

# Disk temizliği (eski image'lar)
docker system prune -f
```

---

## Sonraki Adımlar (isteğe bağlı)

- [ ] Sentry ile hata izleme ekle (ücretsiz plan yeter)
- [ ] HSTS preload listesine ekle (hstspreload.org) — 2-3 ay sonra
- [ ] SEO: sitemap.xml, robots.txt

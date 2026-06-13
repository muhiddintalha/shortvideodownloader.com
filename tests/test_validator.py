"""Link güvenlik katmanı testleri — saldırı senaryoları dahil."""

import pytest

from app.validator import validate

# ---------------------------------------------------------- geçerli bağlantılar
VALID = [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "YouTube"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "YouTube"),
    ("https://www.youtube.com/shorts/abc123XYZ_-", "YouTube"),
    ("https://youtu.be/dQw4w9WgXcQ?si=takip_kodu", "YouTube"),
    ("youtube.com/watch?v=dQw4w9WgXcQ", "YouTube"),            # şemasız
    ("HTTP://WWW.YOUTUBE.COM/WATCH?v=dQw4w9WgXcQ", "YouTube"), # büyük harf + http
    ("https://www.instagram.com/reel/Cxyz_1234/", "Instagram"),
    ("https://www.instagram.com/p/Cabc-999/?igsh=xxx", "Instagram"),
    ("https://www.tiktok.com/@kullanici.adi/video/7300000000000000000", "TikTok"),
    ("https://vm.tiktok.com/ZMabcdef", "TikTok"),
    ("https://x.com/kullanici/status/1790000000000000000", "X (Twitter)"),
    ("https://twitter.com/kullanici/status/1790000000000000000", "X (Twitter)"),
    ("https://www.facebook.com/watch?v=123456789", "Facebook"),
    ("https://fb.watch/abcDE-12", "Facebook"),
    ("https://vimeo.com/123456789", "Vimeo"),
    ("https://www.dailymotion.com/video/x8abcd1", "Dailymotion"),
    ("https://www.reddit.com/r/videos/comments/abc123/baslik_yazisi/", "Reddit"),
    ("https://www.twitch.tv/videos/2200000000", "Twitch"),
    ("https://clips.twitch.tv/CleverClipSlug-x1_Y2", "Twitch"),
]


@pytest.mark.parametrize("url,platform", VALID)
def test_gecerli_linkler_kabul_edilir(url, platform):
    r = validate(url)
    assert r.valid, f"{url} reddedildi: {r.message}"
    assert r.platform == platform
    assert r.normalized_url.startswith("https://")


# ------------------------------------------------------ saldırı / kötü girdiler
ATTACKS = [
    # şema hileleri
    ("javascript:alert(1)", "bad_scheme"),
    ("data:text/html;base64,PHNjcmlwdD4=", "bad_scheme"),
    ("file:///etc/passwd", "bad_scheme"),
    ("ftp://youtube.com/watch?v=abc123", "bad_scheme"),
    # gizlenmiş adres
    ("https://youtube.com@kotu-site.com/watch?v=abc123", "credentials"),
    # SSRF denemeleri
    ("https://192.168.1.1/video", "ip_host"),
    ("https://127.0.0.1/watch?v=abc123", "ip_host"),
    ("https://[::1]/video", "ip_host"),
    ("https://localhost/watch", "internal_host"),
    ("https://sunucu.internal/video", "internal_host"),
    # port hilesi
    ("https://youtube.com:8443/watch?v=abc123", "bad_port"),
    # sahte / benzer domainler
    ("https://evil-youtube.com/watch?v=abc123", "unsupported"),
    ("https://youtube.com.kotu-site.com/watch?v=abc123", "unsupported"),
    ("https://xn--youtub-9ta.com/watch?v=abc123", "unsupported"),   # punycode homograph
    ("https://rastgele-site.xyz/video.mp4", "unsupported"),
    # her yere yönlenebilen kısaltıcı bilinçli olarak desteklenmiyor
    ("https://t.co/abc123XYZ", "unsupported"),
    # bozuk karakterler / enjeksiyon
    ("https://youtube.com/watch?v=abc 123", "bad_chars"),
    ("https://youtube.com/watch?v=abc%0d%0aSet-Cookie:x", "bad_chars"),
    ("https://youtube.com\\watch?v=abc123", "bad_chars"),
]


@pytest.mark.parametrize("url,code", ATTACKS)
def test_saldiri_senaryolari_reddedilir(url, code):
    r = validate(url)
    assert not r.valid, f"{url} kabul EDİLMEMELİYDİ"
    assert r.code == code, f"{url}: beklenen {code}, gelen {r.code}"


# --------------------------------------------------- video olmayan sayfa linkleri
NOT_VIDEO = [
    "https://www.youtube.com",                       # ana sayfa
    "https://www.youtube.com/@KanalAdi",             # profil
    "https://www.youtube.com/watch",                 # v parametresi yok
    "https://www.youtube.com/results?search_query=kedi",
    "https://www.instagram.com/kullanici_adi/",      # profil
    "https://x.com/kullanici",                       # profil
    "https://www.tiktok.com/@kullanici",             # profil
]


@pytest.mark.parametrize("url", NOT_VIDEO)
def test_video_olmayan_linkler_reddedilir(url):
    r = validate(url)
    assert not r.valid, f"{url} video değil, kabul edilmemeliydi"
    assert r.code == "not_video"


# ------------------------------------------------------------- sınır durumları
def test_bos_girdi():
    assert validate("").code == "empty"
    assert validate("   ").code == "empty"
    assert validate(None).code == "empty"


def test_cok_uzun_girdi():
    url = "https://youtube.com/watch?v=" + "a" * 3000
    assert validate(url).code == "too_long"


# ------------------------------------------------------------- normalizasyon
def test_takip_parametreleri_temizlenir():
    r = validate("https://www.youtube.com/watch?v=dQw4w9WgXcQ&utm_source=x&si=abc&feature=share")
    assert r.valid
    assert "utm_source" not in r.normalized_url
    assert "si=" not in r.normalized_url
    assert "feature" not in r.normalized_url
    assert "v=dQw4w9WgXcQ" in r.normalized_url


def test_playlist_parametresi_atilir():
    r = validate("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxyz&index=5")
    assert r.valid
    assert "list=" not in r.normalized_url


def test_http_https_e_zorlanir():
    r = validate("http://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert r.valid
    assert r.normalized_url.startswith("https://")

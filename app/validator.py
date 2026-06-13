"""
Link Güvenlik Katmanı — shortvideodownloader.com

Her URL, indirme motoruna ulaşmadan önce bu süzgeçten geçer.
Kontroller (sırayla):

1. Boş / aşırı uzun / kontrol karakterli ya da kodlanmış kontrol karakterli girdi
2. Şema kontrolü: yalnızca http/https (javascript:, data:, file: vb. reddedilir)
3. URL içine gizlenmiş kullanıcı adı/parola hilesi (örn. youtube.com@kotu-site.com)
4. IP adresi, localhost ve iç ağ adresleri (SSRF koruması)
5. Standart dışı port
6. Domain allowlist: yalnızca tanıdığımız platformlar.
   Eşleşme tam domain ya da ".domain" son ekiyle yapılır; böylece
   "evil-youtube.com" veya "youtube.com.evil.com" geçemez.
   Punycode/homograph (benzer görünümlü) domainler allowlist ASCII olduğu
   için otomatik elenir.
7. Yol (path) kontrolü: gerçekten bir VİDEO bağlantısı mı?
   Ana sayfa / profil / rastgele sayfa linkleri reddedilir.
8. Normalizasyon: https'e zorlanır, takip parametreleri (utm_*, fbclid,
   si, igsh...) ve playlist parametreleri temizlenir.

Not: t.co gibi "her yere yönlenebilen" kısaltıcılar bilinçli olarak
allowlist'te YOKTUR.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import asdict, dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_URL_LENGTH = 2048

# ---------------------------------------------------------------- platformlar
# domain -> kullanıcıya gösterilecek platform adı
PLATFORMS: dict[str, str] = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "instagram.com": "Instagram",
    "tiktok.com": "TikTok",
    "x.com": "X (Twitter)",
    "twitter.com": "X (Twitter)",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "vimeo.com": "Vimeo",
    "dailymotion.com": "Dailymotion",
    "dai.ly": "Dailymotion",
    "reddit.com": "Reddit",
    "twitch.tv": "Twitch",
}

# Domain başına "bu bir video linki" sayılan yol desenleri.
# Amaç: ana sayfa, profil, arama sayfası gibi linkleri motora hiç sokmamak.
_PATTERNS: dict[str, list[str]] = {
    "youtube.com": [
        r"^/watch$",                  # ?v=ID zorunluluğu QUERY_REQUIRED ile
        r"^/shorts/[\w-]{6,}$",
        r"^/embed/[\w-]{6,}$",
        r"^/live/[\w-]{6,}$",
        r"^/clip/[\w-]{6,}$",
    ],
    "youtu.be": [r"^/[\w-]{6,}$"],
    "instagram.com": [
        r"^/(p|reel|reels|tv)/[\w-]{5,}$",
        r"^/share/(p|reel|reels)/[\w-]{5,}$",
        r"^/stories/[\w.\-]+/\d+$",
    ],
    "tiktok.com": [
        r"^/@[\w.\-]+/video/\d+$",
        r"^/@[\w.\-]+/photo/\d+$",
        r"^/t/[\w-]{5,}$",
        r"^/v/\d+$",
        r"^/[A-Za-z0-9]{6,12}$",      # vm.tiktok.com/KOD kısa linkleri
    ],
    "x.com": [r"^/\w+/status/\d+$"],
    "twitter.com": [r"^/\w+/status/\d+$"],
    "facebook.com": [
        r"^/watch$",                  # ?v=ID zorunlu
        r"^/reel/\d+$",
        r"^/share/[vr]/[\w-]+$",
        r"^/[\w.\-]+/videos/\d+$",
    ],
    "fb.watch": [r"^/[\w-]{5,}$"],
    "vimeo.com": [r"^/\d{6,}$", r"^/video/\d{6,}$", r"^/channels/\w+/\d{6,}$"],
    "dailymotion.com": [r"^/video/[\w]{5,}$"],
    "dai.ly": [r"^/[\w]{5,}$"],
    "reddit.com": [
        r"^/r/\w+/comments/\w+(/[\w%\-]*)*$",
        r"^/r/\w+/s/\w+$",
        r"^/video/\w+$",
    ],
    "twitch.tv": [
        r"^/videos/\d+$",
        r"^/\w+/clip/[\w-]+$",
        r"^/[\w-]{5,}$",              # clips.twitch.tv/Slug
    ],
}
_COMPILED = {d: [re.compile(p, re.ASCII | re.IGNORECASE) for p in pats]
             for d, pats in _PATTERNS.items()}

# (domain, yol) -> zorunlu query parametresi ve deseni
QUERY_REQUIRED: dict[tuple[str, str], tuple[str, re.Pattern]] = {
    ("youtube.com", "/watch"): ("v", re.compile(r"^[\w-]{6,}$", re.ASCII)),
    ("facebook.com", "/watch"): ("v", re.compile(r"^\d{5,}$", re.ASCII)),
}

# Normalizasyonda atılan takip/playlist parametreleri
_TRACKING_PREFIXES = ("utm_",)
_DROP_PARAMS = {
    "fbclid", "gclid", "igsh", "igshid", "si", "feature", "ref", "ref_src",
    "ref_url", "mibextid", "rdid", "share_id", "s", "t",
    "list", "index", "pp", "ab_channel", "start_radio",
}

# %00–%1F gibi kodlanmış kontrol karakterleri (CRLF enjeksiyonu vb.)
_ENCODED_CTRL = re.compile(r"%(?:0[0-9a-fA-F]|1[0-9a-fA-F])")

_INTERNAL_SUFFIXES = (".local", ".internal", ".lan", ".home", ".localhost")


# ------------------------------------------------------------------- sonuç
@dataclass
class ValidationResult:
    valid: bool
    code: str
    message: str
    platform: str | None = None
    normalized_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _reject(code: str, message: str) -> ValidationResult:
    return ValidationResult(False, code, message)


def _match_domain(host: str) -> tuple[str | None, str | None]:
    for domain, platform in PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return domain, platform
    return None, None


_SUPPORTED_TEXT = "YouTube, Instagram, TikTok, X, Facebook, Vimeo, Reddit, Twitch ve Dailymotion"


# ----------------------------------------------------------------- doğrulama
def validate(raw: str | None) -> ValidationResult:
    # 1) temel girdi kontrolleri
    if raw is None or not isinstance(raw, str) or not raw.strip():
        return _reject("empty", "Lütfen bir video bağlantısı girin.")
    url = raw.strip()

    if len(url) > MAX_URL_LENGTH:
        return _reject("too_long", "Bağlantı çok uzun. Lütfen videonun kendi bağlantısını yapıştırın.")

    if any(ord(c) < 33 for c in url) or "\\" in url:
        return _reject("bad_chars", "Bağlantı geçersiz karakterler içeriyor.")
    if _ENCODED_CTRL.search(url):
        return _reject("bad_chars", "Bağlantı geçersiz karakterler içeriyor.")

    # 2) şema
    if "://" not in url:
        if re.match(r"^[a-z][a-z0-9+.\-]*:", url, re.IGNORECASE):
            # javascript:, data:, mailto: gibi şemalar
            return _reject("bad_scheme", "Yalnızca http/https bağlantıları kabul edilir.")
        url = "https://" + url  # şemasız yapıştırmaları kabul et

    try:
        parts = urlsplit(url)
    except ValueError:
        return _reject("parse_error", "Bağlantı çözümlenemedi. Lütfen kontrol edip tekrar deneyin.")

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return _reject("bad_scheme", "Yalnızca http/https bağlantıları kabul edilir.")

    # 3) gizlenmiş kimlik bilgisi (user@host)
    if "@" in parts.netloc:
        return _reject("credentials", "Bu bağlantı güvenlik nedeniyle reddedildi (gizlenmiş adres içeriyor).")

    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return _reject("no_host", "Bağlantıda geçerli bir adres bulunamadı.")
    try:
        host.encode("ascii")
    except UnicodeEncodeError:
        return _reject("bad_host", "Bağlantıdaki alan adı desteklenmiyor.")

    # 4) IP / localhost / iç ağ (SSRF koruması)
    try:
        ipaddress.ip_address(host)
        return _reject("ip_host", "Güvenlik nedeniyle IP adresli bağlantılar kabul edilmez.")
    except ValueError:
        pass
    if host == "localhost" or host.endswith(_INTERNAL_SUFFIXES):
        return _reject("internal_host", "Bu bağlantı güvenlik nedeniyle reddedildi.")

    # 5) port
    try:
        port = parts.port
    except ValueError:
        return _reject("bad_port", "Bağlantı geçersiz bir port içeriyor.")
    if port not in (None, 80, 443):
        return _reject("bad_port", "Standart dışı portlu bağlantılar kabul edilmez.")

    # 6) domain allowlist
    domain, platform = _match_domain(host)
    if domain is None:
        return _reject(
            "unsupported",
            f"Bu site desteklenmiyor veya bağlantı güvenli görünmüyor. Desteklenenler: {_SUPPORTED_TEXT}.",
        )

    # 7) video yolu kontrolü
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"

    path_ok = any(p.match(path) for p in _COMPILED[domain])
    required = QUERY_REQUIRED.get((domain, path.lower()))
    params = dict(parse_qsl(parts.query, keep_blank_values=False))
    if required is not None:
        name, pattern = required
        path_ok = name in params and bool(pattern.match(params[name]))

    if not path_ok:
        return _reject(
            "not_video",
            f"Bu bir {platform} video bağlantısına benzemiyor. "
            "Lütfen videonun kendi bağlantısını yapıştırın (ana sayfa veya profil linki değil).",
        )

    # 8) normalizasyon
    clean_query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in _DROP_PARAMS
        and not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    normalized = urlunsplit(("https", host, path, urlencode(clean_query), ""))

    return ValidationResult(
        valid=True,
        code="ok",
        message=f"{platform} bağlantısı doğrulandı.",
        platform=platform,
        normalized_url=normalized,
    )

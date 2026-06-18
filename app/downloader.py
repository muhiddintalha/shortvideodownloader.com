"""
yt-dlp sarmalayıcı — buraya YALNIZCA validator'dan geçmiş URL'ler ulaşır.

Güvenlik sınırları:
- noplaylist: tek video; playlist'le sunucuyu meşgul etme saldırısı engellenir
- socket_timeout: takılı kalan bağlantılar koparılır
- süre limiti: aşırı uzun videolar reddedilir (kaynak tüketimi)
- canlı yayın reddedilir (sonsuz indirme)
- dosya boyutu limiti: max_filesize aşılırsa indirme iptal
- format kimliği sıkı allowlist'ten geçer (mp3 | mp4-<yükseklik>)
- her indirme kendi izole geçici klasöründe yapılır; iş bitince klasör silinir
- bayat klasörler süpürülür (1 saatten eski her şey)
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time

MAX_DURATION_SECONDS = 3 * 60 * 60   # 3 saat
SOCKET_TIMEOUT = 15
MAX_FILESIZE = 2 * 1024 ** 3          # 2 GB
STALE_AGE_SECONDS = 60 * 60           # 1 saat: bayat dosya süpürme eşiği

DOWNLOAD_ROOT = os.path.join(tempfile.gettempdir(), "svd-downloads")

# Format kimliği allowlist'i: mp3 ya da mp4-144..4320
_FORMAT_ID = re.compile(r"^(?:mp3|mp4-(\d{3,4}))$", re.ASCII)


class DownloaderError(Exception):
    """Kullanıcıya gösterilebilir, anlaşılır hata."""


def _friendly(raw: str) -> str:
    low = raw.lower()
    if "private" in low or "login" in low or "sign in" in low:
        return "Bu video gizli veya giriş gerektiriyor; indirilemez."
    if "age" in low:
        return "Bu video yaş sınırlı olduğu için indirilemiyor."
    if "unavailable" in low or "removed" in low or "not exist" in low or "404" in low:
        return "Video bulunamadı. Kaldırılmış veya bağlantı hatalı olabilir."
    if "geo" in low or "country" in low:
        return "Bu video bölgenizde kullanılamıyor."
    if "timed out" in low or "timeout" in low:
        return "Platforma ulaşılamadı. Lütfen tekrar deneyin."
    return "Video bilgisi alınamadı. Bağlantıyı kontrol edip tekrar deneyin."


def _simplify_formats(info: dict) -> list[dict]:
    """Kullanıcıyı codec ormanında bırakma: sade, net seçenekler sun."""
    heights = sorted({
        f.get("height") for f in info.get("formats", [])
        if f.get("height") and f.get("vcodec") not in (None, "none")
    })
    options: list[dict] = []
    for h in (360, 720, 1080):
        if any(x >= h for x in heights):
            options.append({"id": f"mp4-{h}", "label": f"MP4 · {h}p"})
    if not options and heights:  # standart yükseklik yoksa en iyisini sun
        options.append({"id": f"mp4-{heights[-1]}", "label": f"MP4 · {heights[-1]}p"})
    options.append({"id": "mp3", "label": "MP3 · yalnızca ses"})
    return options


def get_info(url: str) -> dict:
    try:
        import yt_dlp
    except ImportError as exc:
        raise DownloaderError(
            "İndirme motoru bu kurulumda henüz etkin değil (pip install yt-dlp)."
        ) from exc

    opts = {
        "noplaylist": True,
        "playlist_items": "1",
        "skip_download": True,
        "socket_timeout": SOCKET_TIMEOUT,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloaderError(_friendly(str(exc))) from exc

    if info is None:
        raise DownloaderError(_friendly("unavailable"))
    if info.get("_type") == "playlist":  # her ihtimale karşı
        entries = info.get("entries") or []
        if not entries:
            raise DownloaderError(_friendly("unavailable"))
        info = entries[0]
    if info.get("is_live"):
        raise DownloaderError("Canlı yayınlar indirilemez.")
    duration = int(info.get("duration") or 0)
    if duration > MAX_DURATION_SECONDS:
        raise DownloaderError("Video çok uzun (sınır: 3 saat).")

    thumbnail = info.get("thumbnail")
    if not (isinstance(thumbnail, str) and thumbnail.startswith("https://")):
        thumbnail = None  # http veya tuhaf bir şeyse hiç gösterme

    return {
        "title": info.get("title") or "Video",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": duration,
        "thumbnail": thumbnail,
        "formats": _simplify_formats(info),
    }


# ====================================================================== indirme

def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _safe_filename(name: str, max_len: int = 120) -> str:
    """Dosya adından tehlikeli/sorunlu karakterleri ayıkla."""
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r'[\\/:*?"<>|]', " ", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name[:max_len].rstrip(" .") or "video"


def _format_selector(format_id: str) -> tuple:
    """Format kimliğini yt-dlp seçicisine çevir.
    Dönüş: (hata_mesajı | None, ek yt-dlp ayarları)"""
    m = _FORMAT_ID.match(format_id or "")
    if not m:
        return "Geçersiz format seçimi.", {}

    if format_id == "mp3":
        if not _has_ffmpeg():
            return "MP3 dönüştürme bu sunucuda henüz etkin değil.", {}
        return None, {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

    height = int(m.group(1))
    if not 144 <= height <= 4320:
        return "Geçersiz format seçimi.", {}
    if _has_ffmpeg():
        fmt = (
            f"bestvideo[height<={height}][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/best[height<={height}][ext=mp4]"
            f"/best[height<={height}]/best"
        )
        return None, {"format": fmt, "merge_output_format": "mp4"}
    fmt = f"best[height<={height}][ext=mp4]/best[height<={height}]/best"
    return None, {"format": fmt}


def sweep_stale(root: str = DOWNLOAD_ROOT, max_age: int = STALE_AGE_SECONDS) -> int:
    """1 saatten eski indirme klasörlerini sil (çökme/yarıda kalma artıkları)."""
    removed = 0
    if not os.path.isdir(root):
        return removed
    now = time.time()
    for entry in os.scandir(root):
        try:
            if entry.is_dir() and now - entry.stat().st_mtime > max_age:
                shutil.rmtree(entry.path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _find_output(job_dir: str, info: dict):
    """İndirilen dosyayı bul: önce yt-dlp'nin bildirdiği yol, yoksa en büyük dosya."""
    for d in info.get("requested_downloads") or []:
        path = d.get("filepath")
        if path and os.path.isfile(path):
            return path
    candidates = [
        os.path.join(job_dir, f) for f in os.listdir(job_dir)
        if os.path.isfile(os.path.join(job_dir, f)) and not f.endswith(".part")
    ]
    return max(candidates, key=os.path.getsize) if candidates else None


def download_video(url: str, format_id: str) -> tuple:
    """Doğrulanmış URL'yi indirir.
    Dönüş: (dosya_yolu, kullanıcıya_önerilecek_ad, silinecek_iş_klasörü)"""
    try:
        import yt_dlp
    except ImportError as exc:
        raise DownloaderError(
            "İndirme motoru bu kurulumda henüz etkin değil (pip install yt-dlp)."
        ) from exc

    err, extra = _format_selector(format_id)
    if err:
        raise DownloaderError(err)

    def _duration_filter(info, *, incomplete=False):
        dur = info.get("duration")
        if dur and dur > MAX_DURATION_SECONDS:
            return "Video çok uzun"
        if info.get("is_live"):
            return "Canlı yayın"
        return None

    sweep_stale()
    os.makedirs(DOWNLOAD_ROOT, exist_ok=True)
    job_dir = tempfile.mkdtemp(prefix="svd-", dir=DOWNLOAD_ROOT)

    opts = {
        "noplaylist": True,
        "playlist_items": "1",
        "socket_timeout": SOCKET_TIMEOUT,
        "retries": 2,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_FILESIZE,
        "outtmpl": os.path.join(job_dir, "%(id)s.%(ext)s"),
        "match_filter": _duration_filter,
    }
    opts.update(extra)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise DownloaderError(_friendly(str(exc))) from exc
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise

    if info is None:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise DownloaderError(_friendly("unavailable"))
    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        info = entries[0] if entries else {}

    duration = int(info.get("duration") or 0)
    if duration > MAX_DURATION_SECONDS:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise DownloaderError("Video çok uzun (sınır: 3 saat).")

    path = _find_output(job_dir, info)
    if path is None:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise DownloaderError(
            "Dosya hazırlanamadı. Video çok büyük veya canlı yayın olabilir."
        )

    ext = os.path.splitext(path)[1].lstrip(".") or ("mp3" if format_id == "mp3" else "mp4")
    suggested = f"{_safe_filename(info.get('title') or 'video')}.{ext}"
    return path, suggested, job_dir

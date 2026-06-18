"""
shortvideodownloader.com — FastAPI uygulaması

Güvenlik önlemleri:
- Tüm yanıtlara sıkı güvenlik başlıkları (CSP, nosniff, frame yasağı...)
- API dokümantasyonu kapalı (saldırı yüzeyini küçült)
- IP başına basit rate limit (üretimde önüne Cloudflare + Caddy da gelecek)
- Her URL önce validator'dan geçer; motor doğrulanmamış URL görmez
- Eşzamanlı indirme sınırı (semafor) — kaynak tüketimi saldırısına karşı
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware

from .validator import MAX_URL_LENGTH, validate

BASE_DIR = Path(__file__).resolve().parent

# Aynı anda en fazla bu kadar indirme çalışır; fazlası kibarca reddedilir.
MAX_CONCURRENT_DOWNLOADS = 3
_DL_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_DOWNLOADS)

app = FastAPI(
    title="ShortVideoDownloader",
    docs_url=None, redoc_url=None, openapi_url=None,  # docs kapalı
)

# ----------------------------------------------------------- güvenlik başlıkları
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com; "
        "style-src 'self'; "
        "img-src 'self' https: data:; "
        "connect-src 'self' https://www.google-analytics.com https://analytics.google.com; "
        "font-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    # HSTS, HTTPS yayına alınınca Caddy tarafından eklenecek
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ----------------------------------------------------------------- rate limit
_BUCKETS: dict = {}
_LOCK = threading.Lock()


def _allow(ip: str, bucket: str, limit: int, window: float = 60.0) -> bool:
    now = time.monotonic()
    key = (ip, bucket)
    with _LOCK:
        stamps = [t for t in _BUCKETS.get(key, []) if now - t < window]
        if len(stamps) >= limit:
            _BUCKETS[key] = stamps
            return False
        stamps.append(now)
        _BUCKETS[key] = stamps
        return True


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limited() -> JSONResponse:
    return JSONResponse(
        {"valid": False, "code": "rate_limited",
         "message": "Çok fazla deneme yapıldı. Lütfen bir dakika sonra tekrar deneyin."},
        status_code=429,
    )


# ------------------------------------------------------------------- modeller
class UrlIn(BaseModel):
    url: str = Field(..., max_length=MAX_URL_LENGTH * 8)


@app.exception_handler(RequestValidationError)
async def bad_body(request: Request, exc: RequestValidationError):
    return JSONResponse(
        {"valid": False, "code": "bad_request", "message": "Geçersiz istek."},
        status_code=400,
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return FileResponse(BASE_DIR / "static" / "404.html", status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ------------------------------------------------------------------ endpoints
@app.post("/api/validate")
async def api_validate(body: UrlIn, request: Request):
    """Hafif uç nokta: kullanıcı yazarken canlı doğrulama için."""
    if not _allow(_client_ip(request), "validate", limit=30):
        return _rate_limited()
    return validate(body.url).to_dict()


@app.post("/api/info")
async def api_info(body: UrlIn, request: Request):
    """Doğrulama + yt-dlp ile video bilgisi (başlık, kapak, formatlar)."""
    if not _allow(_client_ip(request), "info", limit=10):
        return _rate_limited()

    result = validate(body.url)
    if not result.valid:
        return JSONResponse(result.to_dict(), status_code=400)

    from .downloader import DownloaderError, get_info
    try:
        info = get_info(result.normalized_url)
    except DownloaderError as exc:
        return JSONResponse(
            {"valid": False, "code": "fetch_failed", "message": str(exc)},
            status_code=502,
        )
    return {"valid": True, "platform": result.platform,
            "normalized_url": result.normalized_url, **info}


@app.get("/api/download")
def api_download(
    request: Request,
    u: str = Query(..., max_length=MAX_URL_LENGTH * 2),
    f: str = Query(..., max_length=16),
):
    """Videoyu indirip kullanıcıya dosya olarak verir; iş klasörü yanıt
    biter bitmez silinir. (sync def → thread havuzunda çalışır,
    event loop bloklanmaz.)"""
    if not _allow(_client_ip(request), "download", limit=5):
        return _rate_limited()

    result = validate(u)
    if not result.valid:
        return JSONResponse(result.to_dict(), status_code=400)

    if not _DL_SLOTS.acquire(blocking=False):
        return JSONResponse(
            {"valid": False, "code": "busy",
             "message": "Sunucu şu an yoğun. Lütfen birkaç saniye sonra tekrar deneyin."},
            status_code=503,
        )

    from . import downloader as dl
    try:
        path, filename, job_dir = dl.download_video(result.normalized_url, f)
    except dl.DownloaderError as exc:
        _DL_SLOTS.release()
        return JSONResponse(
            {"valid": False, "code": "download_failed", "message": str(exc)},
            status_code=502,
        )
    except Exception:
        _DL_SLOTS.release()
        raise

    def _cleanup():
        shutil.rmtree(job_dir, ignore_errors=True)
        _DL_SLOTS.release()

    # filename sanitize edilmiş durumda; başlıkta ASCII fallback +
    # UTF-8 (RFC 5987) birlikte gönderilir
    ascii_name = filename.encode("ascii", "ignore").decode() or "video"
    headers = {
        "Content-Disposition":
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}",
        "X-Robots-Tag": "noindex",
    }
    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers=headers,
        background=BackgroundTask(_cleanup),
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/privacy")
async def privacy():
    return FileResponse(BASE_DIR / "static" / "privacy.html")


@app.get("/terms")
async def terms():
    return FileResponse(BASE_DIR / "static" / "terms.html")


@app.get("/dmca")
async def dmca():
    return FileResponse(BASE_DIR / "static" / "dmca.html")


@app.get("/contact")
async def contact():
    return FileResponse(BASE_DIR / "static" / "contact.html")


@app.get("/robots.txt")
async def robots():
    return FileResponse(BASE_DIR / "static" / "robots.txt", media_type="text/plain")


@app.get("/sitemap.xml")
async def sitemap():
    return FileResponse(BASE_DIR / "static" / "sitemap.xml", media_type="application/xml")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

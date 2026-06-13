"""İndirme katmanı testleri: format allowlist, dosya adı temizliği,
endpoint davranışı (mock) ve local sunucuyla GERÇEK yt-dlp uçtan uca testi."""

import http.server
import os
import shutil
import socketserver
import tempfile
import threading

import pytest
from fastapi.testclient import TestClient

from app import downloader as dl
from app import main as main_mod
from app.downloader import _format_selector, _safe_filename, sweep_stale
from app.main import _BUCKETS, app
from app.validator import ValidationResult

client = TestClient(app)


def setup_function():
    _BUCKETS.clear()


# ------------------------------------------------------------ format allowlist
@pytest.mark.parametrize("bad", ["", "exe", "mp4", "mp4-", "mp4-99", "mp4-99999",
                                 "mp4-720;rm -rf /", "../../etc", "mp3 ", "MP3"])
def test_gecersiz_format_kimligi(bad):
    err, _ = _format_selector(bad)
    assert err is not None


@pytest.mark.parametrize("good", ["mp3", "mp4-360", "mp4-720", "mp4-1080", "mp4-2160"])
def test_gecerli_format_kimligi(good):
    err, extra = _format_selector(good)
    assert err is None
    assert "format" in extra


# ------------------------------------------------------------- dosya adı temizliği
@pytest.mark.parametrize("raw,expected_clean", [
    ('Video: "En İyi" <Anlar> | 2026', None),       # tehlikeli karakterler gitmeli
    ("../../etc/passwd", None),
    ("CON\\aux\\nul", None),
    ("çok güzel bir video 😀", None),               # unicode korunur
    ("", None),                                      # boş → 'video'
    ("a" * 500, None),                               # uzunluk sınırı
])
def test_dosya_adi_temizligi(raw, expected_clean):
    name = _safe_filename(raw)
    assert name, "ad asla boş olamaz"
    assert len(name) <= 120
    for ch in '\\/:*?"<>|\r\n\0':
        assert ch not in name


# ------------------------------------------------------------------ bayat süpürme
def test_bayat_klasorler_silinir(tmp_path):
    eski = tmp_path / "svd-eski"
    eski.mkdir()
    os.utime(eski, (0, 0))  # çok eski görünsün
    yeni = tmp_path / "svd-yeni"
    yeni.mkdir()
    removed = sweep_stale(root=str(tmp_path), max_age=3600)
    assert removed == 1
    assert not eski.exists()
    assert yeni.exists()


# ------------------------------------------------- endpoint (mock'lu) testleri
def test_download_gecersiz_url():
    r = client.get("/api/download", params={"u": "https://127.0.0.1/x", "f": "mp4-720"})
    assert r.status_code == 400
    assert r.json()["code"] == "ip_host"


def test_download_gecersiz_format(monkeypatch):
    r = client.get("/api/download",
                   params={"u": "https://youtu.be/dQw4w9WgXcQ", "f": "exe"})
    assert r.status_code == 502
    assert r.json()["code"] == "download_failed"


def test_download_mock_stream_ve_temizlik(monkeypatch):
    """Endpoint: dosyayı doğru başlıklarla verir ve iş klasörünü siler."""
    job_dir = tempfile.mkdtemp(prefix="svd-test-")
    fpath = os.path.join(job_dir, "abc.mp4")
    with open(fpath, "wb") as fh:
        fh.write(b"FAKEVIDEO" * 100)

    def fake_download(url, format_id):
        return fpath, "Güzel Video.mp4", job_dir

    monkeypatch.setattr(dl, "download_video", fake_download)
    r = client.get("/api/download",
                   params={"u": "https://youtu.be/dQw4w9WgXcQ", "f": "mp4-720"})
    assert r.status_code == 200
    assert r.content == b"FAKEVIDEO" * 100
    cd = r.headers["Content-Disposition"]
    assert "attachment" in cd and "filename*=UTF-8''" in cd
    # TestClient background task'ları çalıştırır → klasör silinmiş olmalı
    assert not os.path.exists(job_dir)


def test_download_hata_durumunda_slot_sizdirmaz(monkeypatch):
    """DownloaderError sonrası semafor geri verilmeli (kaynak sızıntısı yok)."""
    def boom(url, format_id):
        raise dl.DownloaderError("test hatası")

    monkeypatch.setattr(dl, "download_video", boom)
    for _ in range(main_mod.MAX_CONCURRENT_DOWNLOADS + 2):
        _BUCKETS.clear()
        r = client.get("/api/download",
                       params={"u": "https://youtu.be/dQw4w9WgXcQ", "f": "mp4-720"})
        assert r.status_code == 502  # slot bitseydi 503 görürdük


def test_yogunluk_siniri(monkeypatch):
    """Tüm slotlar doluyken kibar 503 dönmeli."""
    acquired = [main_mod._DL_SLOTS.acquire(blocking=False)
                for _ in range(main_mod.MAX_CONCURRENT_DOWNLOADS)]
    try:
        r = client.get("/api/download",
                       params={"u": "https://youtu.be/dQw4w9WgXcQ", "f": "mp4-720"})
        assert r.status_code == 503
        assert r.json()["code"] == "busy"
    finally:
        for ok in acquired:
            if ok:
                main_mod._DL_SLOTS.release()


# --------------------------------------------- GERÇEK yt-dlp ile uçtan uca test
@pytest.fixture()
def local_video_server(tmp_path):
    """Ağa çıkmadan gerçek indirme testi: ffmpeg ile üretilen ufak mp4'ü
    servis eden yerel HTTP sunucusu."""
    pytest.importorskip("yt_dlp")
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg yok")

    video = tmp_path / "ornek video.mp4"
    code = os.system(
        f'ffmpeg -loglevel error -y -f lavfi -i testsrc=duration=1:size=128x72:rate=10 '
        f'-f lavfi -i sine=frequency=440:duration=1 -shortest "{video}"'
    )
    if code != 0 or not video.exists():
        pytest.skip("ffmpeg test videosu üretemedi")

    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(tmp_path), **kw)
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}/ornek%20video.mp4"
    srv.shutdown()


def test_gercek_indirme_uctan_uca(local_video_server, monkeypatch):
    """validator → endpoint → yt-dlp → stream → temizlik zinciri gerçek çalışır."""
    url = local_video_server

    def fake_validate(raw):
        return ValidationResult(True, "ok", "Test bağlantısı doğrulandı.",
                                platform="Test", normalized_url=url)

    monkeypatch.setattr(main_mod, "validate", fake_validate)

    before = set(os.listdir(dl.DOWNLOAD_ROOT)) if os.path.isdir(dl.DOWNLOAD_ROOT) else set()
    r = client.get("/api/download", params={"u": url, "f": "mp4-720"})
    assert r.status_code == 200, r.text
    assert len(r.content) > 1000          # gerçek video baytları geldi
    assert "attachment" in r.headers["Content-Disposition"]
    after = set(os.listdir(dl.DOWNLOAD_ROOT)) if os.path.isdir(dl.DOWNLOAD_ROOT) else set()
    assert before == after                 # iş klasörü temizlendi


def test_gercek_mp3_donusumu(local_video_server, monkeypatch):
    url = local_video_server

    def fake_validate(raw):
        return ValidationResult(True, "ok", "Test bağlantısı doğrulandı.",
                                platform="Test", normalized_url=url)

    monkeypatch.setattr(main_mod, "validate", fake_validate)
    r = client.get("/api/download", params={"u": url, "f": "mp3"})
    assert r.status_code == 200, r.text
    assert len(r.content) > 500
    assert ".mp3" in r.headers["Content-Disposition"]

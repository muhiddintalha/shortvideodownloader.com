"""API katmanı testleri: uç noktalar, güvenlik başlıkları, rate limit."""

from fastapi.testclient import TestClient

from app.main import app, _BUCKETS

client = TestClient(app)


def setup_function():
    _BUCKETS.clear()  # her test temiz rate-limit penceresiyle başlasın


def test_validate_gecerli():
    r = client.post("/api/validate", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["platform"] == "YouTube"


def test_validate_saldiri():
    r = client.post("/api/validate", json={"url": "https://127.0.0.1/x"})
    assert r.status_code == 200
    assert r.json()["valid"] is False
    assert r.json()["code"] == "ip_host"


def test_guvenlik_basliklari_var():
    r = client.get("/healthz")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in r.headers
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_api_docs_kapali():
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_rate_limit_calisiyor():
    url = {"url": "https://youtu.be/dQw4w9WgXcQ"}
    for _ in range(30):
        assert client.post("/api/validate", json=url).status_code == 200
    r = client.post("/api/validate", json=url)
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limited"


def test_bozuk_govde_dostca_hata():
    r = client.post("/api/validate", json={"yanlis_alan": 1})
    assert r.status_code == 400
    assert r.json()["code"] == "bad_request"


def test_ana_sayfa_serviliyor():
    r = client.get("/")
    assert r.status_code == 200
    assert "Short Video" in r.text

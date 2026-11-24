import pytest

from utah_housing.parser import SourceError, synthetic_fixture
from utah_housing.pipeline import fetch_annual


class Response:
    status = 200
    headers = {"Content-Type": "text/plain"}
    def __init__(self, body):
        self.body = body
    def read(self, limit):
        return self.body[:limit]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def test_http_200_html_is_an_error_not_source_data(monkeypatch, tmp_path):
    response = Response(b"<html>Missing key</html>")
    response.headers = {"Content-Type": "text/html"}
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: response)
    with pytest.raises(SourceError, match="HTML"):
        fetch_annual(2025, tmp_path)
    assert not list(tmp_path.rglob("*.txt"))


def test_exact_raw_fingerprint_and_atomic_concurrent_cache(monkeypatch, tmp_path):
    import hashlib
    from concurrent.futures import ThreadPoolExecutor
    raw = synthetic_fixture()
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response(raw))
    with ThreadPoolExecutor(4) as pool:
        records = list(pool.map(lambda _: fetch_annual(2025, tmp_path), range(4)))
    assert {row["sha256"] for row in records} == {hashlib.sha256(raw).hexdigest()}
    assert len(list(tmp_path.rglob("*.txt"))) == 1
    assert not list(tmp_path.rglob("*.tmp"))
    assert not list(tmp_path.rglob("*.download"))
    assert all(row["basis"] == "annual" and row["year"] == 2025 for row in records)

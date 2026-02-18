import tempfile
from pathlib import Path

from paleonews.fetcher import load_sources, fetch_feed


def test_load_sources():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("https://example.com/feed1\n")
        f.write("  \n")
        f.write("# comment\n")
        f.write("https://example.com/feed2\n")
        f.flush()

        sources = load_sources(f.name)

    assert sources == ["https://example.com/feed1", "https://example.com/feed2"]
    Path(f.name).unlink()


def test_fetch_feed_invalid_url():
    articles = fetch_feed("https://invalid.example.com/nonexistent.xml")
    assert articles == []

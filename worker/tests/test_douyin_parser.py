"""Parser tests against a real share-page fixture (image post)."""
from pathlib import Path

from worker.tools import DouyinFetcher


FIXTURE = Path(__file__).parent / "fixtures" / "douyin-image-post.html"


def test_image_post_parsed():
    html = FIXTURE.read_text()
    info = DouyinFetcher._parse_share_html(html)
    assert info is not None, "parser returned None for an image post"
    assert "image_urls" in info, "expected image_urls key for aweme_type=2"
    urls = info["image_urls"]
    assert len(urls) >= 1, f"expected at least one image URL, got {urls!r}"
    for u in urls:
        assert u.startswith("https://"), f"non-https url leaked through: {u!r}"
    # Title round-trips CJK correctly
    assert info.get("title")
    assert "焦虑" in info["title"], f"title CJK broken: {info['title']!r}"


def test_image_url_extractor_dedupes():
    fake_html = (
        '"images":[{"uri":"a","url_list":["https:\\u002F\\u002Fe.com\\u002Fp1.jpg"]}]'
        ',"images":[{"uri":"a","url_list":["https:\\u002F\\u002Fe.com\\u002Fp1.jpg"]}]'
        ',"images":[{"uri":"b","url_list":["https:\\u002F\\u002Fe.com\\u002Fp2.jpg"]}]'
    )
    urls = DouyinFetcher._parse_image_urls(fake_html)
    assert urls == ["https://e.com/p1.jpg", "https://e.com/p2.jpg"]

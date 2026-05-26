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

    # Post desc: user-typed caption (not the BGM track).
    assert info.get("desc")
    assert "第一性原理" in info["desc"], f"desc CJK broken: {info['desc']!r}"
    assert "claude" in info["desc"].lower()

    # Author: post creator nickname.
    assert info.get("author") == "AI大刘", f"unexpected author: {info.get('author')!r}"

    # Music: the BGM track. We pull it for metadata but do NOT use it as title.
    assert info.get("music_title")
    assert "焦虑" in info["music_title"], f"music_title broken: {info['music_title']!r}"


def test_title_picks_post_desc_first_line():
    # Hashtag spam at the end is stripped.
    title = DouyinFetcher._title_from(
        post_text="第一性原理写入claude.md，惊喜！\n第二行 #ai #程序员",
        author="AI大刘",
        music_title="某BGM",
        aweme_id="123",
    )
    assert title == "第一性原理写入claude.md，惊喜！"


def test_title_falls_back_when_no_desc():
    title = DouyinFetcher._title_from(
        post_text="",
        author="AI大刘",
        music_title="某BGM",
        aweme_id="123",
    )
    assert title == "某BGM"


def test_title_strips_pure_hashtag_tail():
    title = DouyinFetcher._title_from(
        post_text="实测 #ai #程序员 #分享",
        author="A",
        music_title="",
        aweme_id="1",
    )
    assert title == "实测"


def test_image_url_extractor_dedupes():
    fake_html = (
        '"images":[{"uri":"a","url_list":["https:\\u002F\\u002Fe.com\\u002Fp1.jpg"]}]'
        ',"images":[{"uri":"a","url_list":["https:\\u002F\\u002Fe.com\\u002Fp1.jpg"]}]'
        ',"images":[{"uri":"b","url_list":["https:\\u002F\\u002Fe.com\\u002Fp2.jpg"]}]'
    )
    urls = DouyinFetcher._parse_image_urls(fake_html)
    assert urls == ["https://e.com/p1.jpg", "https://e.com/p2.jpg"]

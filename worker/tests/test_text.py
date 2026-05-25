from datetime import date

from worker.text import filename_for, format_ts, slugify


def test_format_ts_under_hour():
    assert format_ts(0) == "00:00"
    assert format_ts(65) == "01:05"
    assert format_ts(599) == "09:59"


def test_format_ts_over_hour():
    assert format_ts(3600) == "01:00:00"
    assert format_ts(3661) == "01:01:01"


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"
    assert slugify("My Vibe Coding!!!") == "my-vibe-coding"


def test_slugify_chinese_falls_back_to_video():
    # Pure CJK strips to empty after ASCII fold; we want a stable fallback.
    assert slugify("vibe coding 教程") == "vibe-coding"
    assert slugify("纯中文标题") == "video"


def test_slugify_truncates():
    s = slugify("a" * 200)
    assert len(s) <= 60


def test_filename_for():
    assert filename_for(date(2026, 5, 25), "Hello World") == "2026-05-25-hello-world.md"
    assert filename_for(date(2026, 5, 25), "纯中文") == "2026-05-25-video.md"

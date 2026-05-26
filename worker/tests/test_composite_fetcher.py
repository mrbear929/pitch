"""Composite fetcher tries fetchers in order; first success wins."""
from pathlib import Path

import pytest
from worker.pipeline import FetchError, VideoMeta
from worker.tools import CompositeFetcher, _extract_douyin_id


class FakeFetcher:
    def __init__(self, behavior):
        self.behavior = behavior
        self.called = False

    def fetch(self, url, work_dir):
        self.called = True
        if isinstance(self.behavior, Exception):
            raise self.behavior
        p = Path(work_dir) / "out.mp4"
        p.write_bytes(b"")
        return VideoMeta(title=self.behavior, duration_seconds=1.0, media_path=p)


def test_first_succeeds(tmp_path):
    a = FakeFetcher("from-a")
    b = FakeFetcher("from-b")
    c = CompositeFetcher([a, b])
    meta = c.fetch("https://x", tmp_path)
    assert meta.title == "from-a"
    assert a.called and not b.called


def test_falls_through_on_fetch_error(tmp_path):
    a = FakeFetcher(FetchError("a-skip", "guidance-a"))
    b = FakeFetcher("from-b")
    c = CompositeFetcher([a, b])
    meta = c.fetch("https://x", tmp_path)
    assert meta.title == "from-b"
    assert a.called and b.called


def test_propagates_last_error_when_all_fail(tmp_path):
    a = FakeFetcher(FetchError("a-skip", "guidance-a"))
    b = FakeFetcher(FetchError("b-skip", "guidance-b"))
    c = CompositeFetcher([a, b])
    with pytest.raises(FetchError) as ei:
        c.fetch("https://x", tmp_path)
    assert ei.value.user_guidance == "guidance-b"


def test_empty_chain_rejected():
    with pytest.raises(ValueError):
        CompositeFetcher([])


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.douyin.com/video/7636717976720264491", "7636717976720264491"),
        ("https://www.douyin.com/note/7618972935072366505", "7618972935072366505"),
        ("https://www.douyin.com/jingxuan?modal_id=7618972935072366505", "7618972935072366505"),
        ("https://www.iesdouyin.com/share/video/7618972935072366505/", "7618972935072366505"),
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw", None),
        ("https://example.com/", None),
    ],
)
def test_extract_douyin_id(url, expected):
    assert _extract_douyin_id(url) == expected

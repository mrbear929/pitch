"""End-to-end pipeline test using fakes for every external call."""
from __future__ import annotations

from pathlib import Path

from worker.pipeline import FetchError, MediaBundle, Pipeline
from worker.render import TranscriptSegment


_TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d"
    "0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d3832"
    "3c2e333432ffdb0043010909090c0b0c180d0d1832211c2132323232323232323232323232323232323232"
    "32323232323232323232323232323232323232323232323232323232323232323232ffc00011080001000103"
    "012200021101031101ffc4001f0000010501010101010100000000000000000102030405060708090a0b"
    "ffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191"
    "a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a"
    "535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3"
    "a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9"
    "eaf1f2f3f4f5f6f7f8f9faffc4001f0100030101010101010101010000000000000102030405060708090a"
    "0bffc400b51100020102040403040705040400010277000102031104052131061241510761711322328108"
    "144291a1b1c109233352f0156272d10a162434e125f11718191a262728292a35363738393a434445464748"
    "494a535455565758595a636465666768696a737475767778797a82838485868788898a92939495969798"
    "999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6"
    "e7e8e9eaf2f3f4f5f6f7f8f9faffda000c03010002110311003f00fbfa28a28affd9"
)


class FakeVideoFetcher:
    def fetch(self, url, work_dir):
        v = Path(work_dir) / "video.mp4"
        v.write_bytes(b"")
        return MediaBundle(
            title="Faked Title",
            video_path=v,
            duration_seconds=42,
            post_text="post body",
            author="bear",
        )


class FakeImageFetcher:
    def fetch(self, url, work_dir):
        a = Path(work_dir) / "a.jpg"
        b = Path(work_dir) / "b.jpg"
        a.write_bytes(_TINY_JPEG)
        b.write_bytes(_TINY_JPEG)
        return MediaBundle(title="Image Post", image_paths=[a, b], post_text="caption", author="bear")


class FailingFetcher:
    def fetch(self, url, work_dir):
        raise FetchError("nope", "Try uploading.")


class FakeAudio:
    def extract(self, video_path, work_dir):
        p = Path(work_dir) / "a.wav"
        p.write_bytes(b"")
        return p


class FakeTranscriber:
    def __init__(self, segs=None):
        self.segs = segs if segs is not None else [TranscriptSegment(start=0.0, end=2.0, text="hi")]

    def transcribe(self, audio_path):
        return self.segs


class CrashingTranscriber:
    def transcribe(self, audio_path):
        raise RuntimeError("groq down")


class FakeUnderstander:
    def __init__(self):
        self.last_call = None

    def understand(self, video_path, transcript, post_text="", author=""):
        self.last_call = (video_path, len(transcript), post_text, author)
        return {
            "coverage": "It covers stuff.",
            "key_points": ["x", "y"],
            "tools_mentioned": ["Z"],
            "code_snippets": ["pip install Z"],
        }


class CrashingUnderstander:
    def understand(self, video_path, transcript, post_text="", author=""):
        raise RuntimeError("gemini down")


def make_pipeline(**over):
    base = dict(
        fetcher=FakeVideoFetcher(),
        audio=FakeAudio(),
        transcriber=FakeTranscriber(),
        understander=FakeUnderstander(),
    )
    base.update(over)
    return Pipeline(**base)


def test_video_path_runs(tmp_path):
    u = FakeUnderstander()
    p = make_pipeline(understander=u)
    result = p.run(url="https://x", work_dir=tmp_path)
    md = result.markdown
    assert result.title == "Faked Title"
    assert result.slug == "faked-title"
    assert "## What this covers" in md
    assert "It covers stuff." in md
    assert "**Type:** video" in md
    assert "took" in md
    assert u.last_call[1] == 1  # 1 transcript segment
    assert u.last_call[2] == "post body"
    assert u.last_call[3] == "bear"


def test_image_carousel_fast_path(tmp_path):
    u = FakeUnderstander()
    p = make_pipeline(fetcher=FakeImageFetcher(), understander=u)
    result = p.run(url="https://x", work_dir=tmp_path)
    md = result.markdown

    assert result.title == "Image Post"
    assert "**Type:** image carousel" in md
    assert "## Slides" in md
    assert "![](attachments/pitch/" in md
    assert "## Transcript" not in md

    assert len(result.attachments) == 2
    assert all(a.filename.endswith(".jpg") for a in result.attachments)

    # Fast path skips both transcribe and understand entirely.
    assert u.last_call is None


def test_understander_crash_swallowed(tmp_path):
    p = make_pipeline(understander=CrashingUnderstander())
    result = p.run(url="https://x", work_dir=tmp_path)
    # Renders without coverage but with the rest (transcript still rendered).
    assert "## What this covers" not in result.markdown
    assert "## Transcript" in result.markdown


def test_transcriber_crash_continues(tmp_path):
    """Even if Groq fails, Gemini still gets called (with empty transcript)."""
    u = FakeUnderstander()
    p = make_pipeline(transcriber=CrashingTranscriber(), understander=u)
    result = p.run(url="https://x", work_dir=tmp_path)
    assert u.last_call is not None
    assert u.last_call[1] == 0  # empty transcript passed through
    assert "## What this covers" in result.markdown


def test_no_understander(tmp_path):
    p = make_pipeline(understander=None)
    result = p.run(url="https://x", work_dir=tmp_path)
    assert "## What this covers" not in result.markdown


def test_fetch_failure_propagates(tmp_path):
    p = make_pipeline(fetcher=FailingFetcher())
    try:
        p.run(url="https://x", work_dir=tmp_path)
    except FetchError as e:
        assert e.user_guidance == "Try uploading."
    else:
        raise AssertionError("expected FetchError")

"""End-to-end pipeline test using fakes for every external tool."""
from __future__ import annotations

from pathlib import Path

from worker.pipeline import FetchError, Pipeline, VideoMeta
from worker.render import TranscriptSegment


class FakeFetcher:
    def fetch(self, url, work_dir):
        p = Path(work_dir) / "video.mp4"
        p.write_bytes(b"")
        return VideoMeta(title="Faked Title", duration_seconds=42, media_path=p)


class FailingFetcher:
    def fetch(self, url, work_dir):
        raise FetchError("nope", "Try uploading.")


class FakeAudio:
    def extract(self, video_path, work_dir):
        p = Path(work_dir) / "a.wav"
        p.write_bytes(b"")
        return p


class FakeTranscriber:
    def transcribe(self, audio_path):
        return [
            TranscriptSegment(start=0.0, end=1.5, text="hi"),
            TranscriptSegment(start=1.5, end=3.0, text="there"),
        ]


class FakeFrames:
    def sample(self, video_path, work_dir, every_seconds):
        f1 = Path(work_dir) / "f1.jpg"
        f2 = Path(work_dir) / "f2.jpg"
        f1.write_bytes(b"")
        f2.write_bytes(b"")
        return [(0.0, f1), (float(every_seconds), f2)]


class FakeOcr:
    def __init__(self, texts):
        self.texts = list(texts)

    def run(self, image_path):
        return self.texts.pop(0) if self.texts else ""


class FakeUnderstander:
    def understand(self, transcript, frames):
        return {
            "summary": "Two-second video.",
            "key_points": ["greets"],
            "tools_mentioned": [],
            "code_snippets": [],
        }


class CrashingUnderstander:
    def understand(self, transcript, frames):
        raise RuntimeError("ollama down")


def test_pipeline_happy_path(tmp_path):
    p = Pipeline(
        fetcher=FakeFetcher(),
        audio=FakeAudio(),
        transcriber=FakeTranscriber(),
        frames=FakeFrames(),
        ocr=FakeOcr(["$ ls", ""]),
        understander=FakeUnderstander(),
    )
    md, title, slug = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    assert title == "Faked Title"
    assert slug == "faked-title"
    assert "## Summary" in md
    assert "Two-second video." in md
    assert "$ ls" in md
    assert "## Frame OCR" in md


def test_pipeline_understander_crash_is_swallowed(tmp_path):
    p = Pipeline(
        fetcher=FakeFetcher(),
        audio=FakeAudio(),
        transcriber=FakeTranscriber(),
        frames=FakeFrames(),
        ocr=FakeOcr([""]),
        understander=CrashingUnderstander(),
    )
    md, _, _ = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    # No summary section, but still renders
    assert "## Transcript" in md
    assert "## Summary" not in md


def test_pipeline_no_understander(tmp_path):
    p = Pipeline(
        fetcher=FakeFetcher(),
        audio=FakeAudio(),
        transcriber=FakeTranscriber(),
        frames=FakeFrames(),
        ocr=FakeOcr([""]),
        understander=None,
    )
    md, _, _ = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    assert "## Summary" not in md
    assert "## Transcript" in md


def test_pipeline_fetch_failure_propagates(tmp_path):
    p = Pipeline(
        fetcher=FailingFetcher(),
        audio=FakeAudio(),
        transcriber=FakeTranscriber(),
        frames=FakeFrames(),
        ocr=FakeOcr([]),
        understander=None,
    )
    try:
        p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    except FetchError as e:
        assert e.user_guidance == "Try uploading."
    else:
        raise AssertionError("expected FetchError")

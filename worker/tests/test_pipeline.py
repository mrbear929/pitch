"""End-to-end pipeline test using fakes for every external tool."""
from __future__ import annotations

from pathlib import Path

from worker.pipeline import FetchError, MediaBundle, Pipeline
from worker.render import TranscriptSegment


class FakeVideoFetcher:
    def __init__(self, with_images=False):
        self.with_images = with_images

    def fetch(self, url, work_dir):
        v = Path(work_dir) / "video.mp4"
        v.write_bytes(b"")
        bundle = MediaBundle(title="Faked Title", video_path=v, duration_seconds=42)
        if self.with_images:
            i = Path(work_dir) / "img.jpg"
            i.write_bytes(b"")
            bundle.image_paths = [i]
        return bundle


class FakeImageFetcher:
    def fetch(self, url, work_dir):
        a = Path(work_dir) / "a.jpg"
        b = Path(work_dir) / "b.jpg"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        return MediaBundle(title="Image Post", image_paths=[a, b])


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
        return [TranscriptSegment(start=0.0, end=1.5, text="hi")]


class FakeFrames:
    def sample(self, video_path, work_dir, every_seconds):
        f = Path(work_dir) / "f.jpg"
        f.write_bytes(b"")
        return [(0.0, f)]


class FakeOcr:
    def __init__(self, texts=("",)):
        self.texts = list(texts)

    def run(self, image_path):
        return self.texts.pop(0) if self.texts else ""


class CrashingOcr:
    def run(self, image_path):
        raise RuntimeError("ocr down")


class FakeVision:
    def __init__(self, descriptions=("desc",)):
        self.descriptions = list(descriptions)

    def describe(self, image_path):
        return self.descriptions.pop(0) if self.descriptions else ""


class CrashingVision:
    def describe(self, image_path):
        raise RuntimeError("vision down")


class FakeUnderstander:
    def __init__(self):
        self.last_call = None

    def understand(self, transcript, frames, images):
        self.last_call = (len(transcript), len(frames), len(images))
        return {"summary": "ok", "key_points": [], "tools_mentioned": [], "code_snippets": []}


class CrashingUnderstander:
    def understand(self, transcript, frames, images):
        raise RuntimeError("ollama down")


def make_pipeline(**over):
    base = dict(
        fetcher=FakeVideoFetcher(),
        audio=FakeAudio(),
        transcriber=FakeTranscriber(),
        frames=FakeFrames(),
        ocr=FakeOcr(["$ ls"]),
        vision=FakeVision(["a terminal"]),
        understander=FakeUnderstander(),
    )
    base.update(over)
    return Pipeline(**base)


def test_video_path_runs(tmp_path):
    u = FakeUnderstander()
    p = make_pipeline(understander=u)
    md, title, slug = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    assert title == "Faked Title"
    assert slug == "faked-title"
    assert "## Summary" in md
    assert "## Frame Visuals" in md
    assert "$ ls" in md
    assert "a terminal" in md
    assert u.last_call == (1, 1, 0)  # 1 transcript seg, 1 frame, 0 images


def test_image_path_runs(tmp_path):
    u = FakeUnderstander()
    p = make_pipeline(
        fetcher=FakeImageFetcher(),
        vision=FakeVision(["pic 1", "pic 2"]),
        ocr=FakeOcr(["", ""]),
        understander=u,
    )
    md, title, _ = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    assert title == "Image Post"
    assert "**Type:** image carousel" in md
    assert "## Image Carousel" in md
    assert "pic 1" in md and "pic 2" in md
    assert "## Transcript" not in md
    assert u.last_call == (0, 0, 2)  # no transcript, no frames, 2 images


def test_understander_crash_swallowed(tmp_path):
    p = make_pipeline(understander=CrashingUnderstander())
    md, _, _ = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    assert "## Summary" not in md
    assert "## Frame Visuals" in md  # frames still rendered


def test_no_understander(tmp_path):
    p = make_pipeline(understander=None)
    md, _, _ = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    assert "## Summary" not in md


def test_no_vision(tmp_path):
    # No vision = frames still render, just without vision_description
    p = make_pipeline(vision=None)
    md, _, _ = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    # OCR text alone is enough to keep the frame visible
    assert "$ ls" in md


def test_vision_crash_swallowed(tmp_path):
    p = make_pipeline(vision=CrashingVision())
    md, _, _ = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    # Frame is still visible because OCR succeeded
    assert "$ ls" in md


def test_ocr_crash_swallowed(tmp_path):
    p = make_pipeline(ocr=CrashingOcr())
    md, _, _ = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    # Vision description alone keeps the frame visible
    assert "a terminal" in md


def test_fetch_failure_propagates(tmp_path):
    p = make_pipeline(fetcher=FailingFetcher())
    try:
        p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    except FetchError as e:
        assert e.user_guidance == "Try uploading."
    else:
        raise AssertionError("expected FetchError")

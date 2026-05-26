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


class FakeImageFetcher:
    def fetch(self, url, work_dir):
        a = Path(work_dir) / "a.jpg"
        b = Path(work_dir) / "b.jpg"
        a.write_bytes(_TINY_JPEG)
        b.write_bytes(_TINY_JPEG)
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

    def understand(self, transcript, frames, images, post_text="", author=""):
        self.last_call = (len(transcript), len(frames), len(images), post_text, author)
        return {"summary": "ok", "key_points": [], "tools_mentioned": [], "code_snippets": []}


class CrashingUnderstander:
    def understand(self, transcript, frames, images, post_text="", author=""):
        raise RuntimeError("ollama down")


class FakeOcrCleaner:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.last_hint = None

    def clean(self, raw_ocr, vision_hint=""):
        self.last_hint = vision_hint
        return self.mapping.get(raw_ocr, raw_ocr.replace(" ", ""))


def make_pipeline(**over):
    base = dict(
        fetcher=FakeVideoFetcher(),
        audio=FakeAudio(),
        transcriber=FakeTranscriber(),
        frames=FakeFrames(),
        ocr=FakeOcr(["$ ls"]),
        vision=FakeVision(["a terminal"]),
        understander=FakeUnderstander(),
        ocr_cleaner=None,
    )
    base.update(over)
    return Pipeline(**base)


def test_video_path_runs(tmp_path):
    u = FakeUnderstander()
    p = make_pipeline(understander=u)
    result = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    md, title, slug = result.markdown, result.title, result.slug
    assert title == "Faked Title"
    assert slug == "faked-title"
    assert "## Summary" in md
    assert "## Frame Visuals" in md
    assert "$ ls" in md
    assert "a terminal" in md
    assert "took" in md  # processing time line
    assert u.last_call[:3] == (1, 1, 0)  # 1 transcript seg, 1 frame, 0 images


def test_image_carousel_fast_path(tmp_path):
    """Image-only post hits the fast path: no LLM, just embed images."""
    u = FakeUnderstander()
    p = make_pipeline(
        fetcher=FakeImageFetcher(),
        vision=FakeVision(["pic 1", "pic 2"]),
        ocr=FakeOcr(["nope1", "nope2"]),
        understander=u,
    )
    result = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    md = result.markdown

    # Title comes from the fetcher; type is image carousel.
    assert result.title == "Image Post"
    assert "**Type:** image carousel" in md

    # Slides are embedded — no Vision/OCR sections.
    assert "## Slides" in md
    assert "![](attachments/pitch/" in md
    assert "## Image Carousel" not in md
    assert "## Transcript" not in md

    # Attachments accompany the markdown for the plugin to write.
    assert len(result.attachments) == 2
    assert all(a.filename.endswith(".jpg") for a in result.attachments)

    # Most importantly: the understander never ran.
    assert u.last_call is None


def test_post_text_and_author_threaded(tmp_path):
    """Bundle.post_text and bundle.author flow through to the understander."""

    class FetcherWithMeta:
        def fetch(self, url, work_dir):
            v = Path(work_dir) / "v.mp4"
            v.write_bytes(b"")
            return MediaBundle(
                title="T",
                video_path=v,
                duration_seconds=10,
                post_text="The actual post body",
                author="Some Author",
            )

    u = FakeUnderstander()
    p = make_pipeline(fetcher=FetcherWithMeta(), understander=u)
    result = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    md = result.markdown
    assert u.last_call[3] == "The actual post body"
    assert u.last_call[4] == "Some Author"
    # Post body shows up in the rendered note
    assert "## Post" in md
    assert "The actual post body" in md
    assert "**Author:** Some Author" in md


def test_ocr_cleaner_runs_for_video_frames(tmp_path):
    """Cleaner output replaces raw OCR on video frames; vision hint threaded."""
    cleaner = FakeOcrCleaner(mapping={"$  ls": "$ ls (clean)"})
    p = make_pipeline(
        # video path uses FakeVideoFetcher, frames via FakeFrames
        ocr=FakeOcr(["$  ls"]),
        vision=FakeVision(["v1"]),
        ocr_cleaner=cleaner,
    )
    result = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    assert "$ ls (clean)" in result.markdown
    assert cleaner.last_hint == "v1"


def test_ocr_cleaner_skips_empty_input(tmp_path):
    """Empty raw OCR short-circuits before the cleaner runs."""
    called = {"n": 0}

    class CountingCleaner:
        def clean(self, raw_ocr, vision_hint=""):
            called["n"] += 1
            return "should-not-appear"

    p = make_pipeline(
        ocr=FakeOcr([""]),
        vision=FakeVision(["v"]),
        ocr_cleaner=CountingCleaner(),
    )
    p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    assert called["n"] == 0


def test_understander_crash_swallowed(tmp_path):
    p = make_pipeline(understander=CrashingUnderstander())
    result = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    md = result.markdown
    assert "## Summary" not in md
    assert "## Frame Visuals" in md  # frames still rendered


def test_no_understander(tmp_path):
    p = make_pipeline(understander=None)
    result = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    md = result.markdown
    assert "## Summary" not in md


def test_no_vision(tmp_path):
    # No vision = frames still render, just without vision_description
    p = make_pipeline(vision=None)
    result = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    md = result.markdown
    # OCR text alone is enough to keep the frame visible
    assert "$ ls" in md


def test_vision_crash_swallowed(tmp_path):
    p = make_pipeline(vision=CrashingVision())
    result = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    md = result.markdown
    # Frame is still visible because OCR succeeded
    assert "$ ls" in md


def test_ocr_crash_swallowed(tmp_path):
    p = make_pipeline(ocr=CrashingOcr())
    result = p.run(url="https://x", work_dir=tmp_path, frame_every_seconds=10)
    md = result.markdown
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

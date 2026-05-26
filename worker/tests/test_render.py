from datetime import datetime, timezone

from worker.render import (
    FrameVisual,
    ImageVisual,
    LessonInputs,
    TranscriptSegment,
    render_lesson,
)


def video_inputs(**over):
    base = LessonInputs(
        source_url="https://example.com/v",
        title="Test Video",
        duration_seconds=125,
        processed_at=datetime(2026, 5, 25, 10, 30, tzinfo=timezone.utc),
        processing_seconds=42.0,
        transcript=[
            TranscriptSegment(start=0.0, end=2.0, text="Hello"),
            TranscriptSegment(start=2.0, end=4.0, text="world"),
        ],
        frame_visuals=[
            FrameVisual(timestamp=0.0, ocr_text="$ ls", vision_description="terminal"),
            FrameVisual(timestamp=30.0),  # empty, should be skipped
        ],
        image_visuals=[],
        has_video=True,
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


def image_inputs(**over):
    base = LessonInputs(
        source_url="https://example.com/c",
        title="Image Post",
        duration_seconds=0,
        processed_at=datetime(2026, 5, 25, 10, 30, tzinfo=timezone.utc),
        processing_seconds=70.0,
        transcript=[],
        frame_visuals=[],
        image_visuals=[
            ImageVisual(index=0, vision_description="A diagram of X."),
            ImageVisual(index=1, ocr_text="step 2"),
            ImageVisual(index=2),  # empty, skipped
        ],
        has_video=False,
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


def test_video_renders():
    md = render_lesson(video_inputs())
    assert "# Test Video" in md
    assert "**Duration:** 02:05" in md
    assert "**Type:** video" in md
    assert "took 42s" in md  # processing time
    assert "## Transcript" in md
    assert "`[00:00]` Hello" in md
    assert "## Frame Visuals" in md
    assert "$ ls" in md
    assert "terminal" in md


def test_image_post_renders():
    md = render_lesson(image_inputs())
    assert "# Image Post" in md
    assert "**Type:** image carousel" in md
    assert "**Duration:**" not in md  # no duration line for image-only
    assert "took 1m 10s" in md
    assert "## Transcript" not in md
    assert "## Image Carousel" in md
    assert "### Image 1" in md
    assert "A diagram of X." in md
    assert "### Image 2" in md
    assert "step 2" in md
    assert "### Image 3" not in md  # empty image skipped


def test_post_metadata_renders():
    md = render_lesson(
        image_inputs(
            post_text="The user-typed caption.\nWith two lines.",
            author="AI大刘",
            music_title="某BGM",
        )
    )
    assert "**Author:** AI大刘" in md
    assert "**BGM:** 某BGM" in md
    assert "## Post" in md
    assert "The user-typed caption." in md
    assert "With two lines." in md


def test_understanding_sections():
    md = render_lesson(
        video_inputs(
            summary="A short summary.",
            key_points=["A", "B"],
            tools_mentioned=["FastAPI", "Whisper"],
            code_snippets=["pip install fastapi"],
        )
    )
    assert "## Summary" in md
    assert "A short summary." in md
    assert "## Key Points" in md
    assert "## Tools Mentioned" in md
    assert "## Code / Commands" in md


def test_no_visible_visuals_no_section():
    md = render_lesson(video_inputs(frame_visuals=[]))
    assert "## Frame Visuals" not in md

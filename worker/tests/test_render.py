from datetime import datetime, timezone

from worker.render import LessonInputs, TranscriptSegment, render_lesson


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
        has_video=True,
        coverage="A coverage paragraph.",
        key_points=["A", "B"],
        tools_mentioned=["Tool1"],
        code_snippets=["pip install x"],
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
        has_video=False,
        embedded_image_paths=[
            "attachments/pitch/post-slug/01.jpg",
            "attachments/pitch/post-slug/02.jpg",
        ],
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


def test_video_renders():
    md = render_lesson(video_inputs())
    assert "# Test Video" in md
    assert "**Duration:** 02:05" in md
    assert "**Type:** video" in md
    assert "took 42s" in md
    assert "## What this covers" in md
    assert "A coverage paragraph." in md
    assert "## Key Points" in md
    assert "## Tools Mentioned" in md
    assert "## Code / Commands" in md
    assert "## Transcript" in md
    assert "`[00:00]` Hello" in md


def test_image_post_renders():
    md = render_lesson(image_inputs())
    assert "# Image Post" in md
    assert "**Type:** image carousel" in md
    assert "**Duration:**" not in md
    assert "took 1m 10s" in md
    assert "## Transcript" not in md
    assert "## Slides" in md
    assert "![](attachments/pitch/post-slug/01.jpg)" in md


def test_post_metadata_renders():
    md = render_lesson(
        image_inputs(
            post_text="The user-typed caption.\nWith two lines.",
            author="AI大刘",
        )
    )
    assert "**Author:** AI大刘" in md
    assert "BGM" not in md  # explicitly suppressed
    assert "## Post" in md
    assert "The user-typed caption." in md

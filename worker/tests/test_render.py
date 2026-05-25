from datetime import datetime, timezone

from worker.render import FrameOcr, LessonInputs, TranscriptSegment, render_lesson


def make_inputs(**over):
    base = LessonInputs(
        source_url="https://example.com/v",
        title="Test Video",
        duration_seconds=125,
        processed_at=datetime(2026, 5, 25, 10, 30, tzinfo=timezone.utc),
        transcript=[
            TranscriptSegment(start=0.0, end=2.0, text="Hello"),
            TranscriptSegment(start=2.0, end=4.0, text="world"),
        ],
        frames=[
            FrameOcr(timestamp=0.0, text="$ ls"),
            FrameOcr(timestamp=30.0, text=""),  # empty frame, should be skipped
        ],
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


def test_render_minimal():
    md = render_lesson(make_inputs())
    assert "# Test Video" in md
    assert "https://example.com/v" in md
    assert "**Duration:** 02:05" in md
    assert "## Transcript" in md
    assert "`[00:00]` Hello" in md
    assert "`[00:02]` world" in md
    # Empty frame text is skipped
    assert md.count("### ") == 1
    assert "$ ls" in md


def test_render_includes_understanding():
    md = render_lesson(
        make_inputs(
            summary="A short summary.",
            key_points=["A", "B"],
            tools_mentioned=["FastAPI", "Whisper"],
            code_snippets=["pip install fastapi"],
        )
    )
    assert "## Summary" in md
    assert "A short summary." in md
    assert "## Key Points" in md
    assert "- A" in md
    assert "## Tools Mentioned" in md
    assert "## Code / Commands (from frames)" in md
    assert "pip install fastapi" in md


def test_render_no_frames_no_section():
    md = render_lesson(make_inputs(frames=[]))
    assert "## Frame OCR" not in md

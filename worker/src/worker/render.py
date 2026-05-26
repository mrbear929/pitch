"""Markdown rendering for the lesson note."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from jinja2 import Environment, StrictUndefined

from .text import format_ts


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class FrameVisual:
    """A sampled video frame with what we know about it."""

    timestamp: float
    ocr_text: str = ""           # cleaned OCR (legible)
    ocr_text_raw: str = ""       # original Tesseract output (preserved for debug)
    vision_description: str = ""


@dataclass
class ImageVisual:
    """A single image from a carousel post."""

    index: int                   # 0-based
    ocr_text: str = ""
    ocr_text_raw: str = ""
    vision_description: str = ""


@dataclass
class LessonInputs:
    source_url: str
    title: str
    duration_seconds: float
    processed_at: datetime
    processing_seconds: float
    transcript: list[TranscriptSegment]
    frame_visuals: list[FrameVisual]
    image_visuals: list[ImageVisual]
    has_video: bool
    post_text: str = ""
    author: str = ""
    music_title: str = ""
    # For image-carousel posts: vault-relative paths the markdown will reference
    # via Obsidian's ![](path) syntax. Empty for video-only posts.
    embedded_image_paths: list[str] = field(default_factory=list)
    # For videos: a one-paragraph "what does this video cover" description.
    coverage: Optional[str] = None
    # Legacy summary/key_points/etc. used by video path; image carousels skip these.
    summary: Optional[str] = None
    key_points: list[str] = field(default_factory=list)
    tools_mentioned: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)


def _format_processing_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if s else f"{m}m"


_TEMPLATE = """\
# {{ title }}

- **URL:** {{ source_url }}
{% if author -%}
- **Author:** {{ author }}
{% endif -%}
{% if has_video -%}
- **Duration:** {{ duration }}
{% endif -%}
- **Type:** {{ media_type }}
- **Processed:** {{ processed_at }} (took {{ processing_time }})
{% if music_title -%}
- **BGM:** {{ music_title }}
{% endif %}
{% if post_text -%}
## Post

{{ post_text }}

{% endif -%}
{% if coverage -%}
## What this covers

{{ coverage }}

{% endif -%}
{% if summary -%}
## Summary

{{ summary }}

{% endif -%}
{% if key_points -%}
## Key Points

{% for p in key_points %}- {{ p }}
{% endfor %}
{% endif -%}
{% if tools_mentioned -%}
## Tools Mentioned

{% for t in tools_mentioned %}- {{ t }}
{% endfor %}
{% endif -%}
{% if code_snippets -%}
## Code / Commands

{% for s in code_snippets %}```
{{ s }}
```

{% endfor -%}
{% endif -%}
{% if embedded_image_paths -%}
## Slides

{% for p in embedded_image_paths -%}
![]({{ p }})

{% endfor -%}
{% endif -%}
{% if transcript -%}
## Transcript

{% for seg in transcript -%}
- `[{{ format_ts(seg.start) }}]` {{ seg.text }}
{% endfor %}

{% endif -%}
{% if visible_frames -%}
## Frame Visuals

{% for f in visible_frames -%}
### {{ format_ts(f.timestamp) }}
{% if f.vision_description -%}
{{ f.vision_description }}

{% endif -%}
{% if f.ocr_text -%}
**Text in frame:**
```
{{ f.ocr_text }}
```

{% endif -%}
{% endfor -%}
{% endif -%}
"""


def render_lesson(inputs: LessonInputs) -> str:
    env = Environment(undefined=StrictUndefined, trim_blocks=False, lstrip_blocks=False)
    env.globals["format_ts"] = format_ts
    template = env.from_string(_TEMPLATE)
    visible_frames = [
        f for f in inputs.frame_visuals if f.ocr_text.strip() or f.vision_description.strip()
    ]
    media_type = (
        "video + images"
        if inputs.has_video and inputs.image_visuals
        else "video"
        if inputs.has_video
        else "image carousel"
    )
    return template.render(
        title=inputs.title,
        source_url=inputs.source_url,
        author=inputs.author,
        duration=format_ts(inputs.duration_seconds),
        processed_at=inputs.processed_at.strftime("%Y-%m-%d %H:%M %Z").strip(),
        processing_time=_format_processing_time(inputs.processing_seconds),
        has_video=inputs.has_video,
        media_type=media_type,
        music_title=inputs.music_title,
        post_text=inputs.post_text,
        coverage=inputs.coverage,
        summary=inputs.summary,
        key_points=inputs.key_points,
        tools_mentioned=inputs.tools_mentioned,
        code_snippets=inputs.code_snippets,
        transcript=inputs.transcript,
        visible_frames=visible_frames,
        embedded_image_paths=inputs.embedded_image_paths,
    )

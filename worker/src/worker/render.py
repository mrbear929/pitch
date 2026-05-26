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
class LessonInputs:
    source_url: str
    title: str
    duration_seconds: float
    processed_at: datetime
    processing_seconds: float
    transcript: list[TranscriptSegment]
    has_video: bool
    post_text: str = ""
    author: str = ""
    embedded_image_paths: list[str] = field(default_factory=list)
    coverage: Optional[str] = None
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

{% if post_text -%}
## Post

{{ post_text }}

{% endif -%}
{% if coverage -%}
## What this covers

{{ coverage }}

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
"""


def render_lesson(inputs: LessonInputs) -> str:
    env = Environment(undefined=StrictUndefined, trim_blocks=False, lstrip_blocks=False)
    env.globals["format_ts"] = format_ts
    template = env.from_string(_TEMPLATE)
    media_type = "video" if inputs.has_video else "image carousel"
    return template.render(
        title=inputs.title,
        source_url=inputs.source_url,
        author=inputs.author,
        duration=format_ts(inputs.duration_seconds),
        processed_at=inputs.processed_at.strftime("%Y-%m-%d %H:%M %Z").strip(),
        processing_time=_format_processing_time(inputs.processing_seconds),
        has_video=inputs.has_video,
        media_type=media_type,
        post_text=inputs.post_text,
        coverage=inputs.coverage,
        key_points=inputs.key_points,
        tools_mentioned=inputs.tools_mentioned,
        code_snippets=inputs.code_snippets,
        transcript=inputs.transcript,
        embedded_image_paths=inputs.embedded_image_paths,
    )

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
class FrameOcr:
    timestamp: float
    text: str  # may be empty


@dataclass
class LessonInputs:
    source_url: str
    title: str
    duration_seconds: float
    processed_at: datetime
    transcript: list[TranscriptSegment]
    frames: list[FrameOcr]
    summary: Optional[str] = None  # filled by LLM step (optional)
    key_points: list[str] = field(default_factory=list)
    tools_mentioned: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)


_TEMPLATE = """\
# {{ title }}

- **URL:** {{ source_url }}
- **Duration:** {{ duration }}
- **Processed:** {{ processed_at }}

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
## Code / Commands (from frames)

{% for s in code_snippets %}```
{{ s }}
```

{% endfor -%}
{% endif -%}
## Transcript

{% for seg in transcript -%}
- `[{{ format_ts(seg.start) }}]` {{ seg.text }}
{% endfor %}

{% if non_empty_frames -%}
## Frame OCR

{% for f in non_empty_frames -%}
### {{ format_ts(f.timestamp) }}
```
{{ f.text }}
```

{% endfor -%}
{% endif -%}
"""


def render_lesson(inputs: LessonInputs) -> str:
    env = Environment(undefined=StrictUndefined, trim_blocks=False, lstrip_blocks=False)
    env.globals["format_ts"] = format_ts
    template = env.from_string(_TEMPLATE)
    non_empty_frames = [f for f in inputs.frames if f.text.strip()]
    return template.render(
        title=inputs.title,
        source_url=inputs.source_url,
        duration=format_ts(inputs.duration_seconds),
        processed_at=inputs.processed_at.strftime("%Y-%m-%d %H:%M %Z").strip(),
        summary=inputs.summary,
        key_points=inputs.key_points,
        tools_mentioned=inputs.tools_mentioned,
        code_snippets=inputs.code_snippets,
        transcript=inputs.transcript,
        non_empty_frames=non_empty_frames,
    )

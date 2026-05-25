"""Pure helpers: slugify, timestamp formatting."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime


def format_ts(seconds: float) -> str:
    """Seconds -> 'mm:ss' or 'hh:mm:ss'."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def slugify(title: str, max_len: int = 60) -> str:
    """Title -> kebab-case slug. Strips Chinese/emoji to ASCII where possible.

    For all-Chinese titles where ASCII ends up empty, returns 'video' so we
    always produce a non-empty slug; the date prefix keeps filenames unique.
    """
    if not title:
        return "video"
    s = unicodedata.normalize("NFKD", title)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if not s:
        return "video"
    return s[:max_len].rstrip("-") or "video"


def filename_for(d: date, title: str) -> str:
    return f"{d.isoformat()}-{slugify(title)}.md"


def parse_iso_date(value: str | datetime | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            pass
    return datetime.now().date()

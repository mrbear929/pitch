"""Concrete pipeline implementations.

Stack:
- yt-dlp / Douyin share-page scraper for fetch.
- ffmpeg for audio extract.
- Groq Whisper API for transcription.
- Gemini Files API + Flash model for video understanding (replaces local
  frame-sampling, OCR, vision LLM, and text summarization).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx

from .pipeline import (
    AudioExtractor,
    FetchError,
    Fetcher,
    MediaBundle,
    Transcriber,
    VideoUnderstander,
)
from .render import TranscriptSegment

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fetcher chain — unchanged from prior versions.
# ---------------------------------------------------------------------------

class CompositeFetcher(Fetcher):
    """Try fetchers in order; first that doesn't raise FetchError wins."""

    def __init__(self, fetchers: list[Fetcher]) -> None:
        if not fetchers:
            raise ValueError("CompositeFetcher needs at least one fetcher")
        self.fetchers = fetchers

    def fetch(self, url: str, work_dir: Path) -> MediaBundle:
        last_err: FetchError | None = None
        for f in self.fetchers:
            try:
                return f.fetch(url, work_dir)
            except FetchError as e:
                log.info("fetcher %s declined: %s", type(f).__name__, e)
                last_err = e
                continue
        assert last_err is not None
        raise last_err


_DOUYIN_VIDEO_ID = re.compile(r"douyin\.com/(?:video|note)/(\d+)")
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def _extract_douyin_id(url: str) -> str | None:
    parsed = urlparse(url)
    if "douyin" not in parsed.netloc and "iesdouyin" not in parsed.netloc:
        return None
    m = _DOUYIN_VIDEO_ID.search(url)
    if m:
        return m.group(1)
    qs = parse_qs(parsed.query)
    if "modal_id" in qs and qs["modal_id"][0].isdigit():
        return qs["modal_id"][0]
    if "/share/video/" in parsed.path:
        tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if tail.isdigit():
            return tail
    return None


class DouyinFetcher(Fetcher):
    """Pulls media info from iesdouyin.com share pages. No auth, no cookies."""

    SHARE = "https://www.iesdouyin.com/share/video/{id}/"

    def fetch(self, url: str, work_dir: Path) -> MediaBundle:
        aweme_id = _extract_douyin_id(url)
        if not aweme_id:
            raise FetchError(
                f"DouyinFetcher: not a Douyin URL: {url}",
                "Worker chain skipped Douyin scraper because URL didn't look like one.",
            )
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as c:
                r = c.get(self.SHARE.format(id=aweme_id), headers={"User-Agent": _MOBILE_UA})
            r.raise_for_status()
            html = r.text
        except httpx.HTTPError as e:
            raise FetchError(
                f"DouyinFetcher: share-page fetch failed: {e}",
                "Couldn't reach the Douyin share page. Try again in a minute.",
            ) from e

        info = self._parse_share_html(html)
        if not info:
            raise FetchError(
                "DouyinFetcher: share page didn't contain recognizable media",
                "Douyin returned an unrecognized response. Post may be deleted, "
                "private, or the share-page format may have changed.",
            )

        post_text = (info.get("desc") or "").strip()
        music_title = (info.get("music_title") or "").strip()
        author = (info.get("author") or "").strip()

        title = self._title_from(post_text, author, music_title, aweme_id)

        if info.get("image_urls"):
            image_paths = self._download_images(info["image_urls"], aweme_id, work_dir)
            return MediaBundle(
                title=title,
                image_paths=image_paths,
                post_text=post_text,
                author=author,
                music_title=music_title,
            )

        if info.get("play_url"):
            video_path = self._download_video(info["play_url"], aweme_id, work_dir)
            return MediaBundle(
                title=title,
                video_path=video_path,
                duration_seconds=float(info.get("duration") or 0.0),
                post_text=post_text,
                author=author,
                music_title=music_title,
            )

        raise FetchError(
            "DouyinFetcher: share page parsed but no media found",
            "Douyin returned a response we couldn't classify as video or images.",
        )

    @staticmethod
    def _title_from(post_text: str, author: str, music_title: str, aweme_id: str) -> str:
        if post_text:
            first_line = post_text.splitlines()[0].strip()
            first_line = re.sub(r"\s*#\S+(\s+#\S+)*\s*$", "", first_line).strip()
            if first_line:
                return first_line[:80]
        if music_title:
            return music_title
        if author:
            return f"{author} 的帖子"
        return f"douyin-{aweme_id}"

    def _download_video(self, play_url: str, aweme_id: str, work_dir: Path) -> Path:
        media_path = work_dir / f"{aweme_id}.mp4"
        try:
            with httpx.Client(timeout=180.0, follow_redirects=True) as c:
                with c.stream("GET", play_url, headers={"User-Agent": _MOBILE_UA}) as resp:
                    resp.raise_for_status()
                    with open(media_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                            f.write(chunk)
        except httpx.HTTPError as e:
            raise FetchError(
                f"DouyinFetcher: video download failed: {e}",
                "Could resolve the Douyin video but the download failed.",
            ) from e
        if media_path.stat().st_size < 1024:
            raise FetchError(
                "DouyinFetcher: downloaded file is implausibly small",
                "Got a tiny file from Douyin — likely an error page.",
            )
        return media_path

    def _download_images(self, urls: list[str], aweme_id: str, work_dir: Path) -> list[Path]:
        out: list[Path] = []
        for i, image_url in enumerate(urls):
            target = work_dir / f"{aweme_id}-{i:02d}.jpg"
            try:
                with httpx.Client(timeout=60.0, follow_redirects=True) as c:
                    resp = c.get(image_url, headers={"User-Agent": _MOBILE_UA})
                resp.raise_for_status()
                target.write_bytes(resp.content)
            except httpx.HTTPError:
                log.warning("image %d/%d failed; skipping", i + 1, len(urls))
                continue
            if target.stat().st_size < 200:
                continue
            out.append(target)
        if not out:
            raise FetchError(
                "DouyinFetcher: all images failed to download",
                "Found image carousel but couldn't download any image. Try again later.",
            )
        return out

    @staticmethod
    def _parse_share_html(html: str) -> dict | None:
        desc = DouyinFetcher._unescape(
            re.search(r'"desc":\s*("(?:[^"\\]|\\.){1,2000}")', html)
        )
        author = DouyinFetcher._unescape(
            re.search(r'"author":\{[^}]{0,2000}?"nickname":\s*("(?:[^"\\]|\\.){1,200}")', html)
        )
        music_title = DouyinFetcher._unescape(
            re.search(r'"music":\{[^}]{0,2000}?"title":\s*("(?:[^"\\]|\\.){1,400}")', html)
        )

        aweme_type_m = re.search(r'"aweme_type":(\d+)', html)
        is_images = bool(aweme_type_m) and aweme_type_m.group(1) == "2"

        out: dict = {"desc": desc, "author": author, "music_title": music_title}

        if is_images:
            image_urls = DouyinFetcher._parse_image_urls(html)
            if image_urls:
                out["image_urls"] = image_urls
                return out

        dur_m = re.search(r'"duration":(\d+)', html)
        duration = int(dur_m.group(1)) / 1000.0 if dur_m else 0.0

        url_m = re.search(
            r'"play_addr":\{[^}]*?"url_list":\[(.*?)\]',
            html,
            re.DOTALL,
        )
        if url_m:
            list_blob = url_m.group(1)
            play_url_m = re.search(r'"(https[^"]+)"', list_blob)
            if play_url_m:
                out["play_url"] = json.loads('"' + play_url_m.group(1) + '"')
                out["duration"] = duration
                return out
        return None if not desc else out

    @staticmethod
    def _parse_image_urls(html: str) -> list[str]:
        seen_uris: set[str] = set()
        urls: list[str] = []
        for m in re.finditer(r'"images":\[', html):
            tail = html[m.end():]
            for slide_m in re.finditer(
                r'\{"uri":"([^"]*)","url_list":\[(.*?)\]',
                tail,
                re.DOTALL,
            ):
                if slide_m.start() > 20_000:
                    break
                uri = slide_m.group(1)
                if uri in seen_uris:
                    continue
                u_m = re.search(r'"(https[^"]+)"', slide_m.group(2))
                if u_m:
                    seen_uris.add(uri)
                    urls.append(json.loads('"' + u_m.group(1) + '"'))
        return urls

    @staticmethod
    def _unescape(m: re.Match | None) -> str:
        if not m:
            return ""
        try:
            return json.loads(m.group(1))
        except (ValueError, json.JSONDecodeError):
            return ""


class YtDlpFetcher(Fetcher):
    """yt-dlp for non-Douyin URLs."""

    def fetch(self, url: str, work_dir: Path) -> MediaBundle:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError

        out_template = str(work_dir / "%(id)s.%(ext)s")
        opts = {
            "outtmpl": out_template,
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except DownloadError as e:
            msg = str(e)
            guidance = self._guidance_for(url, msg)
            raise FetchError(msg, guidance) from e

        media_path = Path(ydl.prepare_filename(info))
        if not media_path.exists():
            raise FetchError("yt-dlp finished but file missing", "Try uploading the file manually.")
        return MediaBundle(
            title=info.get("title") or media_path.stem,
            video_path=media_path,
            duration_seconds=float(info.get("duration") or 0.0),
        )

    @staticmethod
    def _guidance_for(url: str, err: str) -> str:
        if "douyin" in url or "iesdouyin" in url:
            return (
                "Couldn't fetch the Douyin video automatically. "
                "Save the video on your phone and AirDrop to your Mac."
            )
        return f"Couldn't fetch the video: {err[:200]}."


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

class FfmpegAudioExtractor(AudioExtractor):
    def extract(self, video_path: Path, work_dir: Path) -> Path:
        out = work_dir / f"{video_path.stem}.16k.wav"
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")
        return out


# ---------------------------------------------------------------------------
# Transcription via Groq Whisper API
# ---------------------------------------------------------------------------

class GroqTranscriber(Transcriber):
    """Calls Groq's hosted Whisper. ~200x faster than local whisper.cpp.

    Free tier: rate-limited but generous (currently ~7,200 audio-seconds/min).
    Returns the same TranscriptSegment shape as the local transcriber so the
    rest of the pipeline doesn't care.
    """

    URL = "https://api.groq.com/openai/v1/audio/transcriptions"
    MODEL = "whisper-large-v3-turbo"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("GroqTranscriber requires a non-empty API key")
        self.api_key = api_key

    def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        files = {
            "file": (audio_path.name, audio_path.read_bytes(), "audio/wav"),
        }
        data = {
            "model": self.MODEL,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
        with httpx.Client(timeout=300.0) as c:
            r = c.post(
                self.URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                files=files,
                data=data,
            )
        r.raise_for_status()
        body = r.json()

        segments_raw = body.get("segments") or []
        out: list[TranscriptSegment] = []
        for seg in segments_raw:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            out.append(
                TranscriptSegment(
                    start=float(seg.get("start") or 0.0),
                    end=float(seg.get("end") or 0.0),
                    text=text,
                )
            )
        # Fallback if Groq returns plain text only (rare).
        if not out:
            text = (body.get("text") or "").strip()
            if text:
                out.append(TranscriptSegment(start=0.0, end=0.0, text=text))
        return out


# ---------------------------------------------------------------------------
# Video understanding via Gemini Files API
# ---------------------------------------------------------------------------

class GeminiVideoUnderstander(VideoUnderstander):
    """Uploads a video to Gemini's Files API and asks for structured output.

    Why this replaces our previous frame-sampling pipeline:
      Gemini ingests the video natively, gets temporal context, and produces
      a coverage paragraph + key points + tools + code in one round trip.
      No local frame extraction, no OCR, no per-frame vision calls.

    Free tier: generous. Files live for 48 hours then expire.
    """

    UPLOAD_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
    MODEL_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        if not api_key:
            raise ValueError("GeminiVideoUnderstander requires a non-empty API key")
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL

    def understand(
        self,
        video_path: Path,
        transcript: list[TranscriptSegment],
        post_text: str = "",
        author: str = "",
    ) -> dict:
        file_uri, mime_type = self._upload_and_wait(video_path)
        prompt = self._build_prompt(transcript, post_text, author)

        url = self.MODEL_URL.format(model=self.model) + f"?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"file_data": {"mime_type": mime_type, "file_uri": file_uri}},
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "coverage": {"type": "STRING"},
                        "key_points": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "tools_mentioned": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "code_snippets": {"type": "ARRAY", "items": {"type": "STRING"}},
                    },
                    "required": ["coverage", "key_points", "tools_mentioned", "code_snippets"],
                },
            },
        }
        with httpx.Client(timeout=600.0) as c:
            r = c.post(url, json=payload)
        r.raise_for_status()
        body = r.json()

        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            log.warning("Gemini returned unparseable response: %s", e)
            return {}

    # ----- Files API helpers -----

    def _upload_and_wait(self, video_path: Path) -> tuple[str, str]:
        """Upload the video, wait for it to leave PROCESSING state, return
        (file_uri, mime_type) ready to reference in a generateContent call."""
        size = video_path.stat().st_size
        mime_type = "video/mp4"

        # Step 1: start a resumable upload session.
        start_url = self.UPLOAD_URL + f"?key={self.api_key}"
        with httpx.Client(timeout=60.0) as c:
            init = c.post(
                start_url,
                headers={
                    "X-Goog-Upload-Protocol": "resumable",
                    "X-Goog-Upload-Command": "start",
                    "X-Goog-Upload-Header-Content-Length": str(size),
                    "X-Goog-Upload-Header-Content-Type": mime_type,
                    "Content-Type": "application/json",
                },
                json={"file": {"display_name": video_path.name}},
            )
        init.raise_for_status()
        upload_url = init.headers.get("X-Goog-Upload-URL") or init.headers.get(
            "x-goog-upload-url"
        )
        if not upload_url:
            raise RuntimeError("Gemini upload init returned no upload URL")

        # Step 2: upload the bytes in one shot.
        with httpx.Client(timeout=600.0) as c:
            up = c.post(
                upload_url,
                headers={
                    "Content-Length": str(size),
                    "X-Goog-Upload-Offset": "0",
                    "X-Goog-Upload-Command": "upload, finalize",
                },
                content=video_path.read_bytes(),
            )
        up.raise_for_status()
        meta = up.json().get("file") or {}
        file_uri = meta.get("uri")
        file_name = meta.get("name")
        state = meta.get("state")
        if not file_uri or not file_name:
            raise RuntimeError(f"Gemini upload returned no uri/name: {up.text[:300]}")

        # Step 3: poll until ACTIVE (videos go through PROCESSING first).
        poll_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={self.api_key}"
        deadline = time.monotonic() + 180
        while state == "PROCESSING":
            if time.monotonic() > deadline:
                raise RuntimeError("Gemini file stayed in PROCESSING for >3 min")
            time.sleep(2)
            with httpx.Client(timeout=30.0) as c:
                p = c.get(poll_url)
            p.raise_for_status()
            file_meta = p.json()
            state = file_meta.get("state")
        if state != "ACTIVE":
            raise RuntimeError(f"Gemini file ended in state={state}")
        return file_uri, mime_type

    @staticmethod
    def _build_prompt(
        transcript: list[TranscriptSegment], post_text: str, author: str
    ) -> str:
        transcript_text = "\n".join(f"[{seg.start:.0f}s] {seg.text}" for seg in transcript)[:8000]
        parts = [
            "You are summarizing a short tech / vibe-coding video for a "
            "developer's knowledge base. The user will read your output to "
            "decide whether to watch the full video.",
            "",
            "Output JSON only. Match the source's language (Chinese in → Chinese out).",
            "",
            "Fields:",
            "- coverage: one paragraph (3-6 sentences) describing what this "
            "video covers. Concrete topics, claims, demonstrations.",
            "- key_points: actionable bullets, max ~15 words each.",
            "- tools_mentioned: tool/product names shown or named.",
            "- code_snippets: short exact code or commands shown on screen.",
            "",
            "Empty arrays are fine when nothing applies.",
        ]
        if post_text:
            parts.append("\nPOST TEXT (creator's caption):\n" + post_text[:2000])
        if author:
            parts.append("\nAUTHOR: " + author)
        if transcript_text:
            parts.append("\nTRANSCRIPT (timestamps in seconds):\n" + transcript_text)
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Default pipeline factory
# ---------------------------------------------------------------------------

def make_default_pipeline(config):  # noqa: ANN001
    from .pipeline import Pipeline

    return Pipeline(
        fetcher=CompositeFetcher([DouyinFetcher(), YtDlpFetcher()]),
        audio=FfmpegAudioExtractor(),
        transcriber=GroqTranscriber(config.groq_api_key),
        understander=GeminiVideoUnderstander(config.gemini_api_key),
    )

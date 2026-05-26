"""Concrete pipeline implementations using yt-dlp, ffmpeg, whisper.cpp, tesseract, ollama."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx

from .pipeline import (
    AudioExtractor,
    FetchError,
    Fetcher,
    FrameSampler,
    OcrRunner,
    Transcriber,
    Understander,
    VideoMeta,
)
from .render import FrameOcr, TranscriptSegment

log = logging.getLogger(__name__)


# ---- Fetcher chain ----

class CompositeFetcher(Fetcher):
    """Try fetchers in order. First one that doesn't raise FetchError wins.

    A fetcher that doesn't recognize the URL should raise FetchError; the next
    fetcher gets a turn. When the chain is exhausted, the last error is raised.
    """

    def __init__(self, fetchers: list[Fetcher]) -> None:
        if not fetchers:
            raise ValueError("CompositeFetcher needs at least one fetcher")
        self.fetchers = fetchers

    def fetch(self, url: str, work_dir: Path) -> VideoMeta:
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
    """Pull the numeric aweme_id from any supported Douyin URL form."""
    parsed = urlparse(url)
    if "douyin" not in parsed.netloc and "iesdouyin" not in parsed.netloc:
        return None
    m = _DOUYIN_VIDEO_ID.search(url)
    if m:
        return m.group(1)
    # /jingxuan?modal_id=<id>
    qs = parse_qs(parsed.query)
    if "modal_id" in qs and qs["modal_id"][0].isdigit():
        return qs["modal_id"][0]
    # /share/video/<id>/
    if "/share/video/" in parsed.path:
        tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if tail.isdigit():
            return tail
    return None


class DouyinFetcher(Fetcher):
    """Pulls video info from the iesdouyin.com share page (no auth, no cookies).

    The share-page HTML embeds a JSON island that includes the unwatermarked
    playback URL and the original title/duration. We parse the relevant fields
    directly — robust enough for the formats we care about, and dependency-free.
    """

    SHARE = "https://www.iesdouyin.com/share/video/{id}/"

    def fetch(self, url: str, work_dir: Path) -> VideoMeta:
        aweme_id = _extract_douyin_id(url)
        if not aweme_id:
            raise FetchError(
                f"DouyinFetcher: not a Douyin URL: {url}",
                "Worker chain skipped Douyin scraper because the URL didn't look like one.",
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
                "DouyinFetcher: share page didn't contain a video URL",
                "Douyin returned an unrecognized response. The post may be deleted, "
                "private, or the share-page format may have changed.",
            )

        play_url = info["play_url"]
        title = info.get("title") or f"douyin-{aweme_id}"
        duration = float(info.get("duration") or 0.0)

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
                f"DouyinFetcher: download failed: {e}",
                "Could resolve the Douyin video but the download failed. "
                "Save the video on your phone and use 'Pitch: Upload Local File' (v0.2).",
            ) from e

        if media_path.stat().st_size < 1024:
            raise FetchError(
                "DouyinFetcher: downloaded file is implausibly small",
                "Got a tiny file from Douyin — likely an error page. Try again later.",
            )
        return VideoMeta(title=title, duration_seconds=duration, media_path=media_path)

    @staticmethod
    def _parse_share_html(html: str) -> dict | None:
        # The HTML embeds a JSON island whose strings use \uXXXX escapes for CJK.
        # We unescape with json.loads on quoted-string fragments to round-trip
        # the codepoints correctly.
        title_m = re.search(r'"title":\s*("(?:[^"\\]|\\.){1,400}")', html)
        title = json.loads(title_m.group(1)) if title_m else None

        dur_m = re.search(r'"duration":(\d+)', html)
        duration = int(dur_m.group(1)) / 1000.0 if dur_m else 0.0

        url_m = re.search(
            r'"play_addr":\{[^}]*?"url_list":\[(.*?)\]',
            html,
            re.DOTALL,
        )
        if not url_m:
            return None
        list_blob = url_m.group(1)
        play_url_m = re.search(r'"(https[^"]+)"', list_blob)
        if not play_url_m:
            return None
        # Same trick: re-quote and json-load to handle / and \uXXXX.
        play_url = json.loads('"' + play_url_m.group(1) + '"')
        return {"play_url": play_url, "title": title, "duration": duration}


class YtDlpFetcher(Fetcher):
    """Uses the yt-dlp Python library."""

    def fetch(self, url: str, work_dir: Path) -> VideoMeta:
        from yt_dlp import YoutubeDL  # lazy: keep import optional for tests
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

        media_path = Path(ydl.prepare_filename(info))  # type: ignore[arg-type]
        if not media_path.exists():
            raise FetchError("yt-dlp finished but file missing", "Try uploading the file manually.")
        return VideoMeta(
            title=info.get("title") or media_path.stem,
            duration_seconds=float(info.get("duration") or 0.0),
            media_path=media_path,
        )

    @staticmethod
    def _guidance_for(url: str, err: str) -> str:
        if "douyin" in url or "iesdouyin" in url:
            return (
                "Couldn't fetch the Douyin video automatically. "
                "Open it in your phone, save the video, AirDrop it to your Mac, "
                "and use 'Pitch: Upload Local File' in Obsidian."
            )
        return f"Couldn't fetch the video: {err[:200]}. Try uploading the file manually."


# ---- Audio ----

class FfmpegAudioExtractor(AudioExtractor):
    def extract(self, video_path: Path, work_dir: Path) -> Path:
        out = work_dir / f"{video_path.stem}.16k.wav"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")
        return out


# ---- Transcribe ----

class WhisperCppTranscriber(Transcriber):
    """Calls the `whisper-cli` binary from whisper.cpp.

    Whisper.cpp's CLI emits JSON when given `--output-json`. We parse segments.
    """

    def __init__(self, whisper_bin: str, model_path: str) -> None:
        self.whisper_bin = whisper_bin
        self.model_path = model_path

    def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        out_prefix = audio_path.with_suffix("")
        cmd = [
            self.whisper_bin,
            "-m",
            self.model_path,
            "-f",
            str(audio_path),
            "-l",
            "auto",
            "-oj",
            "-of",
            str(out_prefix),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"whisper failed: {proc.stderr[-500:]}")
        json_path = Path(str(out_prefix) + ".json")
        if not json_path.exists():
            raise RuntimeError("whisper produced no JSON output")
        data = json.loads(json_path.read_text())
        # whisper.cpp JSON: {"transcription": [{"offsets": {"from": ms, "to": ms}, "text": "..."}, ...]}
        out: list[TranscriptSegment] = []
        for seg in data.get("transcription", []):
            ts = seg.get("offsets") or {}
            start = float(ts.get("from", 0)) / 1000.0
            end = float(ts.get("to", 0)) / 1000.0
            text = (seg.get("text") or "").strip()
            if text:
                out.append(TranscriptSegment(start=start, end=end, text=text))
        return out


# ---- Frame sampling ----

class FfmpegFrameSampler(FrameSampler):
    def sample(self, video_path: Path, work_dir: Path, every_seconds: int) -> list[tuple[float, Path]]:
        frames_dir = work_dir / "frames"
        frames_dir.mkdir(exist_ok=True)
        # Use fps=1/every_seconds. Output: frame-001.jpg, frame-002.jpg, ...
        out_pattern = frames_dir / "frame-%04d.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/{every_seconds}",
            "-q:v",
            "3",
            str(out_pattern),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg frame sample failed: {proc.stderr[-500:]}")
        result: list[tuple[float, Path]] = []
        for i, p in enumerate(sorted(frames_dir.glob("frame-*.jpg"))):
            result.append((float(i * every_seconds), p))
        return result


# ---- OCR ----

class TesseractOcrRunner(OcrRunner):
    def __init__(self, langs: str = "eng+chi_sim") -> None:
        self.langs = langs

    def run(self, image_path: Path) -> str:
        proc = subprocess.run(
            ["tesseract", str(image_path), "-", "-l", self.langs],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            log.warning("tesseract failed on %s: %s", image_path, proc.stderr[-200:])
            return ""
        return self._clean(proc.stdout)

    @staticmethod
    def _clean(text: str) -> str:
        # Drop very short lines (likely garbage). Keep code-ish lines.
        lines = [ln.rstrip() for ln in text.splitlines()]
        kept = [ln for ln in lines if len(ln.strip()) >= 2]
        return "\n".join(kept).strip()


# ---- Understanding (optional, local Ollama) ----

OLLAMA_PROMPT = """\
You will receive a transcript of a vibe-coding tutorial video and OCR text from key frames.

Output VALID JSON only. No prose, no markdown fences.

Schema:
{
  "summary": "<2-3 sentence summary>",
  "key_points": ["<bullet>", ...],
  "tools_mentioned": ["<name>", ...],
  "code_snippets": ["<short code or command>", ...]
}

If the content is sparse, use empty arrays. Always return all four keys.

TRANSCRIPT:
"""


class OllamaUnderstander(Understander):
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def understand(
        self, transcript: list[TranscriptSegment], frames: list[FrameOcr]
    ) -> dict:
        transcript_text = "\n".join(seg.text for seg in transcript)[:12000]
        ocr_text = "\n---\n".join(f.text for f in frames if f.text.strip())[:6000]
        prompt = OLLAMA_PROMPT + transcript_text + "\n\nOCR TEXT:\n" + ocr_text

        try:
            with httpx.Client(timeout=300.0) as c:
                r = c.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
            r.raise_for_status()
            body = r.json()
            return self._parse(body.get("response", "{}"))
        except Exception as e:
            log.warning("ollama understand failed: %s", e)
            return {}

    @staticmethod
    def _parse(raw: str) -> dict:
        # Ollama with format=json should give pure JSON, but guard anyway.
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    return {}
            return {}


def make_default_pipeline(config):  # noqa: ANN001
    from .pipeline import Pipeline

    return Pipeline(
        fetcher=CompositeFetcher([DouyinFetcher(), YtDlpFetcher()]),
        audio=FfmpegAudioExtractor(),
        transcriber=WhisperCppTranscriber(config.whisper_bin, config.whisper_model),
        frames=FfmpegFrameSampler(),
        ocr=TesseractOcrRunner(),
        understander=OllamaUnderstander(config.ollama_url, config.ollama_model),
    )

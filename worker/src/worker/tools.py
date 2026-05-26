"""Concrete pipeline implementations using yt-dlp, ffmpeg, whisper.cpp, tesseract, ollama."""
from __future__ import annotations

import base64
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
    MediaBundle,
    OcrRunner,
    Transcriber,
    Understander,
    VisionAnalyzer,
)
from .render import FrameVisual, ImageVisual, TranscriptSegment

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
    """Pulls media info from the iesdouyin.com share page (no auth, no cookies).

    Handles both video posts and image-carousel posts ("note" / aweme_type=2).
    The share-page HTML embeds a JSON island; we parse the relevant fields directly.
    """

    SHARE = "https://www.iesdouyin.com/share/video/{id}/"

    def fetch(self, url: str, work_dir: Path) -> MediaBundle:
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
                "DouyinFetcher: share page didn't contain recognizable media",
                "Douyin returned an unrecognized response. The post may be deleted, "
                "private, or the share-page format may have changed.",
            )

        title = info.get("title") or f"douyin-{aweme_id}"

        # Image-carousel post.
        if info.get("image_urls"):
            image_paths = self._download_images(info["image_urls"], aweme_id, work_dir)
            return MediaBundle(title=title, image_paths=image_paths)

        # Video post.
        if info.get("play_url"):
            video_path = self._download_video(info["play_url"], aweme_id, work_dir)
            return MediaBundle(
                title=title,
                video_path=video_path,
                duration_seconds=float(info.get("duration") or 0.0),
            )

        raise FetchError(
            "DouyinFetcher: share page parsed but no media found",
            "Douyin returned a response we couldn't classify as video or images.",
        )

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
                "Could resolve the Douyin video but the download failed. Try again later.",
            ) from e
        if media_path.stat().st_size < 1024:
            raise FetchError(
                "DouyinFetcher: downloaded file is implausibly small",
                "Got a tiny file from Douyin — likely an error page. Try again later.",
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
                log.warning("image %d/%d implausibly small; skipping", i + 1, len(urls))
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
        # The HTML embeds a JSON island whose strings use \uXXXX escapes for CJK.
        # We unescape with json.loads on quoted-string fragments to round-trip
        # the codepoints correctly.
        title_m = re.search(r'"title":\s*("(?:[^"\\]|\\.){1,400}")', html)
        title = json.loads(title_m.group(1)) if title_m else None

        # Detect image-carousel posts (aweme_type=2).
        aweme_type_m = re.search(r'"aweme_type":(\d+)', html)
        is_images = bool(aweme_type_m) and aweme_type_m.group(1) == "2"

        if is_images:
            image_urls = DouyinFetcher._parse_image_urls(html)
            if image_urls:
                return {"title": title, "image_urls": image_urls}
            # Fall through — sometimes posts marked aweme_type=2 still have a
            # video. Try the video path before giving up.

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
                play_url = json.loads('"' + play_url_m.group(1) + '"')
                return {
                    "title": title,
                    "play_url": play_url,
                    "duration": duration,
                }
        return None

    @staticmethod
    def _parse_image_urls(html: str) -> list[str]:
        """Walk every slide ({"uri":"...","url_list":[...]}) under "images":[.

        Different size variants of the same image share the same `uri` field
        but differ in URL — we dedupe on `uri` so we only download each slide
        once, and pick the largest-looking URL (first in the url_list).
        """
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


class YtDlpFetcher(Fetcher):
    """Uses the yt-dlp Python library. Video posts only — no carousel support."""

    def fetch(self, url: str, work_dir: Path) -> MediaBundle:
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
You are converting a vibe-coding/tech post into a structured engineering note.
You will receive: a spoken transcript (may be empty for image-only posts),
visual descriptions of key frames or carousel images, and OCR text.

Output VALID JSON only. No prose, no markdown fences.

Schema:
{
  "summary": "<2-3 sentence summary>",
  "key_points": ["<bullet>", ...],
  "tools_mentioned": ["<name>", ...],
  "code_snippets": ["<short code or command, exact text>", ...]
}

If the content is sparse, use empty arrays. Always return all four keys.

"""


class OllamaUnderstander(Understander):
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def understand(
        self,
        transcript: list[TranscriptSegment],
        frame_visuals: list[FrameVisual],
        image_visuals: list[ImageVisual],
    ) -> dict:
        transcript_text = "\n".join(seg.text for seg in transcript)[:10000]
        frame_text = "\n\n".join(self._frame_block(f) for f in frame_visuals)[:6000]
        image_text = "\n\n".join(self._image_block(i) for i in image_visuals)[:6000]

        prompt_parts = [OLLAMA_PROMPT]
        if transcript_text:
            prompt_parts.append("TRANSCRIPT:\n" + transcript_text)
        if frame_text:
            prompt_parts.append("FRAME VISUALS:\n" + frame_text)
        if image_text:
            prompt_parts.append("CAROUSEL IMAGES:\n" + image_text)
        prompt = "\n\n".join(prompt_parts)

        try:
            with httpx.Client(timeout=300.0) as c:
                r = c.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "keep_alive": "30m",
                    },
                )
            r.raise_for_status()
            body = r.json()
            return self._parse(body.get("response", "{}"))
        except Exception as e:
            log.warning("ollama understand failed: %s", e)
            return {}

    @staticmethod
    def _frame_block(f: FrameVisual) -> str:
        ts = format_ts(f.timestamp)  # noqa: F821 — provided below
        parts = [f"[{ts}]"]
        if f.vision_description:
            parts.append("vision: " + f.vision_description)
        if f.ocr_text:
            parts.append("ocr: " + f.ocr_text)
        return " ".join(parts)

    @staticmethod
    def _image_block(i: ImageVisual) -> str:
        parts = [f"[image {i.index + 1}]"]
        if i.vision_description:
            parts.append("vision: " + i.vision_description)
        if i.ocr_text:
            parts.append("ocr: " + i.ocr_text)
        return " ".join(parts)

    @staticmethod
    def _parse(raw: str) -> dict:
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


# ---- Vision (multimodal local LLM) ----

class OllamaVisionAnalyzer(VisionAnalyzer):
    """Describe an image's visual content via a local multimodal model.

    Uses Ollama's /api/generate with `images: [base64]`. The default prompt
    is tuned for vibe-coding posts — diagrams, screenshots, code, slides — but
    works fine on general scenes too.
    """

    DEFAULT_PROMPT = (
        "Describe what is shown in this image in 1-2 sentences. "
        "If you can read text, code, or commands, transcribe them verbatim. "
        "If it's a diagram, describe the structure. Be concrete, no fluff."
    )

    # Long edge passed to the vision model. Larger ⇒ more detail but slower.
    # 1024 keeps fine-grained text legible while cutting inference cost ~75%
    # vs typical Douyin source images (1860×2475).
    MAX_LONG_EDGE = 1024

    # Tell Ollama to keep the model resident this long after a call. Eliminates
    # cold-start on the next image / next job.
    KEEP_ALIVE = "30m"

    def __init__(self, base_url: str, model: str, prompt: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.prompt = prompt or self.DEFAULT_PROMPT

    def describe(self, image_path: Path) -> str:
        if not image_path.exists():
            return ""
        try:
            payload = self._encode_resized(image_path)
            # 10 min timeout — covers cold-start on first call. Steady-state
            # is ~10-20s per image once the model is warm.
            with httpx.Client(timeout=600.0) as c:
                r = c.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": self.prompt,
                        "images": [payload],
                        "stream": False,
                        "keep_alive": self.KEEP_ALIVE,
                    },
                )
            r.raise_for_status()
            body = r.json()
            return (body.get("response") or "").strip()
        except Exception as e:
            log.warning("vision describe failed for %s: %s", image_path.name, e)
            return ""

    def _encode_resized(self, image_path: Path) -> str:
        """Resize the image so its long edge is MAX_LONG_EDGE, re-encode as JPEG.

        Reasons:
          1. Faster vision inference — far fewer tokens for the model to process.
          2. Ollama's vision endpoint takes JPEG/PNG; some Douyin images are .webp
             with broken metadata that can confuse the model. Re-encoding
             normalizes everything to safe JPEG.
        """
        try:
            from PIL import Image
        except ImportError:
            # Fallback: send raw bytes if Pillow isn't installed.
            return base64.b64encode(image_path.read_bytes()).decode("ascii")
        from io import BytesIO

        img = Image.open(image_path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        long_edge = max(img.size)
        if long_edge > self.MAX_LONG_EDGE:
            scale = self.MAX_LONG_EDGE / long_edge
            new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
            img = img.resize(new_size, Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("ascii")


# Re-export format_ts for OllamaUnderstander._frame_block.
from .text import format_ts  # noqa: E402


def make_default_pipeline(config):  # noqa: ANN001
    from .pipeline import Pipeline

    vision_model = getattr(config, "vision_model", "") or ""
    vision = (
        OllamaVisionAnalyzer(config.ollama_url, vision_model) if vision_model else None
    )
    return Pipeline(
        fetcher=CompositeFetcher([DouyinFetcher(), YtDlpFetcher()]),
        audio=FfmpegAudioExtractor(),
        transcriber=WhisperCppTranscriber(config.whisper_bin, config.whisper_model),
        frames=FfmpegFrameSampler(),
        ocr=TesseractOcrRunner(),
        vision=vision,
        understander=OllamaUnderstander(config.ollama_url, config.ollama_model),
    )

"""Concrete pipeline implementations using yt-dlp, ffmpeg, whisper.cpp, tesseract, ollama."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

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


# ---- Fetcher ----

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
        fetcher=YtDlpFetcher(),
        audio=FfmpegAudioExtractor(),
        transcriber=WhisperCppTranscriber(config.whisper_bin, config.whisper_model),
        frames=FfmpegFrameSampler(),
        ocr=TesseractOcrRunner(),
        understander=OllamaUnderstander(config.ollama_url, config.ollama_model),
    )

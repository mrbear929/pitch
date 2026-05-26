# Pitch — PRD

> Code name: **Pitch**. May be renamed at commercial release.
> Last updated: 2026-05-25.

## Problem

Long-form vibe-coding videos (15–60 min, often Mandarin Douyin or YouTube) hold useful technique — claims about tools, prompts, command snippets, workflows — but cost too much attention to watch. Bear keeps an Obsidian second brain. He needs a low-friction path: **one video link → one digestible note in the vault**, without reaching for any other tool.

## Users

Bear, on macOS, working in Obsidian. No multi-user support in MVP.

## Goals

1. **Capture from anywhere.** Submitting a URL works from any machine that can reach the internet — phone, work laptop, Obsidian on the desktop. Submission is decoupled from processing.
2. **Zero recurring cost.** No paid APIs (no OpenAI, no Anthropic, no transcription services). Reuse the EC2 instance Bear already runs for `tools.mrbear929.com`. Heavy compute runs on Bear's existing Mac.
3. **Ship something usable in a session.** Not a research project. The first version had to install, deploy, and ingest a real video the same day.
4. **Source-of-truth output.** The product is the *output format*, not the plugin chrome. A 30-min video should produce a note Bear can skim in <3 min and decide whether to watch the full video.

## Non-goals (MVP)

- Vault-aware proposal generation, conflict detection, approval workflow. Deferred to Phase 2 once Phase 1 has been used 3–5 times.
- Mobile-native UI, Slack/Raycast/iOS Shortcut integrations.
- Batch processing, scheduled ingest, watch folders.
- Submission to the Obsidian community plugin store. Distribution is via BRAT (GitHub releases).
- Support for arbitrary social platforms. MVP supports Douyin (via custom scraper) and anything yt-dlp handles natively (YouTube, Bilibili, etc.).

## Success criteria

A run is successful if **all** of these hold for one Douyin video:

1. Bear submits a URL via the Obsidian plugin command.
2. Within ~5 minutes, a markdown note appears at `_todo/ideas/vibe-coding/<YYYY-MM-DD>-<slug>.md`.
3. The note contains: source URL, title, duration, processed timestamp, full timestamped transcript, OCR'd text from sampled frames (mostly the code/commands shown on screen), and — when the local LLM is up — a structured summary + key points + tools mentioned.
4. Bear can read the note in under 3 minutes and decide whether the video was worth watching in full.
5. No vault content is sent to any external system.
6. No paid API was called.

## Architecture (one-paragraph version)

Three components: **plugin** in Obsidian (the only UI Bear sees), a tiny **dispatcher** on EC2 (just a queue and an auth gate), and a **worker** daemon on Bear's Mac (does all the heavy lifting). Plugin POSTs a URL to the dispatcher; Mac worker long-polls the dispatcher for pending jobs; when a job exists, the worker downloads the video, transcribes audio, OCRs sampled frames, runs a local LLM on the transcript+OCR for structure, posts the rendered markdown back to the dispatcher; plugin's polling sees `done`, fetches the markdown, writes it to the vault.

The dispatcher exists for one reason: **decouple submission from processing**, so Bear can paste a URL from anywhere and the Mac handles it whenever it's awake.

## Why this design

| Decision | Why |
|---|---|
| 3-component instead of 1 | Submission must work even when the Mac is off. The dispatcher is the always-on rendezvous point. |
| Dispatcher on shared EC2, not new infra | Free. Reuses the box already serving `tools.mrbear929.com`. Tiny memory footprint (queue API, ~100 MB). |
| Worker on Mac, not EC2 | The EC2 box has 957 MB RAM and 1 vCPU — too small for Whisper. The Mac has 16 GB and an M4. Free. |
| Custom Douyin scraper, not yt-dlp's | yt-dlp's Douyin extractor demands "fresh cookies" even when given fresh cookies — the issue is anti-bot fingerprinting, not auth. The iesdouyin.com share-page HTML embeds the playable mp4 URL with a mobile User-Agent and zero auth. ~50 lines of code, no dependency. |
| Composite fetcher chain | DouyinFetcher tries first; falls through to YtDlpFetcher for non-Douyin URLs. Lets us add platform-specific scrapers without changing call sites. |
| Whisper.cpp `medium` model | Free, local, decent multilingual (Mandarin, English, mixed). 1.5 GB on disk. |
| Ollama qwen2.5:7b for understanding | Free, local, good Chinese summarization. 4.7 GB on disk. Optional — pipeline degrades gracefully if Ollama is down. |
| Bearer-token auth | Dispatcher is on the public internet. Without auth, anyone could submit jobs and DoS the Mac. The cheapest gate. |
| BRAT install, no community plugin | Bear is the only user. No reason to put it through the community-plugin review. BRAT installs straight from GitHub releases. |

## Output format

The lesson markdown follows this template (rendered by `worker/src/worker/render.py` from `LessonInputs`):

```
# <Title>

- **URL:** <source URL>
- **Duration:** mm:ss
- **Processed:** YYYY-MM-DD HH:MM UTC

## Summary           (only if Ollama produced one)
<2-3 sentence summary>

## Key Points        (only if Ollama produced any)
- ...

## Tools Mentioned   (only if Ollama produced any)
- ...

## Code / Commands (from frames)   (only if Ollama produced any)
```

## Transcript
- `[mm:ss]` ...
- `[mm:ss]` ...

## Frame OCR         (only if non-empty OCR found)
### mm:ss
```
<OCR text>
```
```

The note opens automatically in the active Obsidian leaf when the plugin finishes writing it.

## Functional criteria (what counts as "done")

MVP is shipped when **all 12** of these hold:

1. From the Obsidian command palette, "Pitch: Ingest URL" opens a modal that accepts a video URL.
2. Submitting a YouTube vibe-coding URL produces a markdown note in `_todo/ideas/vibe-coding/` within ~5 minutes.
3. Submitting a Douyin URL produces a note (via the native scraper) — the note format is identical to YouTube's.
4. *(Deferred to v0.2)* "Pitch: Upload Local File" command accepts a local `.mp4`/`.mp3` and produces a note of the same shape.
5. The note contains source metadata, timestamped transcript, OCR'd frame text, and (when Ollama is up) summary/key-points/tools/code-snippets.
6. The note filename is `<YYYY-MM-DD>-<kebab-slug>.md` and is unique per ingest (suffix-numbered if collision).
7. While a job runs, the modal shows progress (queued / fetching / transcribing / done / failed).
8. The plugin reads its server URL and bearer token from a settings tab; changing them takes effect without restarting Obsidian.
9. The dispatcher rejects requests without the bearer token (401) and accepts with it (200).
10. The worker processes one job at a time without crashing on long videos (≤60 min).
11. Dispatcher runs on the existing EC2 (no upgrade) and worker runs on Bear's Mac. No paid APIs. Zero new dollars.
12. The plugin installs from `mrbear929/pitch` via BRAT — paste repo URL, install, enable, done.

11 of 12 are green as of v0.1.0 / v0.2.0. Item 4 is deferred.

## Verified scope (v0.2.0, 2026-05-25)

- Native Douyin scraper resolves `/video/<id>`, `/note/<id>`, `/jingxuan?modal_id=<id>`, and `/share/video/<id>/` URL forms — no auth, no cookies. Verified live with `https://www.douyin.com/video/7636717976720264491`.
- yt-dlp fallback handles YouTube. Verified live with `https://www.youtube.com/watch?v=jNQXAC9IVRw`.
- Whisper.cpp `medium` produces correct Mandarin + English transcripts.
- Tesseract `eng+chi_sim` extracts code/captions from sampled frames.
- Ollama `qwen2.5:7b` produces coherent Chinese summaries when invoked; pipeline tolerates Ollama being down.
- 60 automated tests pass: 12 dispatcher, 25 worker, 23 plugin.

## Phase 2 (deferred — not designed yet)

Once Phase 1 has been used 3–5 times and the lesson format proves useful:

- Plugin reads the vault, retrieves notes related to the lesson topic.
- Worker (or a new component) returns a "proposal" packet: which existing notes to update, which sections to add, which conflicts exist.
- Plugin renders the proposal as markdown with `- [x]/[ ]` approval checkboxes.
- A separate "Apply approved sections" command merges approved edits via diff-match-patch.

Phase 2 is gated on three runs of Phase 1 producing notes Bear actually wants to keep.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Douyin breaks the share-page format | Medium | The fetcher is structured behind a `Fetcher` interface; we can add a second Douyin scraper as a fallback in the chain. The existing test suite has parser tests we'd extend. |
| EC2 instance dies | Low-Med | `deploy-server.sh` is idempotent; rebuild from the same script in <5 min on a new instance. Tokens regenerate; plugin and worker need re-paste. |
| Worker hangs (already happened once) | Medium | `KeepAlive` in the launchd plist auto-restarts. No timeout on yt-dlp's request paths yet — that's a known issue worth a future fix. |
| Mac asleep when a job is submitted | Expected | Job sits in the dispatcher queue until the Mac wakes. Acceptable for MVP. |
| Whisper.cpp produces bad Mandarin | Low for `medium` | If transcript is unusable, OCR-from-frames still captures code/commands. The lesson template puts both side-by-side. |
| Ollama down or slow | Low impact | Pipeline catches the failure and renders the note without Summary/Key-Points sections. Verified by `test_pipeline_understander_crash_is_swallowed`. |

## Out of scope forever (i.e., would require a different product)

- Real-time streaming transcription.
- Multi-user / shared queues.
- Generic video summarizer for content unrelated to vibe coding / engineering.
- Replacing Bear's judgment about which lessons to keep.

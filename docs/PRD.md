# Pitch — PRD

> Code name: **Pitch**. May be renamed at commercial release.
> Last updated: 2026-05-26 (v0.7.2 / plugin v0.4.0).

## Problem

Long-form vibe-coding videos (15–60 min, often Mandarin Douyin or YouTube) hold useful technique — claims about tools, prompts, command snippets, workflows — but cost too much attention to watch. Bear keeps an Obsidian second brain. He needs a low-friction path: **one video link → one digestible note in the vault**, without reaching for any other tool.

## Users

Bear, on macOS, working in Obsidian. No multi-user support in MVP.

## Goals

1. **Capture from anywhere.** Submitting a URL works from any machine that can reach the internet — phone, work laptop, Obsidian on the desktop. Submission is decoupled from processing.
2. **Zero recurring cost.** Use only free APIs (Groq + Gemini free tiers). Reuse the EC2 instance Bear already runs for `tools.mrbear929.com`. The worker runs on Bear's existing Mac.
3. **Ship something usable in a session.** Not a research project. The first version had to install, deploy, and ingest a real video the same day.
4. **Source-of-truth output.** The product is the *output format*, not the plugin chrome. A 5-min video should produce a note Bear can skim in <3 min and decide whether to watch the full video.
5. **Background processing.** Submitting a URL must not block the Obsidian UI. Modal closes immediately; Notice fires when the note is saved.
6. **Batch capture.** One paste should be able to enqueue a list of URLs.

## Non-goals (MVP)

- Vault-aware proposal generation, conflict detection, approval workflow. Deferred to Phase 2 once Phase 1 has been used 3–5 times.
- Mobile-native UI, Slack/Raycast/iOS Shortcut integrations.
- Scheduled ingest, watch folders.
- Submission to the Obsidian community plugin store. Distribution is via BRAT (GitHub releases).
- Support for arbitrary social platforms. MVP supports Douyin (via custom scraper) and anything yt-dlp handles natively (YouTube, Bilibili, etc.).
- Provider failover (e.g., Groq → OpenAI when rate-limited). Free-tier limits aren't tight enough to hit in normal use; not worth complicating the code.

## Success criteria

A run is successful if **all** of these hold for one Douyin video:

1. Bear submits a URL via the Obsidian plugin command.
2. The plugin modal closes immediately and processing continues in the background.
3. Within ~1 minute (video) or ~5 seconds (image carousel), a markdown note appears at `_todo/ideas/vibe-coding/<YYYY-MM-DD>-<slug>.md`.
4. The note contains: source URL, post title (the user's caption, not the BGM), author, processing timestamp, and — for videos — a "what this covers" paragraph, key points, tools mentioned, code snippets, plus a full timestamped transcript. For image carousels: the post text plus the original images embedded inline.
5. Bear can read the note in under 3 minutes and decide whether the video was worth watching in full.
6. The dispatcher rejects requests without the bearer token; only Bear's plugin and worker can use it.
7. The whole stack costs zero dollars per month.

## Architecture (one-paragraph version)

Three components: **plugin** in Obsidian (the only UI), a tiny **dispatcher** on EC2 (queue + auth gate), and a **worker** daemon on Bear's Mac. Plugin POSTs URLs to the dispatcher; Mac worker long-polls; when a job arrives, the worker fetches the video (DouyinFetcher or yt-dlp), extracts audio with ffmpeg, transcribes via **Groq Whisper API**, uploads the video to **Gemini Files API** for native multimodal understanding, posts the rendered markdown back. Plugin's poll sees `done`, fetches the markdown plus any image attachments, writes everything to the vault. Image carousels skip transcription and Gemini entirely — they're rendered as the post text plus embedded images.

The dispatcher exists for one reason: **decouple submission from processing**, so Bear can paste a URL from anywhere and the Mac handles it whenever it's awake.

## Why this design

| Decision | Why |
|---|---|
| 3-component instead of 1 | Submission must work even when the Mac is off. The dispatcher is the always-on rendezvous point. |
| Dispatcher on shared EC2, not new infra | Free. Reuses the box already serving `tools.mrbear929.com`. Tiny memory footprint (queue API, ~100 MB). |
| Worker on Mac, not EC2 | The EC2 box has 957 MB RAM — too small for Whisper. Even after switching to APIs, the worker still needs ffmpeg to extract audio before sending to Groq, and SSH'ing to do that on EC2 vs. running a long-poll daemon locally is the same complexity for free. |
| Hosted APIs (Groq + Gemini), not local LLMs | Local Whisper + qwen2.5vl took 6+ minutes per video. Groq Whisper does the same transcription in 5–10 seconds. Gemini ingests the entire video natively (no per-frame extract → OCR → describe → summarize), returning structured output in 20–30 seconds. Both have generous free tiers. ~30× speedup, ~$0/month, ~7 GB disk reclaimed. |
| Custom Douyin scraper, not yt-dlp's | yt-dlp's Douyin extractor demands "fresh cookies" even when given fresh cookies — the issue is anti-bot fingerprinting, not auth. The iesdouyin.com share-page HTML embeds the playable mp4 URL with a mobile User-Agent and zero auth. ~50 lines, no dependency. |
| Composite fetcher chain | DouyinFetcher tries first; falls through to YtDlpFetcher for non-Douyin URLs. Lets us add platform-specific scrapers without changing call sites. |
| Image carousels skip the LLM | The user can read the slides; running vision over them adds 14 minutes for no information gain. Embed images inline, render the post body, ship in ~3 seconds. |
| Bearer-token auth | Dispatcher is on the public internet. Without auth, anyone could submit jobs and DoS the Mac. The cheapest gate. |
| Background polling in the plugin | The first version blocked the modal during processing. Users can't wait 1 minute looking at a frozen modal. Plugin spawns a `JobTracker` that polls per-job in the background and surfaces results via Obsidian Notice. |
| BRAT install, no community plugin | Bear is the only user. BRAT installs straight from GitHub release tags. |

## Output format

The lesson markdown follows this template (rendered by `worker/src/worker/render.py` from `LessonInputs`):

**For videos:**

```
# <Post title — the user's caption, not the BGM>

- **URL:** <source URL>
- **Author:** <creator>
- **Duration:** mm:ss
- **Type:** video
- **Processed:** YYYY-MM-DD HH:MM UTC (took 52s)

## Post
<post caption verbatim>

## What this covers
<one paragraph from Gemini — "what does this video cover">

## Key Points
- ...

## Tools Mentioned
- ...

## Code / Commands
```

## Transcript
- `[mm:ss]` ...
- `[mm:ss]` ...
```

**For image carousels (no LLM, no transcript):**

```
# <Post title>

- **URL:** ...
- **Author:** ...
- **Type:** image carousel
- **Processed:** ... (took 3s)

## Post
<post caption>

## Slides
![](attachments/pitch/<slug>/01.jpg)
![](attachments/pitch/<slug>/02.jpg)
...
```

The note opens automatically in the active Obsidian leaf when the plugin finishes writing it.

## Functional criteria (what counts as "done")

MVP is shipped when **all** of these hold:

1. From the Obsidian command palette, "Pitch: Ingest URLs" opens a modal that accepts one or many URLs (one per line).
2. Submitting a Douyin or YouTube video URL produces a markdown note in `_todo/ideas/vibe-coding/` within ~1 minute.
3. Submitting a Douyin image carousel URL produces a markdown note with embedded images in ~5 seconds.
4. Submitting a list of URLs (Cmd/Ctrl+Enter) queues one job per non-empty line. Jobs process sequentially on the worker.
5. The note's title comes from the post caption (not the BGM track), filename is `<YYYY-MM-DD>-<kebab-slug>.md`, unique per ingest.
6. The modal closes immediately after submit; processing happens in the background. Per-job Notice fires when each note is saved.
7. Reopening the modal during a batch shows an "Active jobs (N)" panel with live elapsed time per job.
8. The plugin reads its server URL and bearer token from a settings tab; changes apply without restarting Obsidian.
9. The dispatcher rejects requests without the bearer token (401) and accepts with it (200).
10. The dispatcher and worker each retry transient API failures (429/503) with exponential backoff before giving up.
11. Dispatcher runs on the existing EC2 (no upgrade); worker runs on Bear's Mac. Only ffmpeg is needed locally — no LLM binaries.
12. Costs zero new dollars per month (Groq + Gemini free tiers).
13. The plugin installs from `mrbear929/pitch` via BRAT.

All 13 are green as of v0.7.2 / plugin v0.4.0.

## Verified scope (v0.7.2 / plugin v0.4.0, 2026-05-26)

- Native Douyin scraper resolves `/video/<id>`, `/note/<id>`, `/jingxuan?modal_id=<id>`, `/share/video/<id>/`, and schemeless `douyin.com/video/<id>` URL forms — no auth, no cookies. Verified live.
- yt-dlp fallback handles YouTube and other supported platforms.
- **Groq Whisper API** (whisper-large-v3-turbo) handles transcription. ~5–10s for a 3-min video.
- **Gemini 2.5 Flash** with native video upload handles understanding. ~20–30s warm.
- Image carousels skip the LLM stack entirely; rendered with embedded inline images in ~3s.
- Plugin v0.4.0: background polling via JobTracker, batch URL submission via multi-line textarea, modal status panel.
- 81 automated tests pass: 12 dispatcher, 34 worker, 35 plugin.

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
| Worker restart leaves jobs stuck at `claimed` | Medium | Open: dispatcher should TTL claimed jobs back to pending. Currently mitigated by manual SQL unstick when needed. |
| Mac asleep when a job is submitted | Expected | Job sits in the dispatcher queue until the Mac wakes. |
| Groq or Gemini transient 429/503 | Medium | Both clients retry up to 5 times with exponential backoff. Past that, the pipeline degrades gracefully — Groq failure → empty transcript, Gemini failure → no coverage section. |
| Free-tier API limits exhausted | Low | Limits are very high (Groq ~7200 audio-sec/min, Gemini ~1500 req/day on Flash). If hit, we'd need a paid plan or provider failover (not built). |
| Gemini transcript / video data leaves the Mac | Accepted | Per Bear's call ("data can leave Mac. it's external anyway"). Only the video bytes + transcript go out; vault content never does. |

## Out of scope forever (i.e., would require a different product)

- Real-time streaming transcription.
- Multi-user / shared queues.
- Generic video summarizer for content unrelated to vibe coding / engineering.
- Replacing Bear's judgment about which lessons to keep.

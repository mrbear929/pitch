Try to get the three answers yourself. You can run status check my EC2 setting in the dev folder. # Pitch — Tech Spec

> Code name. May be renamed at commercial release.

## PRD

**Problem.** Long vibe-coding videos (15–60 min, often Chinese-language Douyin) hold useful technique, but cost too much attention to watch. Bear keeps an Obsidian second brain. He needs a low-friction path: one video link → one digestible note in the vault.

**Users.** Bear, on macOS, working in Obsidian. No other users in MVP.

**Success criteria.**
- Bear sends a video URL via the plugin command.
- Within ~5 minutes, a markdown note appears at `_todo/ideas/vibe-coding/<date>-<slug>.md`.
- The note contains: source metadata, full transcript with timestamps, OCR'd text from sampled frames (mostly code/commands shown on screen).
- Bear can skim the note in under 3 minutes — fast-scan timestamps, copy/paste code blocks.
- No vault content is sent to the server.
- No paid APIs. Everything runs locally on the EC2.

**Non-goals.**
- Vault comparison, proposal generation, approval workflow (Phase 2).
- Mobile capture, Slack/Raycast/iOS Shortcut.
- Batch processing, scheduled ingest, multi-user.
- Community-plugin submission. Plugin installs via GitHub release (BRAT).
- Generic video summarizer for unrelated content.

## Architecture (three components, zero cost)

```
  any device           EC2 (existing, tiny)            Mac (existing)
 ┌──────────┐  POST   ┌───────────────────┐  long-poll  ┌──────────────────┐
 │ Obsidian │ ──────▶ │ pitch dispatcher  │ ◀────────── │ pitch worker     │
 │  plugin  │ ◀────── │ - queue           │ ──result──▶ │ yt-dlp + ffmpeg  │
 │ (or curl │  poll   │ - bearer auth     │             │ whisper.cpp      │
 │  /iOS)   │         │ - no processing   │             │ tesseract        │
 └──────────┘         └───────────────────┘             │ local LLM (Ollama│
                                                        │ qwen2.5:7b)      │
                                                        └──────────────────┘
```

- **EC2 dispatcher** = small FastAPI app. Just a queue + result store. No ffmpeg, no Whisper. Fits in 100 MB. Submitting works from anywhere (phone, laptop, plugin).
- **Mac worker** = Python daemon (launchd agent, autostarts on login). Long-polls EC2 for pending jobs, processes locally, posts result back. All heavy lifting here.
- **Plugin** = Obsidian command + settings. Submits URL to EC2, polls EC2 for result, writes markdown to vault.

**Tradeoff:** if Mac is asleep, jobs sit in the queue until it wakes. Acceptable for MVP.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 — Capture loop | URL → dispatcher → Mac worker → markdown note in vault. | Active. |
| 2 — Proposal & approval | Plugin reads vault, worker returns proposal, plugin applies approved diffs. | Deferred until Phase 1 has been used 3–5 times. |

## Phase 1 functional criteria

MVP is done when **all 12** of these hold:

1. From Obsidian command palette, "Pitch: Ingest URL" opens a modal that accepts a video URL.
2. Submitting a YouTube vibe-coding URL produces a markdown note in `_todo/ideas/vibe-coding/` within 5 minutes.
3. Submitting a Douyin URL either produces a note OR shows an Obsidian notice "fetch failed — use Upload Local File." Never silent.
4. "Pitch: Upload Local File" command accepts a local `.mp4`/`.mp3` and produces a note of the same shape.
5. The note contains: source URL, video title, duration, processed date, **timestamped transcript** (`[mm:ss] text`), and **OCR'd text from sampled frames** (mostly the code/commands shown on screen).
6. The note filename is `<YYYY-MM-DD>-<kebab-slug>.md` and is unique per ingest.
7. While a job runs, the modal shows progress (queued / fetching / transcribing / done / failed).
8. The plugin reads its server URL and bearer token from a settings tab; changing them takes effect without restarting Obsidian.
9. The server rejects requests without the bearer token (401) and accepts with it (200).
10. The server processes one job at a time without crashing on long videos (≤60 min).
11. The dispatcher runs on the existing EC2 (no upgrade) and the worker runs on Bear's Mac. No paid APIs. Zero new dollars.
12. The plugin installs from `mrbear929/pitch` via BRAT — paste repo URL, install, enable, done.

## Phase 2 testing criteria

Placeholder. Defined when Phase 1 ships and we know what the proposal format actually needs to be.

## Decisions taken

- **LLM:** none. MVP is transcript + OCR only. No Bedrock, no Anthropic, no Ollama. Free.
- **Hosting:** existing EC2 that runs `tools.mrbear929.com`. No Docker.
- **GitHub:** public, under `mrbear929`.
- **Domain pattern:** `tools.mrbear929.com/pitch/` (path-based, not subdomain — matches `/md-editor/`).
- **Vault output path:** `_todo/ideas/vibe-coding/`.

## Environment (resolved)

- **EC2 (dispatcher only):** `ssh -i ~/.ssh/mrbear929_ec2.pem ubuntu@16.59.18.5`. Ubuntu 24.04, 957 MB RAM, 1 vCPU. Tight but fine for a queue API. nginx 1.24 fronts `tools.mrbear929.com`; Pitch gets a `location /pitch/` block proxying to a local port.
- **Mac (worker):** macOS, Python 3.12 already installed via vault tooling. Worker installs ffmpeg, tesseract, whisper.cpp, Ollama. Runs as a launchd agent.
- **GitHub:** `gh` authenticated as `mrbear929`. Repo `mrbear929/pitch`, public.
- **LLM:** local Ollama with `qwen2.5:7b` (good Chinese, ~4.5 GB, free, runs on M-series Mac). Used for understanding pass on transcript+OCR; transcription itself is whisper.cpp `medium` model (free, fast on Mac).

## Out of scope for now

Source code, dependency installs, GitHub repo creation, EC2 changes, adding `pitch/` as a submodule of `mrbear929/tools`, Phase 2 design. All deferred until the asks above are answered.

# Pitch — Technical specs

> What runs where, on what ports, in what files. Everything you need to operate, debug, or rebuild the system from scratch.
> Last updated: 2026-05-26 (v0.7.2 / plugin v0.4.0).

## System map

```
┌──────────────────────────────┐                  ┌────────────────────────────┐
│  Obsidian (Bear's Mac)       │                  │  EC2  ubuntu@16.59.18.5    │
│                              │  HTTPS           │  tools.mrbear929.com       │
│  Plugin: mrbear929/pitch     │ ───── client ──▶ │                            │
│  Settings → Pitch:           │                  │  nginx 1.24                │
│   serverUrl                  │ ◀──── poll ───── │   /pitch/  →  127.0.0.1:8765│
│   apiKey  (client token)     │                  │                            │
│   outputFolder               │                  │  systemd: pitch.service    │
└──────────────────────────────┘                  │   uvicorn dispatcher       │
            │                                     │   SQLite jobs.db           │
            │ writes lesson .md                   │   bearer auth (2 tokens)   │
            ▼                                     └────────────┬───────────────┘
   _todo/ideas/vibe-coding/                                    │
                                                               │ HTTPS
                                                               │ worker token
                                                               │
                                                               ▼
                                  ┌─────────────────────────────────────────────┐
                                  │  Worker (same Mac, separate process)        │
                                  │                                             │
                                  │  launchd: com.mrbear929.pitch-worker        │
                                  │   long-poll  GET /jobs/next                 │
                                  │                                             │
                                  │  Video pipeline:                            │
                                  │    fetch (DouyinFetcher / yt-dlp)           │
                                  │    → ffmpeg audio extract                   │
                                  │    → Groq Whisper API                       │
                                  │    → Gemini 2.5 Flash (Files API)           │
                                  │    → render markdown                        │
                                  │                                             │
                                  │  Image-carousel pipeline (no LLM):          │
                                  │    fetch (DouyinFetcher)                    │
                                  │    → resize images                          │
                                  │    → render markdown + base64 attachments   │
                                  │                                             │
                                  │   POST /jobs/<id>/progress                  │
                                  │   POST /jobs/<id>/result                    │
                                  └─────────────────────────────────────────────┘
```

The dispatcher is a queue + auth gate. It does no media processing. The worker on the Mac shells out to ffmpeg and calls hosted APIs (Groq + Gemini); no local LLM models. The plugin sees only the dispatcher.

## Repository

- **GitHub:** `https://github.com/mrbear929/pitch` (public)
- **Local clone (vault submodule):** `~/Documents/obsidian-vault/dev/tools/pitch/`
- **Plugin release tags (BRAT-installable):** `v0.1.0`, `v0.2.0`, `v0.3.0`, `v0.4.0` (latest).
- **Worker/server commits use `v0.x.y` in commit messages but no separate tag** — the worker is updated via `install-worker.sh`, the dispatcher via `deploy-server.sh`.

### Repo layout

```
dev/tools/pitch/
├── shared/                 # pydantic models shared between server & worker
│   └── src/pitch_shared/
│       ├── __init__.py
│       └── job.py          # JobStatus, JobSubmit, JobProgress, JobResult, Job
├── server/                 # EC2 dispatcher
│   ├── pyproject.toml
│   ├── Makefile            # `make ci` lints + tests
│   └── src/dispatcher/
│       ├── app.py          # FastAPI factory — uvicorn dispatcher.app:create_app --factory
│       ├── auth.py         # bearer-token check (constant-time compare)
│       ├── config.py       # env-only config (PITCH_CLIENT_TOKEN, PITCH_WORKER_TOKEN)
│       └── store.py        # SQLite-backed JobStore (WAL, durable across restarts)
├── worker/                 # Mac worker daemon
│   ├── pyproject.toml      # exposes `pitch-worker` console script
│   ├── Makefile
│   └── src/worker/
│       ├── main.py         # launchctl entry point — asyncio long-poll loop
│       ├── config.py       # env-only config (Groq + Gemini keys)
│       ├── dispatcher_client.py  # httpx wrapper for /jobs/next, /progress, /result
│       ├── pipeline.py     # Pipeline composition, Fetcher/Transcriber/VideoUnderstander
│       ├── tools.py        # CompositeFetcher, DouyinFetcher, YtDlpFetcher,
│       │                   # FfmpegAudioExtractor, GroqTranscriber,
│       │                   # GeminiVideoUnderstander
│       ├── render.py       # jinja2 lesson template (LessonInputs)
│       └── text.py         # slugify, format_ts (pure helpers)
├── plugin/                 # Obsidian plugin (TypeScript, esbuild)
│   ├── manifest.json       # id: pitch, version: 0.1.0, isDesktopOnly: true
│   ├── package.json
│   ├── esbuild.config.mjs
│   └── src/
│       ├── main.ts         # plugin lifecycle, registers command, settings tab
│       ├── settings.ts     # PitchSettings + DEFAULT_SETTINGS
│       ├── settings-tab.ts # settings UI
│       ├── api.ts          # PitchClient, ApiError, AuthError
│       ├── poll.ts         # pure async polling state machine
│       ├── modal.ts        # IngestUrlModal (URL input + progress display)
│       ├── slug.ts         # slugify, filenameFor (mirrors worker/text.py)
│       ├── vault.ts        # uniquePath helper
│       ├── job-tracker.ts  # background polling, attachments writer, status panel state
│       └── modal.ts        # multi-URL textarea, parseUrlList, status panel UI
├── scripts/
│   ├── deploy-server.sh    # idempotent EC2 deploy
│   └── install-worker.sh   # idempotent Mac install
├── docs/
│   ├── PRD.md              # product spec
│   ├── SPECS.md            # this file
│   └── VALIDATION.md       # what's auto-verified vs Bear-verified
├── .github/workflows/
│   ├── ci.yml              # runs on push to main
│   └── release.yml         # tag-triggered; builds plugin, attaches to release
├── TECH-SPEC.md            # original spec (kept for history)
├── Makefile                # `make ci` runs all three stacks
└── README.md
```

## Components and runtime locations

### Component 1 — Dispatcher (EC2)

Where it runs:

| Item | Path | Notes |
|---|---|---|
| Source clone | `/opt/pitch/` | git clone of `https://github.com/mrbear929/pitch.git` |
| Python venv | `/opt/pitch/.venv/` | `pip install -e shared && pip install -e server` |
| Database | `/opt/pitch/server/jobs.db` | SQLite, WAL mode |
| Env file | `/opt/pitch/server/.env` | Mode 600. Contains `PITCH_CLIENT_TOKEN`, `PITCH_WORKER_TOKEN`, `PITCH_DB_PATH`. |
| Systemd unit | `/etc/systemd/system/pitch.service` | EnvironmentFile points at `.env` |
| nginx snippet | `/etc/nginx/snippets/pitch.conf` | `location /pitch/ { proxy_pass http://127.0.0.1:8765/; ... }` |
| nginx site (modified) | `/etc/nginx/sites-enabled/tools.mrbear929.com` | Added `include /etc/nginx/snippets/pitch.conf;` |
| Listen port | `127.0.0.1:8765` | Internal only; nginx terminates TLS |

How it starts/stops/restarts:

```
sudo systemctl status pitch
sudo systemctl restart pitch
sudo journalctl -u pitch -f         # live logs
```

How it deploys:

```bash
PITCH_HOST=ubuntu@16.59.18.5 PITCH_SSH_KEY=$HOME/.ssh/mrbear929_ec2.pem \
  ./scripts/deploy-server.sh
```

The script clones if missing, `git pull --ff-only` otherwise, refreshes the venv, ensures `.env` exists with generated tokens (only created on first run — never overwrites), writes the systemd unit, writes the nginx snippet, reloads nginx, restarts pitch, then `curl /healthz`.

#### HTTP API

| Method | Path | Auth role | Purpose |
|---|---|---|---|
| GET | `/healthz` | none | liveness; returns `{"ok": true, "stats": {...}}` |
| POST | `/jobs` | client | enqueue `{url, topic_hint?}` → `{id, status}` |
| GET | `/jobs/{id}` | client | fetch full job state including markdown when done |
| GET | `/jobs/next` | worker | long-poll up to 25s, atomically claim oldest pending |
| POST | `/jobs/{id}/progress` | worker | `{status, message?}` — best-effort progress ping |
| POST | `/jobs/{id}/result` | worker | `{status, markdown?, title?, slug?, error?, user_guidance?}` |

`/jobs/next` route is registered before `/jobs/{job_id}` so FastAPI matches the literal first.

### Component 2 — Worker (Mac)

Where it runs:

| Item | Path | Notes |
|---|---|---|
| Source mirror | `~/Library/Application Support/Pitch/src/{shared,server,worker}/` | Copied out of `~/Documents/` because macOS TCC blocks LaunchAgents from reading `~/Documents/`. The vault git repo is the master; this is the runtime mirror. |
| Python venv | `~/Library/Application Support/Pitch/.venv/` | Built on Homebrew `python@3.13`. `pitch-worker` console script lives in `bin/`. |
| Env file | `~/Library/Application Support/Pitch/worker.env` | Mode 600. Quoted values (paths contain spaces). Holds API keys — never commit. |
| Working dir (per-job) | `~/Library/Application Support/Pitch/work/<job_id>/` | Created at start of each job, deleted in `finally`. Holds downloaded video and audio. |
| Logs | `~/Library/Application Support/Pitch/logs/worker.{out,err}.log` | Stdout / stderr |
| Wrapper script | `~/Library/Application Support/Pitch/run-worker.sh` | Sources the env file, then `exec "$@"` — used by launchd |
| LaunchAgent plist | `~/Library/LaunchAgents/com.mrbear929.pitch-worker.plist` | `KeepAlive=true`, `RunAtLoad=true` |

How it starts/stops/restarts:

```bash
launchctl load -w ~/Library/LaunchAgents/com.mrbear929.pitch-worker.plist
launchctl unload ~/Library/LaunchAgents/com.mrbear929.pitch-worker.plist
launchctl kickstart -k gui/$(id -u)/com.mrbear929.pitch-worker     # restart
launchctl list | grep com.mrbear929                                # is it alive?
tail -f "$HOME/Library/Application Support/Pitch/logs/worker.err.log"
```

How it installs (one-time):

```bash
./scripts/install-worker.sh
# then: edit ~/Library/Application Support/Pitch/worker.env
#       set PITCH_WORKER_TOKEN to the value the deploy script printed
launchctl load -w ~/Library/LaunchAgents/com.mrbear929.pitch-worker.plist
```

#### Pipeline stages

The worker runs jobs serially. There are two paths.

**Image carousel (Douyin posts where `aweme_type=2`):**

| Stage | Tool | Notes |
|---|---|---|
| Fetch | `DouyinFetcher` | parses share-page HTML, downloads images |
| Render | `_build_attachments` (Pillow) | resizes images to 1280px long-edge, JPEG-encodes to base64, builds markdown referencing them |

Total wall-clock: ~3 seconds. No transcription, no LLM.

**Video (Douyin video posts, YouTube, etc.):**

| Stage | Status reported | Tool | Notes |
|---|---|---|---|
| Fetch | `fetching` | `CompositeFetcher` → `DouyinFetcher`, `YtDlpFetcher` | First fetcher to succeed wins. |
| Audio | `transcribing` | `ffmpeg -ac 1 -ar 16000` | mono 16kHz wav for Groq |
| Transcribe | `transcribing` | Groq Whisper API (`whisper-large-v3-turbo`) | hosted; ~5–10s for a 3-min video. Returns timestamped segments. |
| Understand | `understanding` | Gemini Files API + `gemini-2.5-flash` | uploads video natively, polls until ACTIVE, calls `generateContent` with response schema. Returns `coverage`, `key_points`, `tools_mentioned`, `code_snippets`. |
| Render | `rendering` | jinja2 template | output is the lesson markdown |

Total wall-clock: ~30–60 seconds for a 3–5 min video.

Both Groq and Gemini calls retry up to 5 times with exponential backoff on 429/502/503/504. On unhandled exception the worker reports `failed` with `error` and a `user_guidance` string the plugin surfaces verbatim. If transcription or understanding partially fails, the pipeline still renders what it has.

### Component 3 — Plugin (Obsidian)

Where it runs:

| Item | Path | Notes |
|---|---|---|
| Installed by BRAT to | `<vault>/.obsidian/plugins/pitch/` | Three files: `main.js`, `manifest.json`, `styles.css` |
| Settings persisted in | `<vault>/.obsidian/plugins/pitch/data.json` | Standard Obsidian plugin storage |
| Output folder | `_todo/ideas/vibe-coding/` (default; configurable) | New notes go here |

Source code is at `dev/tools/pitch/plugin/` in this repo. Releases are built by `.github/workflows/release.yml` on tag push and attached as release assets.

#### Commands

| Command name | Behavior |
|---|---|
| `Pitch: Ingest URLs` | Modal: multi-line URL textarea (one URL per line, `#` comments and blank lines ignored), optional topic hint. Cmd/Ctrl+Enter submits. Each line is POSTed to `/jobs` independently and tracked by `JobTracker`. Modal closes immediately on submit; Notice fires per-job on completion. |

`JobTracker` runs background polls per job, calls `vault.create()` for the markdown and `vault.createBinary()` for any image attachments under `<outputFolder>/attachments/pitch/<slug>/`. `Pitch: Upload Local File` is **not implemented yet** (planned).

## Environment variables

### Dispatcher (`/opt/pitch/server/.env` on EC2)

| Var | Value | Notes |
|---|---|---|
| `PITCH_CLIENT_TOKEN` | random 43-char URL-safe string | Generated once by `deploy-server.sh`. Plugin uses this. |
| `PITCH_WORKER_TOKEN` | random 43-char URL-safe string | Generated once. Worker uses this. |
| `PITCH_DB_PATH` | `/opt/pitch/server/jobs.db` | SQLite path |
| `PITCH_LONG_POLL_SECONDS` | (default 25) | How long `/jobs/next` waits before returning empty |

### Worker (`~/Library/Application Support/Pitch/worker.env`)

| Var | Value | Notes |
|---|---|---|
| `PITCH_DISPATCHER_URL` | `https://tools.mrbear929.com/pitch` | Trailing slash stripped automatically |
| `PITCH_WORKER_TOKEN` | matches dispatcher's worker token | |
| `PITCH_GROQ_API_KEY` | starts with `gsk_` | from https://console.groq.com/keys (free) |
| `PITCH_GEMINI_API_KEY` | starts with `AIza` | from https://aistudio.google.com/apikey (free) |
| `PITCH_WORK_DIR` | `~/Library/Application Support/Pitch/work` | |

All values containing spaces (paths with `Application Support`) MUST be double-quoted in the env file. The env file is mode 600 — never commit it.

### Plugin (Obsidian Settings → Pitch)

| Setting | Default | Notes |
|---|---|---|
| Server URL | `https://tools.mrbear929.com/pitch` | |
| API key | (empty — Bear pastes the client token) | Stored as a password input in the UI |
| Output folder | `_todo/ideas/vibe-coding` | Vault-relative |
| Poll interval (ms) | 3000 | |
| Poll timeout (ms) | 1,800,000 (30 min) | Plugin gives up on job after this |

## External dependencies on the Mac

Installed once by `install-worker.sh`.

| Tool | Source | Purpose |
|---|---|---|
| ffmpeg | `brew install ffmpeg` | audio extraction (only local binary still required) |
| python@3.13 | `brew install python@3.13` | base interpreter for the venv |
| Groq API | hosted | transcription (replaces local whisper.cpp) |
| Gemini API | hosted | video understanding (replaces local ollama + qwen vision/text) |

Disk footprint on the Mac: under 200 MB (mostly the Python venv + httpx/yt-dlp deps). Down from ~7 GB pre-API.

## How tokens work

Two bearer tokens, both random opaque strings (`secrets.token_urlsafe(32)`), generated once by `deploy-server.sh` on the EC2 box and stored in `/opt/pitch/server/.env`. They are NOT credentials for any external product — they exist solely to gate the public dispatcher URL.

| Token | Used by | What it permits |
|---|---|---|
| `PITCH_CLIENT_TOKEN` | Plugin (and any future client — curl, iOS Shortcut) | Submit jobs, read job status |
| `PITCH_WORKER_TOKEN` | Worker on Bear's Mac | Claim jobs, post progress, post results |

Routes are role-gated: a client token cannot claim or post results; a worker token cannot submit. Compare is constant-time (`secrets.compare_digest`).

To rotate: edit `/opt/pitch/server/.env` on EC2, `sudo systemctl restart pitch`, then update the plugin settings (paste the new client token) and `~/Library/Application Support/Pitch/worker.env` on the Mac (paste the new worker token), then `launchctl kickstart -k` the worker.

## How a request flows end-to-end

1. Bear runs `Pitch: Ingest URLs` and pastes one or many URLs.
2. Plugin POSTs each URL to `https://tools.mrbear929.com/pitch/jobs` with bearer = client token; modal closes immediately.
3. nginx terminates TLS, proxies to `http://127.0.0.1:8765/jobs`.
4. Dispatcher writes a row to `jobs.db` with `status=pending`, returns `{id, status}`.
5. Plugin's `JobTracker` starts polling `GET /jobs/{id}` per job in the background.
6. Worker (long-polling `/jobs/next` with bearer = worker token) atomically claims the oldest pending job; status flips to `claimed`.
7. Worker calls progress endpoint with `fetching → transcribing → understanding → rendering` as it goes.
8. Worker POSTs to `/jobs/{id}/result` with `status=done`, the rendered markdown, and any image attachments (base64).
9. Plugin's next poll sees `status=done`. JobTracker writes attachments to `<outputFolder>/attachments/pitch/<slug>/` via `vault.createBinary()`, then writes markdown to `<outputFolder>/<YYYY-MM-DD>-<slug>.md` via `vault.create()`, then opens the note.
10. Notice fires: `Pitch [host/id]: note saved.`

## Tests and CI

| Stack | Test count | Framework | Run |
|---|---|---|---|
| Dispatcher | 12 | pytest + httpx TestClient | `cd server && make ci` |
| Worker | 34 | pytest with fakes for fetcher/transcriber/understander; one cross-package live-server test | `cd worker && make ci` |
| Plugin | 35 | jest with mocked Obsidian module | `cd plugin && npm run ci` |
| All | 81 | — | `make ci` at repo root |

GitHub Actions runs all three on every push to `main`. Tag push (`v*`) triggers the release workflow, which builds the plugin and attaches `main.js`, `manifest.json`, `styles.css` to the release.

## Operations cheat sheet

```bash
# Is the dispatcher alive?
curl -fsS https://tools.mrbear929.com/pitch/healthz

# Is the worker alive?
launchctl list | grep com.mrbear929.pitch-worker

# Tail worker logs
tail -f "$HOME/Library/Application Support/Pitch/logs/worker.err.log"

# Tail dispatcher logs
ssh -i ~/.ssh/mrbear929_ec2.pem ubuntu@16.59.18.5 'sudo journalctl -u pitch -f'

# Submit a test job from the laptop
CT="<client token>"
curl -X POST https://tools.mrbear929.com/pitch/jobs \
  -H "Authorization: Bearer $CT" -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=jNQXAC9IVRw"}'

# Check a job
curl https://tools.mrbear929.com/pitch/jobs/<id> -H "Authorization: Bearer $CT"

# Restart worker after a code change
launchctl kickstart -k gui/$(id -u)/com.mrbear929.pitch-worker

# Sync code changes to the Mac runtime mirror
rm -rf "$HOME/Library/Application Support/Pitch/src/worker"
cp -R "$HOME/Documents/dev/tools/pitch/worker" \
      "$HOME/Library/Application Support/Pitch/src/"
"$HOME/Library/Application Support/Pitch/.venv/bin/pip" install -e \
  "$HOME/Library/Application Support/Pitch/src/worker" --quiet
launchctl kickstart -k gui/$(id -u)/com.mrbear929.pitch-worker

# Redeploy dispatcher after a code change
./scripts/deploy-server.sh   # idempotent; pulls latest, rebuilds venv, restarts service
```

## Failure modes and how to recognize them

| Symptom | Likely cause | Where to look |
|---|---|---|
| Modal: `Pitch: API key rejected` | client token mismatch | Plugin settings vs `/opt/pitch/server/.env` |
| Modal: `Pitch job timed out` | worker is dead or stuck | `launchctl list \| grep pitch`; check err log |
| All jobs stay `pending` forever | worker is not running, or worker has bad/empty Groq/Gemini key | `launchctl list`; check err log; restart |
| Job goes to `claimed` and never moves | worker died mid-job or was killed before posting result | Restart worker; manually unstick row in `jobs.db` (`UPDATE jobs SET status='failed' WHERE status='claimed'`). Open: dispatcher should TTL these. |
| Job → `failed` with "Couldn't fetch the Douyin video automatically..." | DouyinFetcher couldn't parse share page, yt-dlp also gave up | Try a different URL form, or wait — Douyin's share-page format may have shifted |
| Job → `done` but note has no `## What this covers` | Gemini retried 5x, hit transient 429/503 | Check err log for `Gemini transient` warnings; usually self-resolves on next try |
| Job → `done` but `## Transcript` is empty | Groq retried 5x, gave up | Worker log will show `transcription failed; continuing without` |
| 404 from `/healthz` through the public URL | nginx site config not reloaded, or systemd unit died | `ssh; sudo systemctl status pitch; sudo nginx -T \| grep pitch` |
| Worker fails with `Operation not permitted: ~/Documents/...` | Source got moved back into `~/Documents/`; macOS TCC blocks it | The runtime venv must be under `~/Library/Application Support/Pitch/.venv/` |
| Worker venv broken after `brew uninstall` | Pulled in a transitive Python uninstall (e.g., python@3.14 was a dep of a removed package) | Rebuild venv: `rm -rf $APP_VENV; /opt/homebrew/bin/python3.13 -m venv $APP_VENV` then reinstall packages |

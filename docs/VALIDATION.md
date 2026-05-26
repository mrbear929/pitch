# Pitch — validation checklist

What I (Claude) verified vs. what you (Bear) need to verify by hand.

## Verified by automated tests

- 12 dispatcher tests (server lifecycle, auth, store) — `cd server && make ci` → green.
- 15 worker tests (text helpers, render, pipeline with fakes, cross-package live HTTP) — `cd worker && make ci` → green.
- 23 plugin tests (slug, api client, polling, vault path uniqueness, settings) — `cd plugin && npm run ci` → green.

## Verified live against the deployed system

| # | Criterion (from TECH-SPEC §"Phase 1 functional criteria") | Evidence |
|---|---|---|
| 9 | Server rejects without bearer (401), accepts with it (200) | `curl … /pitch/jobs` without auth → 401; with auth → 200. |
| 10 | Server processes one job at a time without crashing | Lifecycle test through live `tools.mrbear929.com/pitch/`: submit → claim → progress → result. |
| 11 | Zero-cost: no paid APIs | Dispatcher runs on existing EC2; worker stack (yt-dlp, ffmpeg, whisper.cpp, tesseract, ollama) is all local + free. |
| 12 | Plugin installable from `mrbear929/pitch` via BRAT | Release v0.1.0 ships `main.js`, `manifest.json`, `styles.css`. |

## You verify (needs your Mac running the worker + Obsidian)

Before any of these will pass:

1. **Worker token.** SSH'd output during deploy printed two tokens. The **client** token goes into the Obsidian plugin settings (Settings → Pitch → API key). The **worker** token goes into `~/Library/Application Support/Pitch/worker.env` on this Mac.
2. **Load the launchd agent.**
   ```
   launchctl unload ~/Library/LaunchAgents/com.mrbear929.pitch-worker.plist 2>/dev/null
   launchctl load -w ~/Library/LaunchAgents/com.mrbear929.pitch-worker.plist
   tail -f "$HOME/Library/Application Support/Pitch/logs/worker.err.log"
   ```
   You should see "worker started" within a few seconds.
3. **Install plugin via BRAT.** In Obsidian: BRAT → Add Beta Plugin → paste `mrbear929/pitch` → choose `v0.1.0`. Enable.
4. **Configure plugin.** Settings → Pitch → fill in:
   - Server URL: `https://tools.mrbear929.com/pitch`
   - API key: (the *client* token printed by the deploy script)

Then run the 12 functional criteria from the spec:

| # | What to do | Pass means |
|---|---|---|
| 1 | Cmd-P → "Pitch: Ingest URL" | Modal opens with URL field. |
| 2 | Paste a YouTube vibe-coding URL, hit Ingest | Within ~5 min a note appears in `_todo/ideas/vibe-coding/`. |
| 3 | Paste a Douyin URL, hit Ingest | Either a note appears OR a Notice says "Couldn't fetch the Douyin video automatically… AirDrop it to your Mac…" |
| 4 | (Phase 1 next: a "Upload local file" command — see open items below) | TBD — see "Open" section. |
| 5 | Open the produced note | Has source URL, duration, processed timestamp, `[mm:ss]` transcript, OCR'd frame text. With Ollama running, also has Summary/Key Points/Tools/Code sections. |
| 6 | Ingest the same video twice | Second filename is `…-2.md`, doesn't overwrite. |
| 7 | While job runs, watch the modal progress text | Cycles through fetching → transcribing → extracting → understanding → rendering → done. |
| 8 | Change settings (e.g., output folder) without reloading Obsidian | Next ingest writes to the new folder. |

## Open items (what I deliberately did NOT build in v0.1.0)

- **"Upload local file" command.** F4 in the spec. The dispatcher accepts only URLs in v0.1.0; a multipart upload path was in scope but I cut it for the first ship — let me add it as `v0.2.0` after you confirm the URL flow works. Workaround: drop the file in a folder served by yt-dlp's `file://` extractor, or wait for v0.2.0.
- **No automated test that exercises ffmpeg/whisper/tesseract/ollama end-to-end.** Those tools aren't in CI; the worker pipeline tests all use fakes. The first full ingest is the integration test.
- **Disk space cleanup.** Worker drops job working files after each job, but Whisper model + Ollama model + downloaded videos sit on the Mac. No retention policy yet.

## Tokens (sensitive — store somewhere, then delete from chat)

```
PITCH_CLIENT_TOKEN=bNpiC-CHVJiBx4oBOfVSxR5_85kXu4lyFlsQd8p9Um8
PITCH_WORKER_TOKEN=_-vzjxBUJzWBZwklgXLH97K3zXo43LFt7CuyviMjXBY
```

If these ever leak, regenerate by editing `/opt/pitch/server/.env` on EC2 and `sudo systemctl restart pitch`, then update both the plugin settings and the Mac worker env file.

# Pitch — validation checklist

What's verified by automated tests, by live deployment, and by Bear in Obsidian.
Last updated: 2026-05-26 (v0.7.2 / plugin v0.4.0).

## Verified by automated tests

- 12 dispatcher tests (server lifecycle, auth, store) — `cd server && make ci`.
- 34 worker tests (text helpers, render, pipeline with fakes, Douyin parser, composite fetcher chain, cross-package live HTTP) — `cd worker && make ci`.
- 35 plugin tests (slug, api client, polling, vault path uniqueness, settings, JobTracker, multi-URL parser) — `cd plugin && npm run ci`.
- **Total: 81 tests green.** GitHub Actions runs all on every push to `main`.

## Verified live end-to-end

| Scenario | Wall-clock | Notes |
|---|---|---|
| Bearer auth (curl) | <1s | 401 without token, 200 with. |
| Image carousel (`douyin.com/video/7618972935072366505`) | ~3s | Full post + embedded image renders. No LLM called. |
| Video (`douyin.com/video/7634862226716757283`) | ~52s | Transcript via Groq, coverage + key points + tools + code via Gemini. |
| Schemeless URL (`douyin.com/video/...` without `https://`) | ~33s | DouyinFetcher accepts both forms. |
| Worker degradation when Gemini 503s | n/a | Pipeline still produces note from transcript + post text. Retries up to 5x first. |
| Plugin background polling | n/a | Modal closes immediately on submit; Notice fires per-job on completion. |

## You verify (needs your Obsidian + plugin v0.4.0)

1. **Plugin upgrade.** Obsidian → BRAT → "Check for updates to all beta plugins" → Pitch shows v0.4.0.
2. **Cmd-P → "Pitch: Ingest URLs"** → modal opens with a multi-line textarea (note: "URLs" plural).
3. **Single URL test.** Paste `douyin.com/video/7618972935072366505` → click Send to Pitch → modal closes → Notice "queued 1 job" → ~5s later Notice "note saved" → image carousel note opens with the inline slide image.
4. **Video test.** Paste `douyin.com/video/7634862226716757283` → wait ~1 min → note opens with transcript + coverage paragraph in Mandarin.
5. **Batch test.** Paste 3+ URLs (one per line) → Cmd+Enter → "queued N jobs" Notice → reopen modal → see active-jobs panel with live elapsed times → individual notes appear over the next few minutes.

## Open items / known limits

- **"Upload local file" command** — not yet built. Workaround: paste a URL.
- **Worker restart leaves jobs stuck at `claimed`** — needs manual SQL unstick. Open: dispatcher should TTL claimed jobs back to pending.
- **No provider failover.** If Groq Whisper rate-limits, transcription is empty (note still produced). If Gemini fails 5 retries, no coverage section. Free-tier limits are high enough this hasn't happened in normal use.

## Tokens (sensitive)

The bearer tokens in `/opt/pitch/server/.env` on EC2 — gate the public dispatcher URL. They are NOT third-party API keys.

The Groq/Gemini API keys live in `~/Library/Application Support/Pitch/worker.env` on the Mac, mode 600. Never commit either file.

If a token leaks: edit `/opt/pitch/server/.env` on EC2, `sudo systemctl restart pitch`, then update both the plugin settings and the Mac worker env.

# Pitch

Long-form video → digestible Obsidian note. Zero-cost pipeline.

## Architecture

```
Obsidian plugin  →  EC2 dispatcher  ←→  Mac worker  →  vault note
                    (queue + auth)      (yt-dlp,
                                         whisper.cpp,
                                         tesseract,
                                         ollama)
```

- **Plugin** submits a URL, polls for result, writes a markdown note.
- **Dispatcher** (`server/`) runs on a tiny EC2 — just a queue. No media processing.
- **Worker** (`worker/`) runs on the user's Mac via launchd. Pulls jobs, processes locally, posts results back.

## Layout

```
server/   FastAPI dispatcher (deploys to EC2)
worker/   Python worker daemon (runs on Mac)
plugin/   Obsidian plugin (TypeScript, BRAT-installable)
shared/   Schema shared between server and worker
```

See `TECH-SPEC.md` for the PRD, functional criteria, and decisions log.

## Quickstart

```bash
make ci          # lint + test all three components
make dev-server  # run dispatcher locally on :8765
make dev-worker  # run worker, points at local dispatcher
```

Deploy:
- `make deploy-server` — pushes server to EC2, restarts systemd unit.
- `make install-worker` — installs launchd agent on this Mac.
- Plugin releases via `git tag v0.x.x && git push --tags` (GitHub Actions handles the build).

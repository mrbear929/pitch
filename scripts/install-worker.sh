#!/usr/bin/env bash
# Install the Pitch worker on this Mac as a launchd agent.
# Idempotent.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
WORKER_DIR="$HERE/worker"
APP_SUPPORT="$HOME/Library/Application Support/Pitch"
MODELS_DIR="$APP_SUPPORT/models"
PLIST_PATH="$HOME/Library/LaunchAgents/com.mrbear929.pitch-worker.plist"
LOG_DIR="$APP_SUPPORT/logs"
ENV_FILE="$APP_SUPPORT/worker.env"

mkdir -p "$APP_SUPPORT" "$MODELS_DIR" "$LOG_DIR"

echo "==> Checking Homebrew dependencies"
need=()
for tool in ffmpeg tesseract whisper-cpp ollama; do
  if ! command -v "$tool" >/dev/null 2>&1 && ! ls /opt/homebrew/bin/"$tool" >/dev/null 2>&1; then
    need+=("$tool")
  fi
done
if [ ${#need[@]} -gt 0 ]; then
  echo "Installing: ${need[*]}"
  brew install "${need[@]}"
fi
# Tesseract Chinese pack
if ! tesseract --list-langs 2>&1 | grep -q chi_sim; then
  brew install tesseract-lang
fi

echo "==> Pulling Ollama model qwen2.5:7b (skips if present)"
if ! ollama list | awk '{print $1}' | grep -q '^qwen2.5:7b$'; then
  ollama pull qwen2.5:7b
fi

echo "==> Downloading whisper.cpp medium model"
MODEL_FILE="$MODELS_DIR/ggml-medium.bin"
if [ ! -f "$MODEL_FILE" ]; then
  curl -L -o "$MODEL_FILE" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin"
fi

echo "==> Setting up worker venv"
cd "$WORKER_DIR"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -e ../shared --quiet
.venv/bin/pip install -e ../server --quiet
.venv/bin/pip install -e . --quiet

echo "==> Writing worker env (you must fill in dispatcher URL and worker token below)"
if [ ! -f "$ENV_FILE" ]; then
  WBIN=$(which whisper-cli || echo /opt/homebrew/bin/whisper-cli)
  cat > "$ENV_FILE" <<EOF
# Pitch worker environment.
# Fill in PITCH_WORKER_TOKEN, then: launchctl unload + launchctl load -w to apply.
# Values containing spaces MUST be quoted.
PITCH_DISPATCHER_URL="https://tools.mrbear929.com/pitch"
PITCH_WORKER_TOKEN=""
PITCH_WHISPER_BIN="$WBIN"
PITCH_WHISPER_MODEL="$MODEL_FILE"
PITCH_OLLAMA_URL="http://127.0.0.1:11434"
PITCH_OLLAMA_MODEL="qwen2.5:7b"
PITCH_FRAME_EVERY_SECONDS="30"
PITCH_WORK_DIR="$APP_SUPPORT/work"
EOF
  chmod 600 "$ENV_FILE"
  echo "Wrote $ENV_FILE — fill in PITCH_WORKER_TOKEN before loading the agent."
fi

echo "==> Writing wrapper that sources env then execs the worker"
WRAPPER="$APP_SUPPORT/run-worker.sh"
cat > "$WRAPPER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ENV_FILE="$HOME/Library/Application Support/Pitch/worker.env"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
exec "$@"
EOF
chmod +x "$WRAPPER"

echo "==> Writing launchd plist"
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.mrbear929.pitch-worker</string>
  <key>ProgramArguments</key>
  <array>
    <string>$WRAPPER</string>
    <string>$WORKER_DIR/.venv/bin/pitch-worker</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StandardOutPath</key><string>$LOG_DIR/worker.out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/worker.err.log</string>
  <key>WorkingDirectory</key><string>$WORKER_DIR</string>
</dict>
</plist>
EOF

echo
echo "Setup complete."
echo "1. Edit $ENV_FILE and fill in PITCH_WORKER_TOKEN (printed by the EC2 deploy step)."
echo "2. Load the agent:"
echo "     launchctl unload $PLIST_PATH 2>/dev/null || true"
echo "     launchctl load -w $PLIST_PATH"
echo "3. Tail logs:"
echo "     tail -f \"$LOG_DIR/worker.err.log\""

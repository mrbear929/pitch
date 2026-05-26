#!/usr/bin/env bash
# Install the Pitch worker on this Mac as a launchd agent.
# Idempotent.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
WORKER_DIR="$HERE/worker"
APP_SUPPORT="$HOME/Library/Application Support/Pitch"
APP_VENV="$APP_SUPPORT/.venv"
APP_SRC="$APP_SUPPORT/src"
PLIST_PATH="$HOME/Library/LaunchAgents/com.mrbear929.pitch-worker.plist"
LOG_DIR="$APP_SUPPORT/logs"
ENV_FILE="$APP_SUPPORT/worker.env"

mkdir -p "$APP_SUPPORT" "$LOG_DIR"

echo "==> Checking ffmpeg (only local binary still required)"
if ! command -v ffmpeg >/dev/null 2>&1 && ! ls /opt/homebrew/bin/ffmpeg >/dev/null 2>&1; then
  brew install ffmpeg
fi

echo "==> Copying source out of ~/Documents (macOS TCC blocks LaunchAgents from reading there)"
rm -rf "$APP_SRC"
mkdir -p "$APP_SRC"
cp -R "$HERE/shared" "$APP_SRC/"
cp -R "$HERE/server" "$APP_SRC/"
cp -R "$HERE/worker" "$APP_SRC/"
rm -rf "$APP_SRC/server/.venv" "$APP_SRC/worker/.venv"

echo "==> Setting up worker venv"
[ -d "$APP_VENV" ] || python3 -m venv "$APP_VENV"
"$APP_VENV/bin/pip" install --upgrade pip --quiet
"$APP_VENV/bin/pip" install -e "$APP_SRC/shared" --quiet
"$APP_VENV/bin/pip" install -e "$APP_SRC/server" --quiet
"$APP_VENV/bin/pip" install -e "$APP_SRC/worker" --quiet

echo "==> Writing worker env (fill in API keys before loading)"
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<EOF
# Pitch worker environment.
# Get your free keys here:
#   Groq:   https://console.groq.com/keys
#   Gemini: https://aistudio.google.com/apikey
PITCH_DISPATCHER_URL="https://tools.mrbear929.com/pitch"
PITCH_WORKER_TOKEN=""
PITCH_GROQ_API_KEY=""
PITCH_GEMINI_API_KEY=""
PITCH_WORK_DIR="$APP_SUPPORT/work"
EOF
  chmod 600 "$ENV_FILE"
  echo "Wrote $ENV_FILE — fill in PITCH_WORKER_TOKEN, PITCH_GROQ_API_KEY, PITCH_GEMINI_API_KEY before loading."
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
    <string>$APP_VENV/bin/pitch-worker</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StandardOutPath</key><string>$LOG_DIR/worker.out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/worker.err.log</string>
  <key>WorkingDirectory</key><string>$APP_SRC/worker</string>
</dict>
</plist>
EOF

echo
echo "Setup complete."
echo "1. Edit $ENV_FILE and fill in PITCH_WORKER_TOKEN, PITCH_GROQ_API_KEY, PITCH_GEMINI_API_KEY."
echo "2. Load the agent:"
echo "     launchctl unload $PLIST_PATH 2>/dev/null || true"
echo "     launchctl load -w $PLIST_PATH"
echo "3. Tail logs:"
echo "     tail -f \"$LOG_DIR/worker.err.log\""
echo
echo "Optional cleanup of old local-LLM models (no longer used):"
echo "  brew uninstall whisper-cpp tesseract tesseract-lang ollama  # binaries"
echo "  rm \"$APP_SUPPORT/models/ggml-medium.bin\"                  # whisper model (~1.5 GB)"
echo "  ollama rm qwen2.5:7b qwen2.5vl:7b                          # ollama models (~10 GB)"

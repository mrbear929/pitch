#!/usr/bin/env bash
# Deploy the Pitch dispatcher to the EC2 instance.
# Idempotent: safe to re-run.
set -euo pipefail

HOST="${PITCH_HOST:-ubuntu@16.59.18.5}"
KEY="${PITCH_SSH_KEY:-$HOME/.ssh/mrbear929_ec2.pem}"
REPO="${PITCH_REPO:-https://github.com/mrbear929/pitch.git}"
INSTALL_DIR="/opt/pitch"

ssh_cmd() { ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$HOST" "$@"; }
scp_to() { scp -i "$KEY" "$@" "$HOST:$2"; }

echo "==> Ensuring system packages on EC2"
ssh_cmd 'sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv git'

echo "==> Cloning or updating $INSTALL_DIR"
ssh_cmd "
set -euo pipefail
if [ ! -d $INSTALL_DIR ]; then
  sudo mkdir -p $INSTALL_DIR
  sudo chown -R ubuntu:ubuntu $INSTALL_DIR
  git clone $REPO $INSTALL_DIR
else
  cd $INSTALL_DIR && git pull --ff-only
fi
"

echo "==> Installing Python deps in venv"
ssh_cmd "
set -euo pipefail
cd $INSTALL_DIR
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -e shared --quiet
.venv/bin/pip install -e server --quiet
"

echo "==> Generating tokens if missing (one-time)"
ssh_cmd "
set -euo pipefail
ENV_FILE=$INSTALL_DIR/server/.env
if [ ! -f \$ENV_FILE ]; then
  python3 -c 'import secrets; print(\"PITCH_CLIENT_TOKEN=\" + secrets.token_urlsafe(32))' > \$ENV_FILE
  python3 -c 'import secrets; print(\"PITCH_WORKER_TOKEN=\" + secrets.token_urlsafe(32))' >> \$ENV_FILE
  echo \"PITCH_DB_PATH=$INSTALL_DIR/server/jobs.db\" >> \$ENV_FILE
  chmod 600 \$ENV_FILE
fi
"

echo "==> Writing systemd unit"
ssh_cmd "sudo tee /etc/systemd/system/pitch.service > /dev/null <<'EOF'
[Unit]
Description=Pitch dispatcher
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$INSTALL_DIR/server
EnvironmentFile=$INSTALL_DIR/server/.env
ExecStart=$INSTALL_DIR/.venv/bin/uvicorn dispatcher.app:create_app --factory --host 127.0.0.1 --port 8765
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF"

echo "==> Reloading systemd, starting service"
ssh_cmd 'sudo systemctl daemon-reload && sudo systemctl enable --now pitch && sudo systemctl restart pitch'

echo "==> Adding nginx /pitch/ location to tools.mrbear929.com"
ssh_cmd "sudo bash -c 'cat > /etc/nginx/snippets/pitch.conf <<EOF
location /pitch/ {
  proxy_pass http://127.0.0.1:8765/;
  proxy_set_header Host \\\$host;
  proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto \\\$scheme;
  proxy_read_timeout 60s;
  client_max_body_size 50M;
}
EOF'"

# Inject the include into the tools.mrbear929.com server block if not present
ssh_cmd '
set -euo pipefail
SITE=/etc/nginx/sites-enabled/tools.mrbear929.com
if ! sudo grep -q "snippets/pitch.conf" $SITE; then
  sudo sed -i "/server_name tools.mrbear929.com/a \\    include /etc/nginx/snippets/pitch.conf;" $SITE
fi
sudo nginx -t
sudo systemctl reload nginx
'

echo "==> Done. Verifying"
ssh_cmd 'curl -fsS http://127.0.0.1:8765/healthz; echo'
echo
echo "Tokens:"
ssh_cmd "cat $INSTALL_DIR/server/.env"

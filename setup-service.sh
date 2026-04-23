#!/bin/bash
# SiteEye service setup — run on the Pi
# Usage: bash setup-service.sh
#
# Requires ~/.env with:
#   SITEEYE_PROXY=https://your-proxy.example.com
#   TELEGRAM_BOT_TOKEN=...   (optional)
#   TELEGRAM_CHAT_ID=...     (optional)

set -e

echo "=== SiteEye Service Setup ==="

# Ensure .env exists
if [ ! -f ~/.env ]; then
    echo "Creating ~/.env from .env.example — fill in your values!"
    cp "$(dirname "$0")/.env.example" ~/.env
    echo "⚠️  Edit ~/.env before starting the service."
    exit 1
fi
echo "✓ ~/.env found"

# Create systemd service
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CURRENT_USER="$(whoami)"
USER_HOME="$(eval echo ~${CURRENT_USER})"

sudo tee /etc/systemd/system/siteeye.service > /dev/null << EOF
[Unit]
Description=SiteEye — Wearable AI Field Assistant
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${REPO_DIR}
EnvironmentFile=${USER_HOME}/.env
ExecStart=${REPO_DIR}/venv/bin/python3 ${REPO_DIR}/main.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
echo "✓ Created siteeye.service"

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable siteeye.service
sudo systemctl start siteeye.service
echo "✓ Service enabled and started"

echo ""
echo "=== Status ==="
sudo systemctl status siteeye.service --no-pager

echo ""
echo "=== Useful commands ==="
echo "  sudo systemctl status siteeye    # check status"
echo "  sudo journalctl -u siteeye -f    # live logs"
echo "  sudo systemctl restart siteeye   # restart"
echo "  sudo systemctl stop siteeye      # stop"

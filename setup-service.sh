#!/bin/bash
# SiteEye auto-start setup — run on the Pi as pi-molt
# Usage: bash setup-service.sh

set -e

echo "=== SiteEye Service Setup ==="

# Extract API key from .bashrc into .env for systemd
grep "OPENAI_API_KEY" ~/.bashrc | sed 's/export //' > ~/.env
echo "✓ Created ~/.env from .bashrc"

# Create systemd service
sudo tee /etc/systemd/system/siteeye.service > /dev/null << 'EOF'
[Unit]
Description=SiteEye AI Wearable
After=network-online.target amp-keepalive.service
Wants=network-online.target

[Service]
Type=simple
User=pi-molt
WorkingDirectory=/home/pi-molt
EnvironmentFile=/home/pi-molt/.env
ExecStart=/usr/bin/python3 /home/pi-molt/main.py
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

# Show status
echo ""
echo "=== Status ==="
sudo systemctl status siteeye.service --no-pager

echo ""
echo "=== Useful commands ==="
echo "  sudo systemctl status siteeye    # check status"
echo "  sudo journalctl -u siteeye -f    # live logs"
echo "  sudo systemctl restart siteeye   # restart"
echo "  sudo systemctl stop siteeye      # stop"

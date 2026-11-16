#!/usr/bin/env bash
# Run JARVIS on a Linux VPS (Debian/Ubuntu), reachable only from your own devices via Tailscale.
# Usage, as root on the VPS, from a clone of this repo:   sudo bash deploy/vps-setup.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"

apt-get update -qq
apt-get install -y -qq python3 git curl rsync >/dev/null

id jarvis >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin jarvis
mkdir -p /opt/jarvis
rsync -a --delete --exclude .git --exclude data --exclude .env "$SRC"/ /opt/jarvis/
chown -R jarvis:jarvis /opt/jarvis

if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! tailscale status >/dev/null 2>&1; then
  echo "Sign this server in to your Tailscale account (open the link it prints):"
  tailscale up
fi
tailscale set --operator=jarvis

# Phone access: hostname + access code into .env, and publish over HTTPS on the tailnet.
runuser -u jarvis -- bash -c 'cd /opt/jarvis && python3 -m jarvis remote'

install -m 644 /opt/jarvis/deploy/jarvis.service /etc/systemd/system/jarvis.service
systemctl daemon-reload
systemctl enable --now jarvis
sleep 2
systemctl --no-pager --lines=5 status jarvis || true

cat <<MSG

JARVIS is running on this server. Open the address printed above on your iPhone
(Tailscale connected), enter the access code, then Share > Add to Home Screen.

Not available on a server: Mac access, Mail, Calendar and the Mac voice.
For the thinking, install Claude Code as the 'jarvis' user and sign in:
  sudo -u jarvis -H bash -c 'curl -fsSL https://claude.ai/install.sh | bash && ~/.local/bin/claude'
or point JARVIS at an Ollama server in /opt/jarvis/.env.
Logs: journalctl -u jarvis -f     Update: git pull, re-run this script.
MSG

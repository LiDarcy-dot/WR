#!/usr/bin/env bash
# Install a simple authenticated SOCKS5 on your Amnezia/VPS (Debian/Ubuntu).
# Run ON THE SERVER as root:
#   bash setup_tg_socks_vps.sh
#
# Then on the PC bots use:
#   TELEGRAM_PROXY=socks5://tgproxy:PASSWORD@SERVER_IP:1080
set -euo pipefail

PORT="${SOCKS_PORT:-1080}"
USER_NAME="${SOCKS_USER:-tgproxy}"
PASS_WORD="${SOCKS_PASS:-}"

if [[ -z "$PASS_WORD" ]]; then
  PASS_WORD="$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y 3proxy || apt-get install -y 3proxy-bin || true

if ! command -v 3proxy >/dev/null 2>&1; then
  echo "3proxy package missing — installing from source tarball fallback is skipped."
  echo "Install 3proxy manually, then put config at /etc/3proxy/3proxy.cfg"
  exit 1
fi

mkdir -p /etc/3proxy /var/log/3proxy
cat >/etc/3proxy/3proxy.cfg <<EOF
daemon
maxconn 200
nserver 1.1.1.1
nserver 8.8.8.8
nscache 65536
timeouts 1 5 30 60 180 1800 15 60
log /var/log/3proxy/3proxy.log D
logformat "- %U %C:%c %R:%r %O %I %h %T"
auth strong
users ${USER_NAME}:CL:${PASS_WORD}
allow ${USER_NAME}
socks -p${PORT}
EOF

cat >/etc/systemd/system/3proxy-tg.service <<EOF
[Unit]
Description=SOCKS5 for Telegram bots
After=network.target

[Service]
Type=forking
ExecStart=/usr/bin/3proxy /etc/3proxy/3proxy.cfg
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

# binary path may differ
if [[ ! -x /usr/bin/3proxy ]]; then
  BIN="$(command -v 3proxy)"
  sed -i "s|/usr/bin/3proxy|${BIN}|" /etc/systemd/system/3proxy-tg.service
fi

systemctl daemon-reload
systemctl enable --now 3proxy-tg.service

# firewall if ufw present
if command -v ufw >/dev/null 2>&1; then
  ufw allow "${PORT}/tcp" || true
fi

IP="$(curl -4 -s ifconfig.me || curl -4 -s icanhazip.com || echo YOUR_VPS_IP)"
echo
echo "=== SOCKS5 ready ==="
echo "TELEGRAM_PROXY=socks5://${USER_NAME}:${PASS_WORD}@${IP}:${PORT}"
echo
echo "Use the SAME line for the assistant .env and the other bot."
echo "Keep Amnezia full-tunnel VPN OFF on the PC (or exclude browsers)."
echo "Browser for gosuslugi/banks = direct. Only bots use this proxy."

#!/bin/bash
# Installs the listener on Amazon Linux 2023 (also fine on Ubuntu 22.04+ with apt).
# Called by the EC2 user-data in infra/, or run by hand as root on any always-on box.
#
# Required env (written to /etc/wakb.env by the infra, or export them yourself):
#   BRAIN_FUNCTION  name of the brain Lambda
#   AWS_REGION      region of that Lambda
#   ALLOWED_GROUPS  comma-separated group jids or group subjects the bot may answer in
#   ALLOW_DMS       1 to also answer 1:1 chats (default 0)
#   REPO_URL / GIT_REF  where to fetch this repo from (default: GitHub main)
set -euo pipefail
REPO_URL="${REPO_URL:-https://github.com/kobyal/whatsapp-kb-bot.git}"
GIT_REF="${GIT_REF:-main}"

# AL2023 ships node as the nodejs20 package and wires /usr/bin/node through alternatives.
# Do not create /usr/bin/node by hand: a symlink over the alternatives link loops on itself.
# First boot on AL2023 runs its own package transaction for a minute or so; a plain dnf call
# then fails with "can't create transaction lock". Retry instead of dying.
pkg_install() {
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if command -v dnf >/dev/null; then dnf install -y -q "$@" && return 0
    else apt-get update -q && apt-get install -y -q "$@" && return 0; fi
    echo "package manager busy, retry $i"; sleep 10
  done
  return 1
}
if command -v dnf >/dev/null; then pkg_install git nodejs20 nodejs20-npm; else pkg_install git nodejs npm; fi
command -v node >/dev/null || { echo "node is not on PATH after install"; exit 1; }

id wakb >/dev/null 2>&1 || useradd -r -m -d /opt/wakb -s /sbin/nologin wakb
mkdir -p /opt/wakb/data
rm -rf /opt/wakb/src
git clone -q --depth 1 --branch "$GIT_REF" "$REPO_URL" /opt/wakb/src
cd /opt/wakb/src/listener && npm install --omit=dev --no-audit --no-fund --loglevel=error
chown -R wakb:wakb /opt/wakb

if [ ! -f /etc/wakb.env ]; then
  cat > /etc/wakb.env <<ENV
DATA_DIR=/opt/wakb/data
BRAIN_FUNCTION=${BRAIN_FUNCTION:-wakb-brain}
AWS_REGION=${AWS_REGION:-eu-west-1}
ALLOWED_GROUPS="${ALLOWED_GROUPS:-}"
ALLOW_DMS=${ALLOW_DMS:-0}
ENV
  chmod 640 /etc/wakb.env
fi
cp /opt/wakb/src/listener/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wakb wakb-qr
echo "installed. status: $(systemctl is-active wakb) / $(systemctl is-active wakb-qr)"

#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
  -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

architecture="$(dpkg --print-architecture)"
codename="$(. /etc/os-release && printf '%s' "$VERSION_CODENAME")"
printf '%s\n' \
  "deb [arch=${architecture} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${codename} stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -qq
apt-get install -y -qq \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker.service

if [[ ! -e /swapfile ]]; then
  fallocate -l 1G /swapfile
  chmod 0600 /swapfile
  mkswap /swapfile >/dev/null
fi
if ! swapon --show=NAME --noheadings | grep -qx '/swapfile'; then
  swapon /swapfile
fi
if ! grep -qE '^/swapfile[[:space:]]' /etc/fstab; then
  printf '%s\n' '/swapfile none swap sw 0 0' >> /etc/fstab
fi
printf '%s\n' \
  'vm.swappiness=10' \
  'net.ipv4.ip_forward=1' \
  > /etc/sysctl.d/60-task-orchestrator.conf
rm -f /etc/sysctl.d/60-task-orchestrator-swap.conf
sysctl --system >/dev/null

install -d -m 0755 /opt/task-orchestrator/app /etc/task-orchestrator
install -d -m 0755 /var/lib/task-orchestrator
install -d -m 0750 -o 10001 -g 10001 \
  /var/lib/task-orchestrator/agents \
  /var/lib/task-orchestrator/playbook \
  /var/lib/task-orchestrator/reports \
  /var/lib/task-orchestrator/runs
install -d -m 0750 /var/lib/task-orchestrator/caddy

install -m 0755 \
  /opt/task-orchestrator/app/deploy/gcp/metadata-firewall.sh \
  /usr/local/sbin/task-orchestrator-metadata-firewall
install -m 0644 \
  /opt/task-orchestrator/app/deploy/gcp/task-orchestrator-firewall.service \
  /etc/systemd/system/task-orchestrator-firewall.service
install -m 0644 \
  /opt/task-orchestrator/app/deploy/gcp/task-orchestrator.service \
  /etc/systemd/system/task-orchestrator.service

systemctl daemon-reload
systemctl enable task-orchestrator-firewall.service task-orchestrator.service
systemctl restart task-orchestrator-firewall.service

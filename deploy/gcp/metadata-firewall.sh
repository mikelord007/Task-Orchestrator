#!/bin/sh
set -eu

iptables_bin=/usr/sbin/iptables
metadata_ip=169.254.169.254/32

"$iptables_bin" -N DOCKER-USER 2>/dev/null || true

# GCE's guest DNS resolver also uses 169.254.169.254. Block the metadata HTTP
# surfaces while leaving DNS (TCP/UDP 53) available to containers.
while "$iptables_bin" -C DOCKER-USER -d "$metadata_ip" -j REJECT 2>/dev/null; do
  "$iptables_bin" -D DOCKER-USER -d "$metadata_ip" -j REJECT
done
for port in 80 443; do
  if ! "$iptables_bin" -C DOCKER-USER -p tcp -d "$metadata_ip" --dport "$port" -j REJECT 2>/dev/null; then
    "$iptables_bin" -I DOCKER-USER 1 -p tcp -d "$metadata_ip" --dport "$port" -j REJECT
  fi
done

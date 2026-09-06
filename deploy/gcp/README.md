# Google Cloud backend deployment

This bundle runs one non-root, read-only Uvicorn worker behind Caddy on a
single Compute Engine VM. Runtime state (`agents`, `playbook`, `reports`, and
`runs`) is persisted on the VM's 20 GiB standard Persistent Disk. Incomplete
in-process jobs are marked interrupted at the next startup.

Production requires a high-entropy `API_AUTH_TOKEN`. Every route except
`GET /healthz` and CORS `OPTIONS` requires that bearer token. Keep the token in
a root-owned mode-0600 file and never expose it in browser or `NEXT_PUBLIC_*`
configuration. With no authenticated frontend proxy, the Vercel frontend must
remain disconnected.

The VM deployment intentionally has no attached service account. Model keys
are absent initially, so live model-backed jobs fail closed until a provider
is separately configured. `ARCHITECT_ALLOW_GLUE_TOOLS=0` prevents generated
glue-tool packages. No local agents or runtime data should be migrated.

The default Caddyfile requests a Let's Encrypt short-lived certificate for the
reserved public IPv4 address. TCP 80 and 443 must be public for issuance and
traffic. SSH is restricted to Google's IAP TCP-forwarding range. Containers
must be denied access to `169.254.169.254` using a persistent `DOCKER-USER`
rule.

Build and start from the repository root on the VM:

```bash
docker compose --env-file /etc/task-orchestrator/backend.env \
  -f deploy/gcp/compose.yaml up -d --build
```

The host creates a 1 GiB swapfile and the mutable directories owned by
UID/GID 10001. Compose uses bounded local logs, drops all backend capabilities,
adds only `NET_BIND_SERVICE` for Caddy, uses no Docker socket, and runs the
backend root filesystem read-only with one Uvicorn process.

`bootstrap-host.sh` installs Docker from Docker's Debian repository, configures
the 1 GiB swapfile and persistent directories, installs the metadata firewall,
and enables the systemd units. It is idempotent and must run only after the
reviewed source is extracted under `/opt/task-orchestrator/app`.

# Security

Nexus is self-hosted: every installation is run by its own admin, and there is no central service.

## Reporting a vulnerability

Please report security problems **privately**: on GitHub, open the repository's **Security** tab and choose
**Report a vulnerability**. Don't open a public issue for them. Say what an attacker can do, which version
(`nexus --version`) and, if you can, the steps to reproduce it.

## Supported versions

Fixes go into the newest release only. Update with `git pull` and `pip install -e .` (see the README).

## What Nexus protects, and how

- **Secrets** (HenrikDev, Anthropic and YouTube keys, the VAPID private key) live in the database in `data/` and
  are never shown again after saving or included in error messages. Keep `data/` out of git and backups private.
- **Accounts:** passwords are hashed; changing the password logs out other devices.
- **Forms** are only accepted from the site itself (Origin / Referer check); `X-Forwarded-Host` is only trusted from
  a reverse proxy on the same machine or the local network.
- **Redirects** (`?next=`) only go to pages of Nexus.
- **Web search** reads pages only from public addresses (never the server, the LAN or cloud metadata, also after
  redirects), connects to exactly the address it checked, and caps size and type.
- **Backups** only go to folders inside `/mnt`, `/media`, `/srv`, `/home`, `/backup(s)`, `/var/backups` or the data
  folder (more with the environment variable `NEXUS_BACKUP_ROOTS`).
- The systemd service in `deploy/` may only write to the data folder.

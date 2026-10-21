# Hosting Better Every Day privately (only you, from any device)

The app is one Python process (`scripts/tracker_ui.py`) that listens on `127.0.0.1:8787` and keeps everything
local: `state/` (progress, sessions, plans), `config/recall.json` (your Claude API key, gitignored). Nothing is
ever uploaded. The goal is to reach it from your phone or laptop without putting it on the public internet.

## Recommended: Tailscale (10 minutes, free, no open ports)

Tailscale builds a private network between your own devices. The server keeps listening on localhost; Tailscale
fronts it with HTTPS and only devices signed in to *your* Tailscale account can reach it.

1. Install Tailscale on the Windows PC and on your phone/laptop: https://tailscale.com/download. Sign in with the
   same account on both (Google sign-in works).
2. Keep the tracker running on the PC: double-click `tracker.cmd` in the repo (or from Git Bash:
   `PYTHONUTF8=1 python3 scripts/tracker_ui.py`). Leave it up; it is cheap.
3. On the PC, publish the local port to your tailnet only (not the internet). In an elevated PowerShell:
   ```powershell
   tailscale serve --bg http://127.0.0.1:8787
   ```
   Tailscale prints a URL like `https://<pc-name>.<tailnet>.ts.net`. Open it on your phone. Done.
4. Optional: `tailscale serve status` shows what is exposed; `tailscale serve reset` removes it.

Why this is safe: there is no public port, no password form, and no account to create on the app. Access is
decided by Tailscale's device login. The server already accepts the `.ts.net` origin for its POST calls.
Your API key never leaves `config/recall.json` on the PC; the phone only sees the page.

Keep the PC awake: Settings → System → Power → "Never" sleep while plugged in, or use the Task Scheduler entry
`scripts/schedule.sh` installs, which only runs while you are signed in anyway.

## Alternative: Cloudflare Tunnel + Cloudflare Access

Use this if you want a normal domain name and cannot install Tailscale on a device.
1. Own a domain on Cloudflare (free plan is enough).
2. `winget install Cloudflare.cloudflared`, then `cloudflared tunnel login`, `cloudflared tunnel create bed`,
   route `bed.yourdomain.com` to the tunnel, and run `cloudflared tunnel run bed` pointing at
   `http://127.0.0.1:8787`.
3. In Zero Trust → Access → Applications, add `bed.yourdomain.com` with a policy that allows **only your email**
   (one-time PIN). Without this step the page is public: do not skip it.
4. Add `yourdomain.com` to the allowed origins in `scripts/tracker_ui.py` (`do_POST`, the Origin check).

## Not recommended

- A VPS or "deploy to Render/Fly": then your API key and six months of notes live on someone else's box, and
  you must bolt on login, HTTPS and backups yourself. The app was built to stay on your machine.
- Port-forwarding 8787 on the router: exposes the server to the internet with no auth.

## Backups

Everything you would miss is in `state/recall.json`, `state/tracker.json`, `config/recall.json` and
`data/recall-curriculum.json`. Copy `state/` and `config/` to OneDrive or a USB stick once a week, or run
```bash
tar czf "backup-$(date +%F).tgz" state config
```

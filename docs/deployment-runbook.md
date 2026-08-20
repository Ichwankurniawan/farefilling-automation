# Fare Filing Automation — Deployment Runbook

**Audience:** Ops/Infra team deploying the Fare Filing Automation web app.
**Scope:** Internal-only tool, no authentication in this version, single host.
**Target host:** The Linux server already running the self-hosted AI model
(currently reachable at `10.90.10.20:8081`). Deploying alongside it means
the app can call the AI endpoint over `localhost` instead of the network.

If a different host is used instead, everything below still applies —
just point `AI_BASE_URL` (step 4) at wherever the AI endpoint actually is.

---

## 1. What you're deploying

A small FastAPI web app that wraps an existing Python fare-filing pipeline:

- A user fills out a form (Work Order ID, Filing Classification Type,
  Rule & Tariff, uploaded pricebook file(s))
- The app matches files to fare rules, resolves ~29 categories per rule
  (mostly deterministic, with AI fallback for free-text conditions), and
  writes a completed Excel filing
- The user downloads the result automatically once it's done (typically
  2–6 minutes per submission, depending on how many categories need AI)

One Python process serves both the web UI and does the processing work
in a background thread — there is no separate worker/queue service to
deploy.

## 2. Prerequisites on the host

- **Python 3.12** (the app was built and tested against 3.12.0; any
  current 3.12.x should work)
- **~200MB disk** for the Python venv + dependencies, plus ongoing space
  for uploaded pricebooks and generated filings (see §7 — needs a
  retention policy, this is not self-cleaning yet)
- **Network reachability** to the AI endpoint (`AI_BASE_URL` in
  `ai_config.env`, see §4) — if the AI model is on the same host, this
  can be `localhost`, no external network dependency
- **No inbound internet access required** — this is an internal tool

## 3. Getting the code onto the host

This project is not currently in a git repository (no remote to clone
from). Transfer the following directories as a single archive
(`rsync`, `scp`, or a zip) to wherever it should live, e.g.
`/opt/fare-filing/`:

```
fare_filling_poc_v36/
├── fare_filling_poc/     # the pipeline itself
│   └── requirements.txt  # includes fastapi/uvicorn now — see note below
├── webapp/                # the FastAPI wrapper + UI
│   └── static/
├── template/               # SQ Fare Filling Template.xlsx -- required, do not omit
└── input_files/             # only needed if ops wants to smoke-test with real samples
```

Do **not** transfer `fare_filling_poc/.venv/` (Windows-specific, rebuild
fresh on Linux — see §5) or `webapp/uploads/` / `webapp/outputs/` from
the dev machine (leftover test artifacts, not needed).

## 4. Configuration — `ai_config.env`

This file is intentionally excluded from any code transfer (it's treated
as local, gitignored-style config, never committed). Create it fresh at
`fare_filling_poc/ai_config.env` on the host:

```
AI_PROVIDER=openai_compatible
AI_BASE_URL=http://localhost:8081/v1
AI_MODEL=qwen3.6:35b-a3b-uncensored
AI_MAX_TOKENS=4000
```

Adjust `AI_BASE_URL` if the AI model isn't on `localhost` for this
deployment. `AI_API_KEY` is optional and can be omitted — the self-hosted
endpoint doesn't require one.

## 5. Python environment

```bash
cd /opt/fare-filing/fare_filling_poc_v36/fare_filling_poc
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

That single `requirements.txt` now includes `fastapi`, `uvicorn`,
`starlette`, and `python-multipart` alongside the pipeline's own
dependencies (`openpyxl`, `PyYAML`, `anthropic`, `openai`, etc.) — one
venv serves both the web layer and the pipeline, no separate install step.

**Smoke test before wiring up systemd:**

```bash
cd /opt/fare-filing/fare_filling_poc_v36
fare_filling_poc/.venv/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
# in another shell:
curl http://127.0.0.1:8000/api/health
# expect: {"status":"ok"}
```

Ctrl-C once confirmed, then proceed to §6.

## 6. Running it as a service (systemd)

Create `/etc/systemd/system/fare-filing.service`:

```ini
[Unit]
Description=Fare Filing Automation
After=network.target

[Service]
Type=simple
User=fare-filing
Group=fare-filing
WorkingDirectory=/opt/fare-filing/fare_filling_poc_v36
ExecStart=/opt/fare-filing/fare_filling_poc_v36/fare_filling_poc/.venv/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Run as a dedicated non-root `fare-filing` user (create with
`useradd -r -s /usr/sbin/nologin fare-filing`, then `chown -R
fare-filing:fare-filing /opt/fare-filing`) rather than root — the process
only needs write access to `webapp/uploads/` and `webapp/outputs/`.

Bind to `127.0.0.1`, not `0.0.0.0` — nginx (§8) is the only thing that
should be reachable from the rest of the network; nothing needs to hit
uvicorn directly.

```bash
systemctl daemon-reload
systemctl enable fare-filing
systemctl start fare-filing
systemctl status fare-filing   # confirm "active (running)"
journalctl -u fare-filing -f   # tail logs
```

Auto-restarts on crash (`Restart=on-failure`) and on host reboot
(`enable`). See §9 for what a restart actually loses.

## 7. Storage — needs a retention policy before going live unattended

`webapp/uploads/` and `webapp/outputs/` grow with every submission —
nothing deletes old job files automatically yet. Before this runs
unattended for weeks, add a daily cleanup job. Simple cron-based version:

```bash
# /etc/cron.d/fare-filing-cleanup
0 3 * * * fare-filing find /opt/fare-filing/fare_filling_poc_v36/webapp/uploads -mindepth 1 -maxdepth 1 -mtime +30 -exec rm -rf {} \;
0 3 * * * fare-filing find /opt/fare-filing/fare_filling_poc_v36/webapp/outputs -mindepth 1 -maxdepth 1 -mtime +30 -exec rm -rf {} \;
```

Adjust the 30-day window to whatever retention makes sense — this is a
placeholder, not a confirmed policy. Monitor disk usage on this path
until real usage volume is known.

## 8. Reverse proxy (nginx)

Not for auth (there isn't any in this version) — this is for a stable
URL, upload size handling, and a place to add TLS/auth later without
re-architecting anything. Ops/Infra owns the actual domain — this is a
minimal example to adapt:

```nginx
server {
    listen 80;
    server_name <hostname to be assigned by ops/infra>;

    client_max_body_size 20M;   # real pricebook files run 1-2MB; headroom for batches

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

No special proxy timeout tuning needed — processing happens in a
background thread server-side, and the browser only ever makes short
polling requests (every 2s) to check status, never one long-held request
for the full multi-minute run.

## 9. What a restart actually loses

Job status/progress is tracked in-memory only, not in a database. If the
service restarts (deploy, crash, host reboot) while a job is queued or
running:

- **That job's status is lost** — the browser tab polling it will start
  getting 404s. The user would need to resubmit.
- **Completed output files are NOT lost** — they're already written to
  `webapp/outputs/` before the job is marked done, they just become
  unreachable via the job-ID download link after a restart (the file
  itself is still on disk, findable by filename/timestamp if needed).
- **In-flight AI calls are simply killed mid-request** — no partial/corrupt
  output is produced, since the file is only written at the very end of
  a successful run.

Accepted tradeoff for this version, not a bug to fix urgently — plan
deploys/restarts for low-usage windows if possible.

## 10. Verifying the deployment

```bash
curl http://127.0.0.1:8000/api/health          # {"status":"ok"}
curl -I http://<nginx-host>/                    # 200, served through nginx
```

Then a real end-to-end submission is the only way to confirm the AI
endpoint is actually reachable from this host — the health check above
only confirms the web server itself is up, not that `AI_BASE_URL` is
correct or reachable. Use a real pricebook file from `input_files/` (or
have the requesting user run one real filing) and confirm it completes
and downloads.

## 11. Updating the deployed code later

```bash
systemctl stop fare-filing
# replace fare_filling_poc/ and webapp/ with the new version
# (leave webapp/uploads/, webapp/outputs/, and ai_config.env untouched)
fare_filling_poc/.venv/bin/pip install -r fare_filling_poc/requirements.txt   # in case deps changed
systemctl start fare-filing
```

Any job running at stop-time is lost per §9 — schedule updates for a
quiet window, or add a simple "drain" step (stop accepting new
submissions, wait for the queue to empty) if that becomes worth building.

## 12. Open items for Ops/Infra to decide

- **Hostname/domain** and whether TLS is needed — both explicitly deferred
  to your team; the nginx config above is a starting point, not final
- **Retention window** for §7 — 30 days is a placeholder
- **Monitoring** — `GET /api/health` is available for whatever uptime
  check you already use; nothing beyond that is wired up yet (no metrics
  endpoint, no alerting)

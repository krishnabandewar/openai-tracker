# OpenAI Status Tracker

A **lightweight, async Python service** that automatically monitors the [OpenAI Status Page](https://status.openai.com) and logs new incident updates to the console in real-time — with no manual refresh, no aggressive polling, and built to scale to 100+ providers.

---

## 🔗 Live Deployment

**GitHub Actions (runs every 15 minutes automatically):**
👉 https://github.com/krishnabandewar/openai-tracker/actions

Click any workflow run → click the **"track"** job → see live console output.

---

## 🚀 Quick Start

```bash
# 1. Create and activate a virtual environment (recommended)
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the tracker
python tracker.py
```

### Docker

```bash
docker build -t openai-tracker .
docker run --rm openai-tracker
```

---

## 📋 Real Output (Live Data from OpenAI API)

```
🔍 Tracking 1 provider(s). Polling every 60s. Press Ctrl+C to stop.
============================================================

[2026-01-27 14:31:56]
Provider : OpenAI
Incident : Elevated Codex Error Rate
Product  : OpenAI API
Status   : Investigating (impact: minor)
------------------------------------------------------------

[2026-01-27 16:14:15]
Provider : OpenAI
Incident : Elevated Codex Error Rate
Product  : OpenAI API
Status   : Monitoring (impact: minor)
------------------------------------------------------------

[2026-01-27 16:33:26]
Provider : OpenAI
Incident : Elevated Codex Error Rate
Product  : OpenAI API
Status   : Resolved (impact: minor)
------------------------------------------------------------
```

The tracker picks up each stage of an incident lifecycle:
`Investigating` → `Identified` → `Monitoring` → `Resolved`

---

## 🏗️ Architecture — Three-Layer Separation

```
StatusPageFetcher  →  ChangeDetector  →  ConsoleOutputHandler
   (HTTP I/O)          (state/logic)       (formatting/output)
```

| Layer | Class | Responsibility |
|---|---|---|
| **Fetch** | `StatusPageFetcher` | HTTP I/O only — retrieves raw JSON, handles ETag caching |
| **Detect** | `ChangeDetector` | Stateful comparison — finds genuinely new updates |
| **Output** | `ConsoleOutputHandler` | Formats and writes to stdout |

Each layer is **independently testable and replaceable** — swap `ConsoleOutputHandler` for a Slack notifier, PagerDuty alert, or database writer without touching any other layer.

---

## 🔍 Design Decisions

### 1. Why `asyncio` + `aiohttp`?

The assignment requires a solution that can scale to **100+ status pages** without aggressive polling. Using `asyncio`:

- Every provider runs as its own **concurrent coroutine** (no threads, no blocking)
- All providers share a **single `aiohttp.ClientSession`** with `TCPConnector` for connection pooling
- Adding a new provider = one line of code + zero additional resource cost
- A synchronous `requests`-based approach would block per HTTP call — unacceptable at 100+ providers

### 2. Change Detection via Incident Update IDs

Each incident update from the Statuspage v2 API has a **stable, unique ID** (e.g., `01KFK38J6HGEFWHZ0TG9MKMJA2`). The `ChangeDetector` maintains a `set` of `(incident_id, update_id)` tuples already seen.

On each poll:
1. Fetch latest JSON
2. Walk every `incident → incident_updates[]`
3. Any unseen `(incident_id, update_id)` pair → log it and mark as seen

This is **O(1) per lookup** and avoids all timestamp edge cases (clock skew, same-second updates, timezone differences).

### 3. Bandwidth Efficiency — ETag / Last-Modified

`StatusPageFetcher` caches the `ETag` and `Last-Modified` headers from each response and sends them as `If-None-Match` / `If-Modified-Since` on the next request.

When nothing has changed, the server replies with **304 Not Modified** (empty body) — zero wasted bandwidth. Critical when polling 100+ providers frequently.

### 4. Graceful Body Fallback

The OpenAI Statuspage API currently returns **empty `body` strings** on incident updates. The tracker handles this gracefully:

```python
if update.body:
    status_line = update.body                          # Rich text when available
else:
    status_line = f"{update.update_status.capitalize()} (impact: {update.impact})"
    # e.g. "Resolved (impact: critical)"
```

This is future-proof — if OpenAI populates `body` again, richer descriptions are automatically shown.

### 5. No Unnecessary Complexity

- **No database** — state lives in memory (`set`). On restart, current open incidents are re-discovered by design.
- **No AI/ML** — pure HTTP + JSON parsing.
- **No heavy frameworks** — single file + one dependency (`aiohttp`).

---

## 📈 Scaling to 100+ Providers

Any service running [Atlassian Statuspage](https://www.atlassian.com/software/statuspage) exposes the same `/api/v2/incidents.json` endpoint. To add providers, just append to `STATUS_PROVIDERS` in `tracker.py`:

```python
STATUS_PROVIDERS: list[tuple[str, str]] = [
    ("OpenAI",     "https://status.openai.com/api/v2/incidents.json"),
    ("Stripe",     "https://status.stripe.com/api/v2/incidents.json"),
    ("GitHub",     "https://www.githubstatus.com/api/v2/incidents.json"),
    ("Cloudflare", "https://www.cloudflarestatus.com/api/v2/incidents.json"),
    ("Twilio",     "https://status.twilio.com/api/v2/incidents.json"),
    ("Datadog",    "https://status.datadoghq.com/api/v2/incidents.json"),
    # ... add as many as needed, no other code changes required
]
```

Each provider gets:
- Its **own `asyncio.Task`** — failures and slowness are fully isolated
- Its **own `ChangeDetector`** — independent state, no cross-contamination
- A **shared `StatusPageFetcher`** + `ClientSession` — connection pooling across all

---

## 📁 Project Structure

```
openai-tracker/
├── tracker.py                        # Main application (fetcher + detector + output)
├── requirements.txt                  # Python dependencies (aiohttp only)
├── Dockerfile                        # Container definition (python:3.12-slim)
├── .github/
│   └── workflows/
│       └── tracker.yml               # GitHub Actions — runs every 15 minutes
└── README.md                         # This file
```

---

## ⚙️ GitHub Actions Deployment

The included workflow (`.github/workflows/tracker.yml`) runs the tracker every 15 minutes automatically on GitHub's free infrastructure:

```yaml
on:
  schedule:
    - cron: '*/15 * * * *'   # every 15 minutes
  workflow_dispatch:          # manual trigger from GitHub UI
```

**Live logs:** https://github.com/krishnabandewar/openai-tracker/actions

---

## 📦 Dependencies

| Package | Version | Purpose |
|---|---|---|
| `aiohttp` | ≥ 3.9.0 | Async HTTP client with connection pooling |

**Python ≥ 3.11** required (`X | Y` union types, improved `datetime.fromisoformat`).

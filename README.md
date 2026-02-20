# OpenAI Status Tracker

A lightweight, async Python service that monitors the **OpenAI Status Page** (and any other Statuspage v2-compatible endpoint) and logs **new** incident updates to the console in real-time.

---

## Quick Start

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

## Example Output

```
🔍 Tracking 1 provider(s). Polling every 60s. Press Ctrl+C to stop.
============================================================

[2025-11-03 14:32:00]
Provider : OpenAI
Incident : Elevated error rates for Chat Completions
Product  : OpenAI API – Chat Completions
Status   : Degraded performance due to upstream issue
------------------------------------------------------------
```

---

## Architecture & Design Choices

### Three-Layer Separation

| Layer | Class | Responsibility |
|---|---|---|
| **Fetch** | `StatusPageFetcher` | HTTP I/O only — retrieves raw JSON |
| **Detect** | `ChangeDetector` | Stateful comparison; finds genuinely new updates |
| **Output** | `ConsoleOutputHandler` | Formats and writes to stdout |

Each layer is independently testable and replaceable (e.g., swap `ConsoleOutputHandler` for a Slack notifier without touching fetch or detect logic).

---

### Why `asyncio` + `aiohttp`?

The assignment explicitly warns against "aggressive polling loops". `asyncio` lets every provider run as a **concurrent coroutine** — all providers share a single OS thread and a single `aiohttp.ClientSession` (with connection pooling via `TCPConnector`). Adding a 101st provider costs virtually nothing in CPU or memory.

A synchronous `requests`-based loop would block the thread per HTTP call, making it unsuitable for monitoring 100+ pages simultaneously.

---

### Change Detection Strategy

New incidents updates are identified using **incident update IDs** (stable, opaque strings assigned by Statuspage). A `set` of `(incident_id, update_id)` tuples (`seen`) is maintained in memory per provider.

On each poll:
1. Fetch latest incidents JSON.
2. Walk every `incident → incident_updates[]` entry.
3. Any `(incident_id, update_id)` pair **not** in `seen` is new — log it and add to `seen`.

This is O(1) per update lookup and avoids timestamp-comparison edge cases (clock skew, same-second updates).

---

### Bandwidth Efficiency — ETag / Last-Modified

`StatusPageFetcher` stores the `ETag` and `Last-Modified` response headers from the previous successful response and sends them back as `If-None-Match` / `If-Modified-Since` on the next request.

When nothing has changed, the server responds **304 Not Modified** with an empty body — zero redundant data transfer. This is especially valuable at short poll intervals or when tracking many providers.

---

### Scalability to 100+ Providers

```python
STATUS_PROVIDERS: list[tuple[str, str]] = [
    ("OpenAI",  "https://status.openai.com/api/v2/incidents.json"),
    ("Stripe",  "https://status.stripe.com/api/v2/incidents.json"),
    ("AWS",     "https://status.aws.amazon.com/incidents.json"),
    # ... add as many as needed
]
```

Each provider gets:
- Its **own `asyncio` task** — polled independently, failures are isolated.
- Its **own `ChangeDetector`** — state is not shared between providers.
- A **shared `StatusPageFetcher`** and `aiohttp.ClientSession` — connection pooling without duplication.

Per-provider poll intervals can be configured individually by passing a different `poll_interval` per task.

---

### No Unnecessary Complexity

- **No database** — state lives in a Python `set`. Restarting the process re-discovers all currently open incidents (by design — you always want current state on startup).
- **No AI/ML** — pure HTTP + JSON parsing.
- **No heavy frameworks** — single file + one dependency (`aiohttp`).

---

## Files

```
bolna-assignment/
├── tracker.py          # Main application
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container definition
└── README.md           # This file
```

---

## Extending to Other Providers

Any service using Atlassian Statuspage (the most common SaaS status-page platform) exposes the same `/api/v2/incidents.json` endpoint. To add a new provider, simply append a tuple to `STATUS_PROVIDERS` in `tracker.py`:

```python
STATUS_PROVIDERS = [
    ("OpenAI",     "https://status.openai.com/api/v2/incidents.json"),
    ("Stripe",     "https://status.stripe.com/api/v2/incidents.json"),
    ("GitHub",     "https://www.githubstatus.com/api/v2/incidents.json"),
    ("Cloudflare", "https://www.cloudflarestatus.com/api/v2/incidents.json"),
    ("Twilio",     "https://status.twilio.com/api/v2/incidents.json"),
]
```

No other code changes are needed.

---

## Dependencies

| Package | Purpose |
|---|---|
| `aiohttp` | Async HTTP client with connection pooling |

Python ≥ 3.11 recommended (uses `|` union type hints and `datetime.fromisoformat` improvements).

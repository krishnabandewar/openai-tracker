"""
tracker.py — OpenAI Status Page Tracker
========================================
A lightweight, async Python service that detects and logs NEW incidents
or incident updates from the OpenAI Statuspage API.

Architecture:
  - Fetcher     : Retrieves raw JSON from a status-page endpoint.
  - Detector    : Compares new data against known state to find new updates.
  - Output      : Formats and prints new updates to the console.

Designed to scale to 100+ providers by treating each provider as an
independent, long-running async task (coroutine) sharing a single
aiohttp ClientSession for connection pooling.
"""

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import aiohttp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Each entry: (human-readable name, URL of the Statuspage incidents JSON)
STATUS_PROVIDERS: list[tuple[str, str]] = [
    (
        "OpenAI",
        "https://status.openai.com/api/v2/incidents.json",
    ),
    # Uncomment to track additional providers:
    # ("Stripe",  "https://status.stripe.com/api/v2/incidents.json"),
    # ("AWS",     "https://status.aws.amazon.com/incidents.json"),
]

# How often (in seconds) to poll. Tune per-provider if needed.
DEFAULT_POLL_INTERVAL: int = 60  # 1 minute


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class IncidentUpdate:
    """Represents a single update entry inside an incident."""
    incident_id: str
    incident_name: str
    update_id: str
    created_at: str          # ISO-8601 string from the API
    body: str                # Human-readable status message (may be empty)
    update_status: str       # Lifecycle status: investigating / identified / monitoring / resolved
    impact: str              # Incident impact level: none / minor / major / critical
    affected_components: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Layer 1 — Fetcher
# ---------------------------------------------------------------------------

class StatusPageFetcher:
    """
    Retrieves the raw incidents payload from a Statuspage v2 API endpoint.

    Uses ETag / Last-Modified for conditional requests to minimise
    bandwidth and avoid redundant processing when nothing has changed.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        # Map[url -> {etag, last_modified}] for conditional-GET headers
        self._cache: dict[str, dict[str, str]] = {}

    async def fetch(self, url: str) -> dict[str, Any] | None:
        """
        Fetch the incidents JSON.

        Returns the parsed JSON dict when the server returns new data,
        or None when the server responds with 304 Not Modified.
        """
        request_headers: dict[str, str] = {}
        cached = self._cache.get(url, {})
        if etag := cached.get("etag"):
            request_headers["If-None-Match"] = etag
        if last_modified := cached.get("last_modified"):
            request_headers["If-Modified-Since"] = last_modified

        try:
            async with self._session.get(
                url, headers=request_headers, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status == 304:
                    logging.debug("304 Not Modified — no new data at %s", url)
                    return None

                response.raise_for_status()

                # Update cached validators for next request
                new_cache: dict[str, str] = {}
                if etag_value := response.headers.get("ETag"):
                    new_cache["etag"] = etag_value
                if lm_value := response.headers.get("Last-Modified"):
                    new_cache["last_modified"] = lm_value
                self._cache[url] = new_cache

                return await response.json(content_type=None)

        except aiohttp.ClientError as exc:
            logging.warning("HTTP error fetching %s: %s", url, exc)
            return None
        except asyncio.TimeoutError:
            logging.warning("Timeout fetching %s", url)
            return None


# ---------------------------------------------------------------------------
# Layer 2 — Change Detector
# ---------------------------------------------------------------------------

class ChangeDetector:
    """
    Stateful detector that identifies genuinely NEW incident updates.

    State is kept entirely in memory:
      seen_update_ids  — set of (incident_id, update_id) tuples already logged.

    This approach is O(1) per update check and trivially extensible.
    """

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def find_new_updates(self, data: dict[str, Any]) -> list[IncidentUpdate]:
        """
        Parse the Statuspage v2 incidents payload and return only updates
        that have not been seen before.
        """
        new_updates: list[IncidentUpdate] = []

        for incident in data.get("incidents", []):
            inc_id: str = incident.get("id", "")
            inc_name: str = incident.get("name", "Unknown incident")
            inc_impact: str = incident.get("impact", "unknown")

            # Affected component names (may be empty list)
            affected: list[str] = [
                c.get("name", "")
                for c in incident.get("components", [])
                if c.get("name")
            ]

            for update in incident.get("incident_updates", []):
                upd_id: str = update.get("id", "")
                key = (inc_id, upd_id)

                if key in self._seen:
                    continue  # Already reported

                self._seen.add(key)
                new_updates.append(
                    IncidentUpdate(
                        incident_id=inc_id,
                        incident_name=inc_name,
                        update_id=upd_id,
                        created_at=update.get("created_at", ""),
                        body=update.get("body", "").strip(),
                        update_status=update.get("status", "unknown"),
                        impact=inc_impact,
                        affected_components=affected,
                    )
                )

        return new_updates


# ---------------------------------------------------------------------------
# Layer 3 — Output Handler
# ---------------------------------------------------------------------------

class ConsoleOutputHandler:
    """
    Formats and writes incident update records to stdout.

    Keeping output separate from detection/fetching makes it trivial to
    swap in a different sink (Slack, PagerDuty, database, etc.) later.
    """

    def emit(self, provider_name: str, update: IncidentUpdate) -> None:
        """Print a single incident update to the console."""
        # Parse the ISO-8601 timestamp and convert to local-ish display
        try:
            dt = datetime.fromisoformat(
                update.created_at.replace("Z", "+00:00")
            ).astimezone()
            ts = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            ts = update.created_at or "N/A"

        product_label = (
            ", ".join(update.affected_components)
            if update.affected_components
            else f"{provider_name} API"
        )

        # Body is the richest description; fall back to structured fields
        # when the provider leaves body empty (current OpenAI behavior).
        if update.body:
            status_line = update.body
        else:
            status_line = (
                f"{update.update_status.capitalize()} "
                f"(impact: {update.impact})"
            )

        print(
            f"\n[{ts}]\n"
            f"Provider : {provider_name}\n"
            f"Incident : {update.incident_name}\n"
            f"Product  : {product_label}\n"
            f"Status   : {status_line}\n"
            + "-" * 60,
            flush=True,
        )


# ---------------------------------------------------------------------------
# Orchestrator — ties the three layers together per provider
# ---------------------------------------------------------------------------

async def monitor_provider(
    provider_name: str,
    url: str,
    fetcher: StatusPageFetcher,
    detector: ChangeDetector,
    output: ConsoleOutputHandler,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
) -> None:
    """
    Continuously monitors a single status-page provider.

    Each provider runs as its own async task so all providers are polled
    concurrently without blocking each other.
    """
    logging.info("Starting monitor for %s (poll every %ds)", provider_name, poll_interval)

    while True:
        data = await fetcher.fetch(url)

        if data is not None:
            new_updates = detector.find_new_updates(data)

            if not new_updates:
                logging.debug("No new updates from %s", provider_name)
            else:
                for upd in new_updates:
                    output.emit(provider_name, upd)

        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    output = ConsoleOutputHandler()

    # A single shared ClientSession enables connection pooling across all
    # provider tasks — critical for scaling to many concurrent monitors.
    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        fetcher = StatusPageFetcher(session)

        tasks = [
            asyncio.create_task(
                monitor_provider(
                    provider_name=name,
                    url=url,
                    fetcher=fetcher,
                    detector=ChangeDetector(),   # independent state per provider
                    output=output,
                    poll_interval=DEFAULT_POLL_INTERVAL,
                )
            )
            for name, url in STATUS_PROVIDERS
        ]

        print(
            f"🔍 Tracking {len(STATUS_PROVIDERS)} provider(s). "
            f"Polling every {DEFAULT_POLL_INTERVAL}s. Press Ctrl+C to stop.\n"
            + "=" * 60,
            flush=True,
        )

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTracker stopped.")

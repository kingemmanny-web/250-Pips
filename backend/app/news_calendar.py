from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from urllib.request import Request, urlopen
from typing import Any


class EconomicCalendar:
    def __init__(self) -> None:
        self.url = os.getenv("ECONOMIC_CALENDAR_URL", "https://nfs.faireconomy.media/ff_calendar_thisweek.json")
        self.cache_seconds = int(os.getenv("ECONOMIC_CALENDAR_CACHE_SECONDS", "900"))
        self.before_minutes = int(os.getenv("NEWS_BLACKOUT_BEFORE_MINUTES", "30"))
        self.after_minutes = int(os.getenv("NEWS_BLACKOUT_AFTER_MINUTES", "30"))
        self.fail_closed = os.getenv("NEWS_FAIL_CLOSED", "true").lower() == "true"
        self._events: list[dict[str, Any]] = []
        self._loaded_at = 0.0
        self._error: str | None = None

    def status(self) -> dict[str, Any]:
        self._refresh()
        return {"provider": self.url, "events_cached": len(self._events), "loaded_at": self._loaded_at or None, "error": self._error, "fail_closed": self.fail_closed}

    def blocked(self, instrument: str, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        self._refresh()
        currencies = {instrument[:3].upper(), instrument[3:6].upper()} if len(instrument) >= 6 else set()
        for event in self._events:
            if event.get("impact", "").lower() not in {"high", "3", "red"} or event.get("currency", "").upper() not in currencies:
                continue
            event_time = self._event_time(event)
            if event_time is None:
                continue
            window_start = event_time - timedelta(minutes=self.before_minutes)
            window_end = event_time + timedelta(minutes=self.after_minutes)
            if window_start <= current <= window_end:
                return {"blocked": True, "reason": f"High-impact {event.get('currency', '')} event: {event.get('title', 'economic release')}", "event": event}
        if self._error and self.fail_closed:
            return {"blocked": True, "reason": f"Economic calendar unavailable: {self._error}"}
        return {"blocked": False, "reason": "No high-impact event in the configured blackout window"}

    def _refresh(self) -> None:
        if time.time() - self._loaded_at < self.cache_seconds:
            return
        try:
            request = Request(self.url, headers={"User-Agent": "250-Pips-Trading-Bot/1.0"})
            with urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self._events = payload if isinstance(payload, list) else payload.get("events", [])
            self._error = None
            self._loaded_at = time.time()
        except Exception as error:
            self._error = str(error)
            self._loaded_at = time.time()

    @staticmethod
    def _event_time(event: dict[str, Any]) -> datetime | None:
        raw = event.get("date") or event.get("datetime") or event.get("timestamp")
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw, UTC)
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None

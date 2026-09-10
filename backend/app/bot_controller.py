from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any, Callable


class BotController:
    def __init__(self, interval_seconds: int, analyze: Callable[[], dict[str, Any]], execute: Callable[[dict[str, Any]], dict[str, Any]], manage: Callable[[str], dict[str, Any] | None]):
        self.interval_seconds = max(10, interval_seconds)
        self.analyze = analyze
        self.execute = execute
        self.manage = manage
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._status: dict[str, Any] = {
            "running": False,
            "mode": "live",
            "state": "stopped",
            "last_analysis": None,
            "last_trade": None,
            "last_error": None,
        }

    def start(self, mode: str) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.snapshot()
            self._stop_event.clear()
            self._status.update({"running": True, "mode": mode, "state": "starting", "last_error": None})
            self._thread = threading.Thread(target=self._run, name="250-pips-bot", daemon=True)
            self._thread.start()
            return self.snapshot()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        with self._lock:
            self._status.update({"running": False, "state": "stopped"})
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                managed = self.manage(self.snapshot()["mode"])
                if managed is not None:
                    with self._lock:
                        self._status.update({"state": managed["state"], "last_trade": managed.get("trade", self._status.get("last_trade")), "last_error": None})
                    self._stop_event.wait(self.interval_seconds)
                    continue
                analysis = self.analyze()
                with self._lock:
                    self._status.update({"state": "analyzing", "last_analysis": analysis, "last_error": None})
                if analysis.get("decision") == "TRADE":
                    trade = self.execute(analysis)
                    with self._lock:
                        self._status.update({"state": "trade_opened", "last_trade": trade})
                else:
                    with self._lock:
                        self._status["state"] = "waiting"
            except Exception as error:
                with self._lock:
                    self._status.update({"state": "error", "last_error": str(error)})
            self._stop_event.wait(self.interval_seconds)

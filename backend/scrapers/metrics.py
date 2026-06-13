from __future__ import annotations
import os
import threading
import time

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


class RamSampler:
    """Background daemon thread that samples process RSS every interval_s seconds.

    stop() is idempotent and does NOT join the thread (avoids blocking the async
    event loop). The daemon thread exits within one interval on process shutdown.
    """

    def __init__(self, interval_s: float = 5.0) -> None:
        self._interval = interval_s
        self._stop = threading.Event()
        self._peak_mb = 0
        self._total_mb = 0
        self._samples = 0
        self._proc = psutil.Process(os.getpid()) if _HAS_PSUTIL else None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(timeout=self._interval):
            if self._proc:
                try:
                    mb = self._proc.memory_info().rss // (1024 * 1024)
                    self._peak_mb = max(self._peak_mb, mb)
                    self._total_mb += mb
                    self._samples += 1
                except Exception:
                    pass

    def stop(self) -> tuple[int, int]:
        """Signal stop and return (peak_mb, avg_mb). Safe to call multiple times."""
        self._stop.set()
        peak = self._peak_mb
        avg = (self._total_mb // self._samples) if self._samples else peak
        return peak, avg


class RunMetrics:
    """Thread-safe scraper run metrics collector."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._phases: dict[str, float] = {}
        self._phase_start: dict[str, float] = {}
        self._cooldowns = 0
        self._attempted = 0
        self._skipped = 0
        self._failed = 0

    def phase_start(self, name: str) -> None:
        with self._lock:
            self._phase_start[name] = time.monotonic()

    def phase_end(self, name: str) -> None:
        with self._lock:
            t0 = self._phase_start.pop(name, None)
            if t0 is not None:
                self._phases[name] = round(time.monotonic() - t0, 1)

    def cooldown(self) -> None:
        with self._lock:
            self._cooldowns += 1

    def attempt(self, n: int = 1) -> None:
        with self._lock:
            self._attempted += n

    def skip(self, n: int = 1) -> None:
        with self._lock:
            self._skipped += n

    def fail(self, n: int = 1) -> None:
        with self._lock:
            self._failed += n

    @property
    def phase_durations(self) -> dict[str, float]:
        with self._lock:
            return dict(self._phases)

    @property
    def cooldown_hits(self) -> int:
        with self._lock:
            return self._cooldowns

    @property
    def items_attempted(self) -> int:
        with self._lock:
            return self._attempted

    @property
    def items_skipped(self) -> int:
        with self._lock:
            return self._skipped

    @property
    def items_failed(self) -> int:
        with self._lock:
            return self._failed

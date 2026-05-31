"""Frame-time accumulator for the ``--profile-frames`` client flag.

Pure Python (no pygame): collects named per-section millisecond samples
and prints percentile summaries to stderr once per window, then resets.
Clients build one only when profiling is enabled, so the normal path
pays nothing. This exists to *measure* the client (which had no frame
instrumentation) — not to optimize anything yet.
"""

from __future__ import annotations

import sys


def percentile(samples: list[float], pct: float) -> float:
    """Return the ``pct`` (0-100) percentile of ``samples``.

    Nearest-rank on the sorted samples; empty input yields 0.0. Good
    enough to eyeball frame-time spread — not a statistics library.
    """
    if not samples:
        return 0.0
    ordered = sorted(samples)
    rank = round(pct / 100.0 * (len(ordered) - 1))
    return ordered[rank]


class FrameProfiler:
    """Accumulate named ms samples; flush percentiles once per window."""

    def __init__(self, label: str = "[frames]", every_s: float = 2.0) -> None:
        self.label = label
        self.every_s = every_s
        self._samples: dict[str, list[float]] = {}
        self._frames = 0
        self._window_start: float | None = None

    def add(self, name: str, ms: float) -> None:
        """Record one ``ms`` sample under section ``name``."""
        self._samples.setdefault(name, []).append(ms)

    def frame_done(self, now: float) -> None:
        """Mark one rendered frame at time ``now`` (seconds).

        Flushes a report once the open window reaches ``every_s``.
        """
        self._frames += 1
        if self._window_start is None:
            self._window_start = now
        elif now - self._window_start >= self.every_s:
            self.flush(now)

    def flush(self, now: float) -> None:
        """Print one summary line and start a fresh window at ``now``."""
        if self._window_start is None or self._frames == 0:
            return
        span = now - self._window_start
        fps = self._frames / span if span > 0 else 0.0
        parts = [f"{self.label} fps={fps:.1f}"]
        for name, xs in self._samples.items():
            parts.append(
                f"{name}=p50:{percentile(xs, 50):.2f}/"
                f"p95:{percentile(xs, 95):.2f}/"
                f"max:{max(xs):.2f}ms"
            )
        print("  ".join(parts), file=sys.stderr)
        self._samples.clear()
        self._frames = 0
        self._window_start = now

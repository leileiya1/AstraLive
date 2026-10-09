"""Observability only: fixed windows, no queue or delivery decisions."""
import time


class DropRateMonitor:
    def __init__(self, window_seconds=10.0, threshold=0.10, sustained_windows=3,
                 min_offers=50, cooldown_seconds=60.0, clock=time.monotonic):
        self.window_seconds = window_seconds
        self.threshold = threshold
        self.sustained_windows = sustained_windows
        self.min_offers = min_offers
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self.started = clock()
        self.offered = self.dropped = self.high_windows = 0
        self.last_warning = float('-inf')
        self.rate = 0.0

    def offer(self):
        now = self.clock()
        warning = None
        elapsed = now - self.started
        if elapsed >= self.window_seconds:
            self.rate = self.dropped / self.offered if self.offered else 0.0
            # A gap with no producer traffic cannot count as sustained overload.
            high = elapsed < self.window_seconds * 2 and self.offered >= self.min_offers and self.rate > self.threshold
            self.high_windows = self.high_windows + 1 if high else 0
            if self.high_windows >= self.sustained_windows and now - self.last_warning >= self.cooldown_seconds:
                warning = {"drop_rate": self.rate, "windowSeconds": elapsed,
                           "offered": self.offered, "windowDropped": self.dropped}
                self.last_warning = now
            self.started = now
            self.offered = self.dropped = 0
        self.offered += 1
        return warning

    def drop(self):
        self.dropped += 1

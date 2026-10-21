"""Small timing helpers shared by the long-running MicroPython application."""
import time


def ticks_diff(a, b):
    fn = getattr(time, "ticks_diff", None)
    return fn(a, b) if fn else a - b


def ticks_ms():
    fn = getattr(time, "ticks_ms", None)
    return fn() if fn else int(time.monotonic() * 1000)


class Runtime:
    def __init__(self, clock=time):
        self.clock = clock
        self.last_tick = clock.ticks_ms()
        self.elapsed_ms = 0
        self.max_ms = {}

    def uptime(self, now=None):
        now = self.clock.ticks_ms() if now is None else now
        self.elapsed_ms += max(0, self.clock.ticks_diff(now, self.last_tick))
        self.last_tick = now
        return self.elapsed_ms

    def call(self, name, fn, *args):
        before = self.clock.ticks_ms()
        try:
            return fn(*args)
        finally:
            duration = max(0, self.clock.ticks_diff(self.clock.ticks_ms(), before))
            previous = self.max_ms.get(name, -1)
            if duration > previous:
                self.max_ms[name] = duration
                if duration >= 250:
                    print("SLOW_OP", name, "ms", duration)

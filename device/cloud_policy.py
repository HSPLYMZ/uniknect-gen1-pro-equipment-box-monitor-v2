"""Bounded boot schedule, real TSL values and reboot-safe traffic credits."""
import json
import math
import os


def decode_signal(value):
    """EC200U QENG strength/quality; SINR dB = raw/2 - 23.5.

    EC200U & EG915U AT manual section6.11 p93: SINR -23..40dB.
    Current module QENG/QCSQ codes were cross-checked on hardware.
    """
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None, None
    strength, quality = value
    rsrp = strength if type(strength) is int and -140 <= strength <= -44 else None
    sinr = quality / 2.0 - 23.5 if type(quality) is int and 1 <= quality <= 127 else None
    return rsrp, sinr


def build_values(sample):
    values = {}
    mask = 0
    for key, fid, lo, hi, bit in (("temperature_c", 2, -40, 85, 1),
            ("humidity_pct", 3, 0, 100, 2), ("light_adc_u16", 4, 0, 65535, 4)):
        value = sample.get(key)
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and lo <= value <= hi):
            if fid == 4:
                if int(value) != value:
                    continue
                value = int(value)
            values[fid] = value
            mask |= bit
    values[5] = mask
    return values


def phase(elapsed_ms):
    """[5,7), [10,12), [15,17), [20,22), [25,27) minutes."""
    if elapsed_ms < 300000:
        return "WAIT", max(0, (300000 - elapsed_ms + 999) // 1000)
    if elapsed_ms >= 1800000:
        return "ENDED", 0
    offset = (elapsed_ms - 300000) % 300000
    if offset < 120000:
        return "REPORT", (120000 - offset + 999) // 1000
    return "PAUSE", min((300000 - offset + 999) // 1000,
                         (1800000 - elapsed_ms + 999) // 1000)


class Schedule:
    def __init__(self):
        self.last_slot = None

    def due(self, elapsed_ms):
        if phase(elapsed_ms)[0] != "REPORT":
            return False
        slot = elapsed_ms // 10000
        if slot == self.last_slot:
            return False
        self.last_slot = slot
        return True


class TrafficBudget:
    """Capacity240, refill600/day powered time, conservative cost2/send.

    Any real 24h interval permits <=840 managed units, regardless of RTC or
    reboots. Outage time never refills. Reserve before dispatch; unused
    reserved credit is lost on reset. This is not the platform balance.
    """
    QUANTUM = 144000
    CAPACITY = 240 * QUANTUM
    BLOCK = 16

    def __init__(self, path, now_ms, diff):
        self.path = path
        self.diff = diff
        self.last = now_ms
        self.balance = 0
        self.granted = 0
        self.error = None
        self.saved_balance = 0
        self.checkpoint_at = now_ms
        try:
            if self._exists(path + ".new"):
                raise ValueError("unfinished budget transaction")
            if self._exists(path):
                with open(path) as handle:
                    record = json.load(handle)
                balance = record[1]
                if (len(record) != 3 or record[0] != 1 or
                        type(balance) is not int or not 0 <= balance <= self.CAPACITY or
                        record[2] != self._check(balance)):
                    raise ValueError("invalid budget")
                self.balance = balance
                self.saved_balance = balance
            else:
                self.balance = self.CAPACITY
                self._save()
        except Exception:
            self.balance = 0
            self.error = "BUDGET_STORAGE"

    @staticmethod
    def _exists(path):
        try:
            os.stat(path)
            return True
        except OSError as exc:
            if exc.args and exc.args[0] == 2:
                return False
            raise

    @staticmethod
    def _check(balance):
        return (balance * 31 + 20557) % 2147483647

    def _save(self):
        with open(self.path + ".new", "w") as handle:
            json.dump([1, self.balance, self._check(self.balance)], handle)
            handle.flush()
        if hasattr(os, "sync"):
            os.sync()
        self.saved_balance = self.balance
        getattr(os, "replace", os.rename)(self.path + ".new", self.path)
        if hasattr(os, "sync"):
            os.sync()

    def tick(self, now_ms):
        elapsed = max(0, self.diff(now_ms, self.last))
        self.last = now_ms
        if self.error is None:
            self.balance = min(self.CAPACITY - self.granted * self.QUANTUM,
                               self.balance + elapsed)

    def take(self, now_ms, units=2):
        self.tick(now_ms)
        if self.error is not None or type(units) is not int or units < 1:
            return False
        if self.granted < units:
            reserve = min(self.BLOCK, self.balance // self.QUANTUM)
            if reserve + self.granted < units:
                return False
            self.balance -= reserve * self.QUANTUM
            try:
                self._save()
            except Exception:
                self.error = "BUDGET_STORAGE"
                self.balance = 0
                self.granted = 0
                return False
            self.granted += reserve
        self.granted -= units
        return True

    def remaining(self):
        return (self.balance // self.QUANTUM + self.granted) // 2

    def checkpoint(self, now_ms):
        self.tick(now_ms)
        if self.diff(now_ms, self.checkpoint_at) < 3600000:
            return
        self.checkpoint_at = now_ms
        if self.error is None and self.balance > self.saved_balance:
            try:
                self._save()
            except Exception:
                self.error = "BUDGET_STORAGE"
                self.balance = 0
                self.granted = 0

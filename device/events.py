"""Pure Python edge event detector, compatible with MicroPython."""

import math
from runtime import ticks_diff


def _cosine(a, b):
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    na = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
    nb = math.sqrt(b[0] ** 2 + b[1] ** 2 + b[2] ** 2)
    if na < 1 or nb < 1:
        return None
    return max(-1.0, min(1.0, dot / (na * nb)))


class _Latch:
    def __init__(self, required, cooldown_ms):
        self.required = required
        self.cooldown_ms = cooldown_ms
        self.count = 0
        self.active = False
        self.last_on_ms = None

    def update(self, trigger, clear, now_ms):
        if trigger is None:
            self.count = 0
            return None
        if self.active:
            if clear:
                self.active = False
                self.count = 0
                return "clear"
            return None
        self.count = self.count + 1 if trigger else 0
        if self.count < self.required:
            return None
        if self.last_on_ms is not None and ticks_diff(now_ms, self.last_on_ms) < self.cooldown_ms:
            return None
        self.active = True
        self.last_on_ms = now_ms
        self.count = 0
        return "on"


class EventEngine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.light_sum = 0
        self.accel_sum = [0.0, 0.0, 0.0]
        self.cal_count = 0
        self.light_count = 0
        self.accel_count = 0
        self.light_min = None
        self.light_max = None
        self.ready = False
        self.light_base = None
        self.accel_base = None
        self.latches = {}
        for name in ("temperature", "humidity", "light", "tilt", "combined"):
            self.latches[name] = _Latch(cfg.EVENT_CONSECUTIVE if name != "combined" else 1,
                                         cfg.EVENT_COOLDOWN_MS)
        self.absolute_light = getattr(cfg, "LIGHT_MODE", "delta") == "absolute"
        if self.absolute_light:
            self.latches["light"] = _Latch(1, 0)
        self.last_light_ms = None
        self.last_tilt_ms = None

    def calibrate(self, sample):
        light = sample.get("light_adc_u16")
        accel = sample.get("accel_m_s2")
        if not self.absolute_light and light is not None and self.light_min is not None:
            next_min = min(self.light_min, light)
            next_max = max(self.light_max, light)
            if next_max - next_min > self.cfg.CALIBRATION_LIGHT_SPAN:
                self.light_sum = 0
                self.accel_sum = [0.0, 0.0, 0.0]
                self.cal_count = 0
                self.light_count = 0
                self.accel_count = 0
                self.light_min = None
                self.light_max = None
        if light is not None:
            self.light_sum += light
            self.light_count += 1
            self.light_min = light if self.light_min is None else min(self.light_min, light)
            self.light_max = light if self.light_max is None else max(self.light_max, light)
        if accel is not None and all(math.isfinite(v) for v in accel) and sum(v*v for v in accel) >= 1:
            for i in range(3):
                self.accel_sum[i] += accel[i]
            self.accel_count += 1
        self.cal_count += 1
        enough_light = self.absolute_light or self.light_count >= self.cfg.CALIBRATION_SAMPLES
        if enough_light and self.accel_count >= self.cfg.CALIBRATION_SAMPLES:
            if self.light_count:
                self.light_base = self.light_sum / self.light_count
            if self.accel_count:
                self.accel_base = tuple(x / self.accel_count for x in self.accel_sum)
            self.ready = True
            return True
        return False

    def reset_calibration(self):
        self.__init__(self.cfg)

    def update(self, sample, now_ms):
        events = self.update_light(sample.get("light_adc_u16"), now_ms)
        if not self.ready:
            self.calibrate(sample)
        temp = sample.get("temperature_c")
        hum = sample.get("humidity_pct")
        accel = sample.get("accel_m_s2")
        cos_tilt = _cosine(accel, self.accel_base) if accel is not None and self.accel_base is not None else None
        values = {
            "temperature": (temp, self.cfg.TEMP_HIGH_C, self.cfg.TEMP_CLEAR_C),
            "humidity": (hum, self.cfg.HUMIDITY_HIGH_PCT, self.cfg.HUMIDITY_CLEAR_PCT),
        }
        for name, (value, high, low) in values.items():
            transition = self.latches[name].update(
                None if value is None else value >= high,
                value is not None and value <= low, now_ms)
            if transition:
                events.append({"type": name, "transition": transition, "value": value})
        if cos_tilt is not None:
            on_cos = math.cos(self.cfg.TILT_TRIGGER_DEG * math.pi / 180)
            off_cos = math.cos(self.cfg.TILT_CLEAR_DEG * math.pi / 180)
            transition = self.latches["tilt"].update(cos_tilt <= on_cos,
                                                       cos_tilt >= off_cos, now_ms)
        else:
            transition = self.latches["tilt"].update(None, False, now_ms)
        if transition:
            events.append({"type": "tilt", "transition": transition,
                           "cosine": round(cos_tilt, 4) if cos_tilt is not None else None})
            if transition == "on":
                self.last_tilt_ms = now_ms
        events.extend(self._update_combined(now_ms))
        return events

    def update_light(self, light, now_ms):
        """Exposure is available at boot and every ADC poll, with no cooldown."""
        if self.absolute_light:
            value = light
            high = self.cfg.LIGHT_EXPOSED_TRIGGER
            low = self.cfg.LIGHT_EXPOSED_CLEAR
        else:
            if not self.ready:
                return []
            value = abs(light - self.light_base) if light is not None and self.light_base is not None else None
            high, low = self.cfg.LIGHT_DELTA_TRIGGER, self.cfg.LIGHT_DELTA_CLEAR
        exposed_low = self.absolute_light and getattr(self.cfg, "LIGHT_EXPOSED_LOW", False)
        trigger = None if value is None else (value <= high if exposed_low else value >= high)
        clear = value is not None and (value >= low if exposed_low else value <= low)
        transition = self.latches["light"].update(trigger, clear, now_ms)
        events = []
        if transition:
            events.append({"type": "light", "transition": transition, "value": value})
            if transition == "on":
                self.last_light_ms = now_ms
        events.extend(self._update_combined(now_ms))
        return events

    def _update_combined(self, now_ms):
        events = []
        recent = (self.last_light_ms is not None and self.last_tilt_ms is not None
                  and abs(ticks_diff(self.last_light_ms, self.last_tilt_ms)) <= self.cfg.FUSION_WINDOW_MS
                  and self.latches["light"].active and self.latches["tilt"].active)
        transition = self.latches["combined"].update(recent, not recent, now_ms)
        if transition:
            events.append({"type": "combined", "transition": transition,
                           "evidence": ["light", "tilt"]})
        return events

    def active(self):
        return [name for name in self.latches if self.latches[name].active]

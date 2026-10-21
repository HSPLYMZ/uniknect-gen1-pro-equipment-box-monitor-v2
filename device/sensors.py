"""Board sensors; each reading can fail independently."""

import machine
from ahtx0 import AHT20
from lis2dh12 import LIS2DH12
import math
from runtime import ticks_ms, ticks_diff


class Sensors:
    def __init__(self):
        self.errors = {}
        self.aht = None
        self.lis = None
        self.ldr = None
        try:
            bus = machine.I2C(1, freq=400000)
        except Exception as exc:
            self.errors["i2c_init"] = str(exc)
            bus = None
        if bus is not None:
            for key, cls, attr in (("aht20_init", AHT20, "aht"), ("lis2dh12_init", LIS2DH12, "lis")):
                try:
                    setattr(self, attr, cls(bus))
                except Exception as exc:
                    self.errors[key] = str(exc)
        self.bus = bus
        self.last_retry = ticks_ms()
        try:
            self.ldr = machine.ADC(machine.Pin("C5"))
        except Exception as exc:
            self.errors["ldr_init"] = str(exc)

    def _recover_missing(self):
        if self.aht is not None and self.lis is not None and self.ldr is not None:
            return
        now = ticks_ms()
        if ticks_diff(now, self.last_retry) < 10000:
            return
        self.last_retry = now
        if self.bus is None:
            try:
                self.bus = machine.I2C(1, freq=400000)
            except Exception:
                pass
        if self.bus is not None:
            for cls, attr in ((AHT20, "aht"), (LIS2DH12, "lis")):
                if getattr(self, attr) is None:
                    try:
                        setattr(self, attr, cls(self.bus))
                    except Exception:
                        pass
        if self.ldr is None:
            try:
                self.ldr = machine.ADC(machine.Pin("C5"))
            except Exception:
                pass

    def read_light(self):
        """Read only the ADC; do not wait for the AHT20's conversion."""
        if self.ldr is None:
            return None
        try:
            return self.ldr.read_u16()
        except Exception as exc:
            self.errors["ldr"] = str(exc)
            return None

    def read_acceleration(self):
        """Fast pose-only read. Never starts a temperature conversion or recovery."""
        if self.lis is None:
            return None
        try:
            values = tuple(round(v, 3) for v in self.lis.acceleration)
            if len(values) == 3 and all(math.isfinite(v) and abs(v) <= 160 for v in values):
                return values
        except Exception:
            pass
        return None

    def read(self):
        self._recover_missing()
        data = {"temperature_c": None, "humidity_pct": None,
                "light_adc_u16": None, "accel_m_s2": None}
        errors = {}
        if self.aht is not None:
            try:
                data["temperature_c"] = round(self.aht.temperature, 2)
                if not -40 <= data["temperature_c"] <= 85:
                    data["temperature_c"] = None
                    errors["temperature"] = "out_of_range"
            except Exception as exc:
                errors["temperature"] = str(exc)
            try:
                data["humidity_pct"] = round(self.aht.relative_humidity, 2)
                if not 0 <= data["humidity_pct"] <= 100:
                    data["humidity_pct"] = None
                    errors["humidity"] = "out_of_range"
            except Exception as exc:
                errors["humidity"] = str(exc)
        else:
            errors["aht20"] = "init_failed"
        if self.lis is not None:
            try:
                data["accel_m_s2"] = tuple(round(v, 3) for v in self.lis.acceleration)
                if len(data["accel_m_s2"]) != 3 or any(not math.isfinite(v) for v in data["accel_m_s2"]):
                    data["accel_m_s2"] = None
                    errors["lis2dh12"] = "invalid_vector"
            except Exception as exc:
                errors["lis2dh12"] = str(exc)
        else:
            errors["lis2dh12"] = "init_failed"
        if self.ldr is not None:
            try:
                data["light_adc_u16"] = self.ldr.read_u16()
            except Exception as exc:
                errors["ldr"] = str(exc)
        else:
            errors["ldr"] = "init_failed"
        data["valid"] = len(errors) == 0
        data["errors"] = errors
        self.errors = errors
        return data

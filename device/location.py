"""GNSS first; optional slow LBS fallback. No fabricated coordinates."""

import quectel


class Location:
    def __init__(self, cfg):
        self.cfg = cfg
        self.gnss = None
        self.lbs = None
        self.status = "DISABLED"
        self.last = None
        self.last_ms = None
        self.last_gnss_ms = None
        self.last_lbs_ms = None
        self.error = None
        # Module AT scan works via J401 USB; this MCU firmware exposes no scan API.
        self.wifi_scan = "USB_ONLY"

    def start(self):
        if not self.cfg.ENABLE_GNSS:
            return
        try:
            self.gnss = quectel.GNSS()
            if self.gnss.start():
                self.status = "SEARCHING"
            else:
                self.status = "UNAVAILABLE"
        except Exception as exc:
            self.status = "UNAVAILABLE"
            self.error = str(exc)

    def poll_gnss(self, now_ms, diff):
        if self.gnss is None or self.status == "UNAVAILABLE":
            return
        if self.last_gnss_ms is not None and diff(now_ms, self.last_gnss_ms) < self.cfg.GNSS_POLL_MS:
            return
        self.last_gnss_ms = now_ms
        try:
            raw = self.gnss.get_location()
            if raw and raw.get("latitude") is not None and raw.get("longitude") is not None:
                self.last = {"source": "GNSS", "latitude": raw["latitude"],
                             "longitude": raw["longitude"],
                             "satellites": raw.get("satellites"),
                             "hdop": raw.get("hdop"), "fix_mode": raw.get("fix_mode")}
                self.last_ms = now_ms
                self.status = "FIX"
                self.error = None
            elif self.last is None or self.last.get("source") != "LBS":
                self.status = "NO_FIX"
        except Exception as exc:
            self.status = "ERROR"
            self.error = str(exc)

    def poll_lbs(self, now_ms, diff):
        if not self.cfg.ENABLE_LBS or self.cfg.LBS_POLL_MS <= 0:
            return
        if self.status == "FIX":
            return
        if self.last_lbs_ms is not None and diff(now_ms, self.last_lbs_ms) < self.cfg.LBS_POLL_MS:
            return
        self.last_lbs_ms = now_ms
        try:
            if self.lbs is None:
                self.lbs = quectel.LBS()
            raw = self.lbs.get_location(15000)
            if raw and raw.get("latitude") is not None and raw.get("longitude") is not None:
                self.last = {"source": "LBS", "latitude": raw["latitude"],
                             "longitude": raw["longitude"]}
                self.last_ms = now_ms
                self.status = "LBS"
        except Exception as exc:
            self.error = "LBS: " + str(exc)

    def snapshot(self, now_ms, diff):
        result = {"status": self.status, "source": "NONE", "valid": False,
                  "latitude": None, "longitude": None, "age_s": None,
                  "wifi_scan": self.wifi_scan}
        if self.last is None or self.last_ms is None:
            return result
        age_ms = max(0, diff(now_ms, self.last_ms))
        if age_ms > self.cfg.LOCATION_MAX_AGE_MS:
            return result
        result.update(self.last)
        result["valid"] = True
        result["age_s"] = age_ms // 1000
        return result

    def stop(self):
        for obj, method in ((self.gnss, "stop"), (self.lbs, "deinit")):
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass

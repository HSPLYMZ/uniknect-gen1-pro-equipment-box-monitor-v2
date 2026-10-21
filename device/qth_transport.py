"""Cooperative Qth initialization and bounded TSL; SDK owns MQTT reconnects."""
import time
import json
from cloud_policy import build_values, decode_signal, phase, Schedule, TrafficBudget


class QthTransport:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = "INIT" if getattr(cfg, "ENABLE_QTH", False) else "DISABLED"
        self.error = None
        self.started = False
        self.boot = getattr(cfg, "_CLOUD_BOOT_TICKS", time.ticks_ms())
        self.latest = ({5: 0}, None)
        self.read_request = None
        self.rsrp = None
        self.sinr = None
        self.signal_at = None
        self.attempts = 0
        self.last_result = "--"
        self.remaining = 0
        self.budget_state = None
        self.ended = False
        self.Qth = None
        self.restore = None
        self.step = 0
        self.budget = None
        self.schedule = Schedule()
        self.checked_at = None
        self.signal_due = None
        self.net = None
        self.ping_at = None
        self.pings = 0
        self.ping_errors = 0

    def _elapsed(self, now_ms):
        elapsed = max(0, time.ticks_diff(now_ms, self.boot))
        if elapsed >= 1800000:
            self.ended = True
        return 1800000 if self.ended else elapsed

    def submit(self, sample, now_ms):
        self.latest = (build_values(sample), now_ms)

    def status(self, now_ms):
        mode, seconds = phase(self._elapsed(now_ms))
        if self.state == "DISABLED":
            mode = "DISABLED"
        elif mode == "REPORT" and self.budget_state:
            mode = self.budget_state
        elif mode == "REPORT" and self.state != "ONLINE":
            mode = "OFFLINE"
        signal = self.rsrp if (self.signal_at is not None and
                             time.ticks_diff(now_ms, self.signal_at) <= 90000) else None
        quality = self.sinr if (self.signal_at is not None and
                               time.ticks_diff(now_ms, self.signal_at) <= 90000) else None
        return {"network": self.state, "rsrp_dbm": signal, "sinr_db": quality, "phase": mode,
                "phase_s": seconds, "sent": self.attempts,
                "last_result": self.last_result, "budget": self.remaining,
                "pings": self.pings, "ping_errors": self.ping_errors}

    def _event(self, event, result):
        if event == 2:
            self.state = "ONLINE" if result == 0 else "CONNECTING"
            if result == 0:
                self.ping_at = None
        print("CLOUD_EVENT", event if isinstance(event, int) else -1,
              result if isinstance(result, int) else -1)

    def _read(self, ids, pkg_id):
        if phase(self._elapsed(time.ticks_ms()))[0] == "REPORT":
            self.read_request = (list(ids)[:16], pkg_id)

    def connect_if_due(self, now_ms, diff, sleep):
        if self.state in ("DISABLED", "ERROR") or diff(now_ms, self.boot) < 15000:
            return
        try:
            if not self.started:
                # Native SDK setup must run on this firmware's main thread.
                # One stage per loop lets UI/ADC/BLE run between stages.
                if self.step == 0:
                    import Qth
                    from qth_compat import install
                    self.Qth = Qth
                    self.budget = TrafficBudget("/flash/cloud_budget.json", now_ms, diff)
                    self.remaining = self.budget.remaining()
                    self.budget_state = self.budget.error
                    if Qth.init() is False:
                        raise RuntimeError("SDK_INIT")
                    self.restore = install(Qth)
                else:
                    q = self.Qth
                    steps = ((q.setProductInfo, (self.cfg.QTH_PRODUCT_KEY, self.cfg.QTH_PRODUCT_SECRET)),
                             (q.setDK, (self.cfg.QTH_DEVICE_KEY,)),
                             (q.setServer, (self.cfg.QTH_SERVER,)),
                             (q.setLifetime, (120,)),
                             (q.setVer, ("V2.2.0-cloud-window",)),
                             (q.setEventCb, ({"devEvent": self._event, "readTsl": self._read},)),
                             (q.start, ()))
                    fn, args = steps[self.step - 1]
                    if fn(*args) is False:
                        raise RuntimeError("SDK_CONFIG")
                    if self.step == len(steps):
                        self.started = True
                        self.state = "CONNECTING"
                        from quectel import Network
                        self.net = Network()
                        try:
                            self.net.init()
                        except Exception:
                            pass  # Signal failure must not stop cloud/local UI.
                self.step += 1
                return
            if self.checked_at is None or diff(now_ms, self.checked_at) >= 1000:
                self.checked_at = now_ms
                online = self.Qth.state()
                self.state = "ONLINE" if online is True or online == 1 else "CONNECTING"
            if self.state == "ONLINE" and (self.ping_at is None or diff(now_ms, self.ping_at) >= 60000):
                self.ping_at = now_ms
                try:
                    # Beta20260721 SDK otherwise idles past broker keepalive.
                    # Native MQTT PINGREQ is free protocol traffic, not TSL.
                    client = getattr(self.Qth.qth_dmp, "_mqtt_client", None)
                    if client is None or client.ping() is False:
                        raise RuntimeError("PING")
                    self.pings += 1
                    print("CLOUD_PING", self.pings, "CALLED")
                except Exception:
                    self.ping_errors += 1
                    print("CLOUD_PING_ERROR", self.ping_errors)
            if self.signal_due is None or diff(now_ms, self.signal_due) >= 30000:
                self.signal_due = now_ms
                self._poll_signal()
        except Exception as exc:
            self.error = type(exc).__name__
            self.state = "ERROR"
            print("CLOUD_ERROR", self.error, "stage", self.step)

    def send_one(self, outbox, now_ms):
        if self.budget is None:
            return False
        self.budget.checkpoint(now_ms)
        self.remaining = self.budget.remaining()
        self.budget_state = self.budget.error or ("QUOTA_HOLD" if self.remaining < 1 else None)
        elapsed = self._elapsed(now_ms)
        if phase(elapsed)[0] != "REPORT":
            self.read_request = None
        if not self.schedule.due(elapsed) or self.state != "ONLINE":
            return False
        values, sampled_at = self.latest
        if sampled_at is None or time.ticks_diff(now_ms, sampled_at) > 5000:
            values = {5: 0}
        if len(json.dumps(values).encode()) > 128:
            self.error = "TSL_SIZE"
            return False
        if not self.budget.take(now_ms, 2):
            self.budget_state = self.budget.error or "QUOTA_HOLD"
            return False
        self.remaining = self.budget.remaining()
        self.attempts += 1
        request = self.read_request
        self.read_request = None
        answer = {}
        if request is not None:
            for fid in request[0]:
                try:
                    fid = int(fid)
                except (ValueError, TypeError):
                    continue
                if fid in values:
                    answer[fid] = values[fid]
        try:
            result = (self.Qth.ackTsl(1, answer, request[1]) if answer else
                      self.Qth.sendTsl(1, values))
            self.last_result = "FAIL" if result is False else "CALLED"
        except Exception:
            self.last_result = "FAIL"
        print("CLOUD_SEND", self.attempts, "slot", elapsed // 10000,
              "result", self.last_result, "remaining", self.remaining)
        # None is unconfirmed. No retry, no transparent data or offline replay.
        return False

    def _poll_signal(self):
        try:
            value = self.net.get_signal()
            # Firmware returns (strength, quality); official ql_net LTE parser
            # selects QENG RSRP and raw SINR. Verified against module QENG.
            self.rsrp, self.sinr = decode_signal(value)
            self.signal_at = time.ticks_ms()
        except Exception:
            self.rsrp = None
            self.sinr = None

    def close(self):
        if self.Qth is not None:
            try:
                self.Qth.stop()
            except Exception:
                pass
            if self.restore is not None:
                self.Qth.qth_file.write_file = self.restore
        self.started = False

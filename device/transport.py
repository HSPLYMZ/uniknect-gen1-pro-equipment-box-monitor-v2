"""Cellular attach and MQTT QoS 0 with bounded retry intervals."""

import json


class _MqttTransport:
    def __init__(self, cfg):
        self.cfg = cfg
        self.net = None
        self.client = None
        self.state = "DISABLED" if not cfg.ENABLE_MQTT or cfg.BROKER == "CHANGE_ME" else "INIT"
        self.last_attempt_ms = None
        self.init_ms = None
        self.retry_ms = cfg.MQTT_RETRY_MS
        self.error = None

    def _disconnect(self):
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None

    def connect_if_due(self, now_ms, diff, sleep):
        if self.state in ("DISABLED", "ONLINE"):
            return
        if self.last_attempt_ms is not None and diff(now_ms, self.last_attempt_ms) < self.retry_ms:
            return
        if self.net is None:
            try:
                from quectel import Network
                self.net = Network()
                self.net.init()
                self.init_ms = now_ms
                self.state = "SETTLING"
                return
            except Exception as exc:
                self.net = None
                self.error = str(exc)
                self.state = "BACKOFF"
                self.last_attempt_ms = now_ms
                self.retry_ms = min(self.cfg.MQTT_RETRY_MAX_MS, self.retry_ms * 2)
                return
        if self.init_ms is not None and diff(now_ms, self.init_ms) < 5000:
            return  # Let sampling and LCD continue while the SIM settles.
        self.init_ms = None
        self.last_attempt_ms = now_ms
        self.state = "ATTACHING"
        try:
            from umqtt.simple import MQTTClient
            if not self.net.query_usim():
                raise RuntimeError("SIM unavailable")
            self.net.attach()
            self.client = MQTTClient(client_id=self.cfg.CLIENT_ID, server=self.cfg.BROKER,
                                     port=self.cfg.PORT, user=self.cfg.USERNAME or None,
                                     password=self.cfg.PASSWORD or None, keepalive=60)
            self.client.connect()
            self.state = "ONLINE"
            self.error = None
            self.retry_ms = self.cfg.MQTT_RETRY_MS
        except Exception as exc:
            self._disconnect()
            self.error = str(exc)
            self.state = "BACKOFF"
            self.retry_ms = min(self.cfg.MQTT_RETRY_MAX_MS, self.retry_ms * 2)

    def send_one(self, outbox, now_ms):
        if self.state != "ONLINE" or len(outbox) == 0:
            return False
        topic, payload, _priority = outbox.peek()
        try:
            self.client.publish(topic.encode() if isinstance(topic, str) else topic,
                                json.dumps(payload).encode())
            outbox.sent()
            return True
        except Exception as exc:
            payload["replayed"] = True
            self._disconnect()
            self.error = str(exc)
            self.state = "BACKOFF"
            self.last_attempt_ms = now_ms
            self.retry_ms = min(self.cfg.MQTT_RETRY_MAX_MS, self.retry_ms * 2)
            return False

    def close(self):
        self._disconnect()
        if self.net is not None:
            try:
                self.net.deinit()
            except Exception:
                pass


class Transport:
    """Select the existing generic MQTT client or Quectel's managed Qth cloud."""
    def __init__(self, cfg):
        if getattr(cfg, "TRANSPORT_MODE", "mqtt") == "qth":
            try:
                from qth_transport import QthTransport
                self.impl = QthTransport(cfg)
            except Exception as exc:
                self.impl = _MqttTransport(cfg)
                self.impl.state = "DISABLED"
                self.impl.error = "QTH_INIT:" + type(exc).__name__
                print("CLOUD_ERROR", self.impl.error)
        else:
            self.impl = _MqttTransport(cfg)

    @property
    def state(self):
        return self.impl.state

    @property
    def error(self):
        return self.impl.error

    def connect_if_due(self, now_ms, diff, sleep):
        return self.impl.connect_if_due(now_ms, diff, sleep)

    def submit(self, sample, now_ms):
        if hasattr(self.impl, "submit"):
            self.impl.submit(sample, now_ms)

    def status(self, now_ms):
        if hasattr(self.impl, "status"):
            return self.impl.status(now_ms)
        return {"network": self.state, "phase": "DISABLED", "rsrp_dbm": None, "sinr_db": None,
                "phase_s": 0, "sent": 0, "last_result": "--", "budget": 0}

    def send_one(self, outbox, now_ms):
        return self.impl.send_one(outbox, now_ms)

    def close(self):
        return self.impl.close()

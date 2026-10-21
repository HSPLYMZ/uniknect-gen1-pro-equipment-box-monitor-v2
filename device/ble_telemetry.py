"""Read-only V2 telemetry over the board's documented Quectel BLE API."""

SERVICE_UUID = 0xFFF0
TELEMETRY_UUID = 0xFFF1
POSE_UUID = 0xFFF2
CCCD_UUID = 0x2902


def encode_frame(sample, active, calibrated, sequence):
    # 20 ASCII bytes, including version. Valid bits distinguish missing from 0.
    flags = 0
    values = []
    for key, scale, lower, upper, bit in (
            ("temperature_c", 100, -4000, 8500, 1),
            ("humidity_pct", 100, 0, 10000, 2),
            ("light_adc_u16", 1, 0, 65535, 4)):
        value = sample.get(key)
        try:
            encoded = int(round(value * scale))
            if encoded < lower or encoded > upper:
                raise ValueError("range")
            flags |= bit
        except (TypeError, ValueError, OverflowError):
            encoded = 0
        values.append(encoded & 65535)
    for name, bit in (("light", 8), ("tilt", 16), ("temperature", 32), ("humidity", 64)):
        if name in active:
            flags |= bit
    if calibrated:
        flags |= 128
    return "01%04X%04X%04X%04X%02X" % (
        sequence & 65535, values[0], values[1], values[2], flags)


def encode_pose(values, sequence):
    # 02 + sample sequence + signed XYZ centi-m/s2 + validity, exactly 20 ASCII bytes.
    encoded = [0, 0, 0]
    valid = 0
    try:
        if values is not None and len(values) == 3:
            encoded = [int(round(v * 100)) for v in values]
            if any(abs(v) > 16000 for v in encoded):
                raise ValueError("range")
            valid = 1
    except (TypeError, ValueError, OverflowError):
        encoded = [0, 0, 0]
    return "02%04X%04X%04X%04X%02X" % (
        sequence & 65535, encoded[0] & 65535, encoded[1] & 65535,
        encoded[2] & 65535, valid)


def _notification_enabled(value):
    if isinstance(value, int):
        return bool(value & 1)
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value)
        if len(value) == 2:
            return bool(value[0] & 1)
        try:
            value = value.decode()
        except UnicodeError:
            return False
    if isinstance(value, str):
        value = value.replace(" ", "").upper()
        return value == "0100" or value == "0300"
    return False


class BleTelemetry:
    def __init__(self, cfg):
        self.enabled = getattr(cfg, "ENABLE_BLE", False)
        self.name = getattr(cfg, "BLE_NAME", "UniKnect_V2")
        self.interval_ms = max(200, getattr(cfg, "BLE_NOTIFY_MS", 1000))
        self.ble = None
        self.api = None
        self.started = False
        self.connected = False
        self.subscribed = False
        self.pose_subscribed = False
        self.pose_interval_ms = max(200, getattr(cfg, "BLE_POSE_MS", 200))
        self._last_pose_send = None
        self._last_pose_seq = None
        self.pose_sent = 0
        self.pose_errors = 0
        self.max_pose_ms = 0
        self.state = "DISABLED" if not self.enabled else "INIT"
        self._reported = None
        self._last_send = None
        self.connections = 0
        self.disconnections = 0
        self._reported_link = None
        self.sequence = 0
        self.sent = 0
        self.errors = 0
        self.max_notify_ms = 0
        self.mtu = 23

    def _event(self, event):
        # No modem calls or sensor I/O from a callback.
        kind = event.get("event")
        if kind == self.api.EVT_CONNECTED:
            self.connections += 1
            self.connected = True
            self.subscribed = False
            self.pose_subscribed = False
            self._last_pose_send = None
            self._last_pose_seq = None
            self._last_send = None
            self.state = "CONNECTED"
        elif kind == self.api.EVT_DISCONNECTED:
            self.disconnections += 1
            self.connected = False
            self.subscribed = False
            self.pose_subscribed = False
            # Like the official example, let the module resume advertising.
            # advertise() also commits GATT and fails if called twice on this firmware.
            self.state = "ADVERTISING"
        elif kind == self.api.EVT_MTU:
            self.mtu = event.get("mtu", 23)
        elif kind == self.api.EVT_DESCDATA and event.get("desc_uuid") == CCCD_UUID:
            enabled = self.connected and _notification_enabled(event.get("value"))
            if event.get("uuid") == TELEMETRY_UUID:
                self.subscribed = enabled
            elif event.get("uuid") == POSE_UUID:
                self.pose_subscribed = enabled
            self.state = "STREAMING" if self.subscribed or self.pose_subscribed else "CONNECTED"

    def start(self):
        if not self.enabled:
            return
        try:
            from quectel import BLE
            self.api = BLE
            self.ble = BLE()
            if not self.ble.init(self._event):
                raise RuntimeError("init")
            self.ble.set_dataformat(BLE.DATAFMT_STRING)
            self.ble.start(self.name)
            self.started = True
            self.ble.add_service(0, SERVICE_UUID, True)
            self.ble.add_character(0, 0, BLE.PROP_READ | BLE.PROP_NOTIFY, TELEMETRY_UUID)
            initial = encode_frame({}, [], False, 0)
            self.ble.set_character_value(0, 0, BLE.PERM_READ, TELEMETRY_UUID, 20,
                                         "".join("%02X" % b for b in initial.encode()))
            self.ble.add_descriptor(0, 0, BLE.PERM_READ | BLE.PERM_WRITE, CCCD_UUID, "0000")
            self.ble.add_character(0, 1, BLE.PROP_READ | BLE.PROP_NOTIFY, POSE_UUID)
            initial_pose = encode_pose(None, 0)
            self.ble.set_character_value(0, 1, BLE.PERM_READ, POSE_UUID, 20,
                                         "".join("%02X" % b for b in initial_pose.encode()))
            self.ble.add_descriptor(0, 1, BLE.PERM_READ | BLE.PERM_WRITE, CCCD_UUID, "0000")
            self.ble.advertise()
            self.state = "ADVERTISING"
            print("BLE_READY", self.name, "service", "FFF0", "notify", "FFF1", "frame_bytes", 20)
            print("BLE_POSE_READY", "FFF2", "frame_bytes", 20)
        except Exception as exc:
            self.errors += 1
            print("BLE_ERROR", "start", type(exc).__name__)
            self.close()
            self.state = "ERROR"

    def poll(self, sample, active, calibrated, now_ms, clock):
        if self.ble is None:
            return
        link = (self.connections, self.disconnections, self.subscribed, self.pose_subscribed)
        if link != self._reported_link:
            print("BLE_LINK", "connections", self.connections,
                  "disconnections", self.disconnections, "subscribed", self.subscribed,
                  "pose_subscribed", self.pose_subscribed)
            self._reported_link = link
        if self.state != self._reported:
            print("BLE_STATE", self.state)
            self._reported = self.state
        if not self.connected or not self.subscribed:
            return
        if self._last_send is not None and clock.ticks_diff(now_ms, self._last_send) < self.interval_ms:
            return
        self._last_send = now_ms
        frame = encode_frame(sample, active, calibrated, self.sequence)
        before = clock.ticks_ms()
        try:
            self.ble.notify(TELEMETRY_UUID, len(frame), frame)
            self.sent += 1
            self.sequence = (self.sequence + 1) & 65535
            if self.sent == 1 or self.sent % 10 == 0:
                print("BLE_SENT", self.sent, "frame", frame)
        except Exception as exc:
            self.errors += 1
            print("BLE_ERROR", "notify", type(exc).__name__)
        finally:
            self.max_notify_ms = max(self.max_notify_ms, clock.ticks_diff(clock.ticks_ms(), before))

    def poll_pose(self, values, sequence, measured_ms, now_ms, clock):
        if self.ble is None or not self.connected or not self.pose_subscribed or measured_ms is None:
            return
        if self._last_pose_seq == sequence:
            return
        if self._last_pose_send is not None and clock.ticks_diff(now_ms, self._last_pose_send) < self.pose_interval_ms:
            return
        self._last_pose_send = now_ms
        self._last_pose_seq = sequence
        age = clock.ticks_diff(now_ms, measured_ms)
        frame = encode_pose(values if 0 <= age <= 600 else None, sequence)
        before = clock.ticks_ms()
        try:
            self.ble.notify(POSE_UUID, len(frame), frame)
            self.pose_sent += 1
        except Exception as exc:
            self.pose_errors += 1
            print("BLE_ERROR", "pose_notify", type(exc).__name__)
        finally:
            self.max_pose_ms = max(self.max_pose_ms, clock.ticks_diff(clock.ticks_ms(), before))

    def close(self):
        self.connected = False
        self.subscribed = False
        self.pose_subscribed = False
        if self.ble is not None:
            if self.started:
                try:
                    self.ble.stop()
                except Exception:
                    pass
            try:
                self.ble.deinit()
            except Exception:
                pass
        self.ble = None
        self.started = False
        self.state = "STOPPED" if self.enabled else "DISABLED"

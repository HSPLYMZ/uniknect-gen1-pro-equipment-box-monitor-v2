"""Protocol, subscription and lifecycle regressions without real hardware."""
import contextlib
import io
import types
import unittest
from unittest.mock import patch
from support import DEVICE_DIR
from ble_telemetry import BleTelemetry, encode_frame, encode_pose, _notification_enabled


class FakeBle:
    EVT_CONNECTED, EVT_DISCONNECTED, EVT_MTU, EVT_DESCDATA = range(4)
    DATAFMT_STRING = 2
    PROP_READ, PROP_NOTIFY, PERM_READ, PERM_WRITE = 2, 16, 1, 2
    def __init__(self):
        self.calls = []
        self.callback = None
        self.fail_send = False
    def init(self, cb): self.callback = cb; return True
    def set_dataformat(self, *args): pass
    def start(self, *args): pass
    def add_service(self, *args): pass
    def add_character(self, *args): pass
    def set_character_value(self, *args): self.calls.append(("value", args))
    def add_descriptor(self, *args): pass
    def advertise(self):
        if any(c[0] == "advertise" for c in self.calls):
            raise OSError("BLE service complete failed: -5")
        self.calls.append(("advertise",))
    def notify(self, *args):
        if self.fail_send: raise OSError("fixture")
        self.calls.append(("notify", args))
    def stop(self): self.calls.append(("stop",))
    def deinit(self): self.calls.append(("deinit",))


class BleTests(unittest.TestCase):
    def setUp(self):
        self.clock = types.SimpleNamespace(now=0)
        self.clock.ticks_ms = lambda: self.clock.now
        self.clock.ticks_diff = lambda a, b: a - b
        self.cfg = types.SimpleNamespace(ENABLE_BLE=True, BLE_NOTIFY_MS=1000, BLE_NAME="UniKnect_V2")
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
    def tearDown(self): self.output.__exit__(None, None, None)
    def begin(self):
        channel = BleTelemetry(self.cfg)
        with patch.dict("sys.modules", {"quectel": types.SimpleNamespace(BLE=FakeBle)}):
            channel.start()
        return channel
    def poll(self, channel, now):
        self.clock.now = now
        channel.poll({"temperature_c": 25.5, "humidity_pct": 50, "light_adc_u16": 13000},
                     ["light"], True, now, self.clock)
    def test_wire_format_negative_temperature_zero_and_wrap(self):
        frame = encode_frame({"temperature_c": -12.34, "humidity_pct": 0, "light_adc_u16": 65535},
                             ["light", "tilt"], True, 65536)
        self.assertEqual(frame, "010000FB2E0000FFFF9F")
        self.assertEqual(len(frame.encode()), 20)
    def test_invalid_data_clears_bits_and_cannot_be_confused_with_zero(self):
        self.assertEqual(encode_frame({}, [], False, 1), "01000100000000000000")
        frame = encode_frame({"temperature_c": float("nan"), "humidity_pct": 101,
                              "light_adc_u16": -1}, [], False, 0)
        self.assertEqual(frame[-2:], "00")
    def test_subscription_representations_and_indicate_only(self):
        for value in ("0100", "01 00", b"\x01\x00", b"0100", 1, "0300"):
            self.assertTrue(_notification_enabled(value), repr(value))
        for value in ("0200", "0000", b"\x00\x00", None, "junk"):
            self.assertFalse(_notification_enabled(value), repr(value))
    def test_only_subscribed_connection_sends_and_is_rate_limited(self):
        channel = self.begin()
        driver = channel.ble
        self.poll(channel, 0)
        driver.callback({"event": 0})
        self.poll(channel, 0)
        self.assertEqual(channel.sent, 0)
        driver.callback({"event": 3, "uuid": 0xfff1, "desc_uuid": 0x2902, "value": "0100"})
        self.poll(channel, 0)
        self.poll(channel, 999)
        self.poll(channel, 1000)
        self.assertEqual(channel.sent, 2)
        sent = [c[1] for c in driver.calls if c[0] == "notify"]
        self.assertTrue(all(c[0] == 0xfff1 and c[1] == 20 for c in sent))
        driver.callback({"event": 1})
        self.poll(channel, 2000)
        self.assertFalse(channel.subscribed)
        self.assertEqual(channel.sent, 2)
        self.assertEqual([c[0] for c in driver.calls].count("advertise"), 1)
        self.assertEqual(channel.state, "ADVERTISING")
        self.assertEqual(channel.errors, 0)
        self.assertEqual(channel.disconnections, 1)
        driver.callback({"event": 0})
        self.poll(channel, 3000)
        self.assertEqual(channel.sent, 2)  # Reconnect needs a fresh CCCD subscription.
        channel.close()
        self.assertEqual(driver.calls[-2:], [("stop",), ("deinit",)])
    def test_notify_failure_is_contained_and_does_not_spin(self):
        channel = self.begin()
        channel._event({"event": 0})
        channel._event({"event": 3, "uuid": 0xfff1, "desc_uuid": 0x2902, "value": "0100"})
        channel.ble.fail_send = True
        self.poll(channel, 0)
        self.poll(channel, 20)
        self.assertEqual(channel.errors, 1)
        self.assertEqual(channel.sent, 0)
    def test_pose_encoding_signed_values_and_invalid_vectors(self):
        self.assertEqual(encode_pose((-9.81, 0, 9.81), 65536), '020000FC2B000003D501')
        for values in (None, (0, 1), (float('nan'), 0, 1), (161, 0, 0)):
            self.assertEqual(encode_pose(values, 7), '02000700000000000000')

    def test_pose_subscription_independent_and_requires_fresh_sample_after_reconnect(self):
        channel = self.begin()
        channel._event({'event': 0})
        channel._event({'event': 3, 'uuid': 0xfff2, 'desc_uuid': 0x2902, 'value': '0100'})
        self.assertFalse(channel.subscribed)
        channel.poll_pose((0, 0, 9.81), 1, 0, 0, self.clock)
        channel.poll_pose((0, 0, 9.81), 1, 0, 300, self.clock)
        self.assertEqual(channel.pose_sent, 1)
        channel.poll_pose((0, 0, 9.81), 2, 0, 700, self.clock)
        sent = [c[1] for c in channel.ble.calls if c[0] == 'notify']
        self.assertEqual(sent[-1][0], 0xfff2)
        self.assertEqual(sent[-1][2][-2:], '00')
        channel._event({'event': 1})
        self.assertFalse(channel.pose_subscribed)
        channel._event({'event': 0})
        channel.poll_pose((0, 0, 9.81), 3, 900, 900, self.clock)
        self.assertEqual(channel.pose_sent, 2)
        channel._event({'event': 3, 'uuid': 0xfff1, 'desc_uuid': 0x2902, 'value': '0100'})
        self.poll(channel, 1000)
        self.assertEqual(channel.sent, 1)

    def test_pose_failure_keeps_environment_channel_usable(self):
        channel = self.begin()
        channel._event({'event': 0})
        for uuid in (0xfff1,0xfff2):
            channel._event({'event':3,'uuid':uuid,'desc_uuid':0x2902,'value':'0100'})
        channel.ble.fail_send = True
        channel.poll_pose((0,0,9.81),1,0,0,self.clock)
        channel.ble.fail_send = False
        self.poll(channel, 0)
        self.assertEqual(channel.pose_errors, 1)
        self.assertEqual(channel.sent, 1)

    def test_disabled_path_does_not_initialize_modem(self):
        self.cfg.ENABLE_BLE = False
        channel = self.begin()
        self.poll(channel, 0)
        self.assertIsNone(channel.ble)
        self.assertEqual(channel.state, "DISABLED")


if __name__ == "__main__": unittest.main()

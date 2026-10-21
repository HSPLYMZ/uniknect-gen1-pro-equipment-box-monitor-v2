"""PC regressions for ADC input, LCD recovery and changing live samples."""

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from support import DEVICE_DIR
import config_template


def load(name, filename, dependencies):
    spec = importlib.util.spec_from_file_location(name, DEVICE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, dependencies):
        spec.loader.exec_module(module)
    return module


class UiTests(unittest.TestCase):
    def test_logo_resource_matches_official_pixels(self):
        import hashlib
        pixels = (DEVICE_DIR / "assets" / "logo_160x20.bin").read_bytes()
        self.assertEqual(hashlib.sha256(pixels).hexdigest(),
                         "761f7240a05b4f542a83cb9de2d7f5d8601fa5d432f57797a4e79cb50fe0a5c5")

    def setUp(self):
        self.adc = types.SimpleNamespace(value=65000)
        self.adc.read_u16 = lambda: self.adc.value
        machine = types.SimpleNamespace(Pin=lambda pin: pin, ADC=lambda pin: self.adc)
        self.ui = load("ui_test_display", "display.py", {"machine": machine})
        self.button = self.ui.Button(config_template)

    def poll(self, at, value):
        self.adc.value = value
        return self.button.poll(at, lambda now, then: now - then)

    def test_tap_and_release_bounce(self):
        self.assertIsNone(self.poll(0, 12000))
        self.assertIsNone(self.poll(100, 65000))
        self.assertIsNone(self.poll(120, 12000))
        self.assertIsNone(self.poll(150, 65000))
        self.assertEqual(self.poll(200, 65000), "next")
        self.assertIsNone(self.poll(250, 65000))

    def test_hold_emits_once_and_no_extra_on_release(self):
        self.poll(0, 12000)
        self.assertEqual(self.poll(1000, 12000), "next")
        self.assertIsNone(self.poll(2000, 12000))
        self.poll(2050, 65000)
        self.assertIsNone(self.poll(2100, 65000))

    def test_noise_and_very_short_pulse_do_not_switch(self):
        for at in range(0, 1000, 50):
            self.assertIsNone(self.poll(at, 64500 + at % 500))
        self.poll(1000, 12000)
        self.poll(1020, 65000)
        self.assertIsNone(self.poll(1070, 65000))

    def test_held_at_startup_is_not_idle_baseline(self):
        self.adc.value = 12000
        self.button = self.ui.Button(config_template)
        self.poll(0, 12000)
        self.assertEqual(self.poll(1000, 12000), "next")

    def test_adc_failure_does_not_disable_display(self):
        display = self.ui.Display.__new__(self.ui.Display)
        display.page = 2
        display.button = self.button
        display.button_error = None
        with patch.object(self.adc, "read_u16", side_effect=OSError("ADC busy")):
            self.assertIsNone(display.poll_button(0, lambda a, b: a - b))
        self.assertEqual(display.button_error, "ADC busy")
        self.adc.value = 65000
        display.poll_button(50, lambda a, b: a - b)
        self.assertIsNone(display.button_error)

    def test_live_frame_changes_with_samples_and_uptime(self):
        lcd = types.SimpleNamespace(WIDTH=160, HEIGHT=128, BLACK=0, RED=1, WHITE=2, CYAN=3)
        lines = []
        lcd.fill_screen = lambda color: None
        lcd.fill_rectangle = lambda *args: None
        lcd.flush = lambda: None
        lcd.show_string = lambda x, y, text, *args: lines.append(text)
        display = self.ui.Display.__new__(self.ui.Display)
        display.lcd = lcd
        display.page = 2
        display.render({"light_adc_u16": 14000}, {}, [], "DISABLED", 0, 0, 1, 0)
        first = list(lines)
        lines.clear()
        display.render({"light_adc_u16": 30000}, {}, [], "DISABLED", 0, 0, 2, 0)
        self.assertIn("Light:14000", first)
        self.assertEqual(lines, ["LIVE 00:00:02", "Light:30000"])

    def make_lcd(self, bulk=False):
        calls = []
        lcd = types.SimpleNamespace(WIDTH=160, HEIGHT=128, BLACK=0, RED=0xf800, WHITE=0xffff, CYAN=0x7fff)
        lcd.fill_screen = lambda color: calls.append(("clear", color))
        lcd.fill_rectangle = lambda *args: calls.append(("rect",) + args)
        lcd.flush = lambda: calls.append(("flush",))
        lcd.show_string = lambda *args: calls.append(("text",) + args)
        lcd.show_image = lambda *args: calls.append(("image",))
        lcd.draw_point = lambda *args: calls.append(("pixel",) + args)
        if bulk:
            lcd.RAMWR = 0x2c
            lcd.set_address_window = lambda *args: calls.append(("window",) + args)
            lcd.write_command = lambda cmd: calls.append(("command", cmd))
            lcd.write_data = lambda data: calls.append(("data", bytes(data)))
        display = self.ui.Display.__new__(self.ui.Display)
        display.lcd = lcd
        display.page = 2
        return display, calls

    def render(self, display, light=14000, uptime=1, active=()):
        return display.render({"light_adc_u16": light}, {}, active, "DISABLED", 0, 0, uptime, 0)

    def test_static_pages_skip_io_and_repaint_when_reentered(self):
        display, calls = self.make_lcd()
        for page in (0, 1, 0):
            display.page = page
            self.assertTrue(self.render(display))
            calls.clear()
            self.assertFalse(self.render(display, uptime=2))
            self.assertEqual(calls, [])

    def test_unchanged_live_screen_does_no_io(self):
        display, calls = self.make_lcd()
        self.render(display)
        calls.clear()
        self.assertFalse(self.render(display))
        self.assertEqual(calls, [])

    def test_changed_row_is_erased_before_text_and_shorter_value_has_no_tail(self):
        display, calls = self.make_lcd()
        self.render(display)
        calls.clear()
        self.render(display, light=14001)
        self.assertEqual([call for call in calls if call[0] == "text"],
                         [("text", 0, 38, "Light:14001", 0xffff, 0, 12)])
        self.assertEqual(calls[0], ("rect", 0, 38, 160, 16, 0))
        self.assertFalse(any(call[0] == "clear" for call in calls))
        calls.clear()
        self.render(display, light=None)
        self.assertIn(("rect", 0, 38, 160, 16, 0), calls)
        self.assertIn(("text", 0, 38, "Light:--", 0xffff, 0, 12), calls)

    def test_alarm_background_change_repaints_every_line(self):
        display, calls = self.make_lcd()
        self.render(display)
        for active, color in ((["light"], 0xf800), ([], 0)):
            calls.clear()
            self.render(display, active=active)
            self.assertIn(("clear", color), calls)
            self.assertEqual(len([call for call in calls if call[0] == "text"]), 7)

    def test_all_pages_follow_light_even_while_other_alarms_remain(self):
        for page in (0, 1, 2):
            display, calls = self.make_lcd()
            display.page = page
            self.render(display, active=["temperature"])
            for active, color in ((["light", "temperature"], 0xf800), (["temperature"], 0)):
                calls.clear()
                self.assertTrue(self.render(display, active=active))
                self.assertIn(("clear", color), calls)

    def test_failed_flush_invalidates_cache_for_complete_repair(self):
        display, calls = self.make_lcd()
        self.render(display)
        with patch.object(display.lcd, "flush", side_effect=OSError("SPI busy")):
            with self.assertRaises(OSError):
                self.render(display, light=14001)
        calls.clear()
        self.assertTrue(self.render(display, light=14001))
        self.assertIn(("clear", 0), calls)
        self.assertEqual(len([call for call in calls if call[0] == "text"]), 7)

    def test_bulk_strip_geometry_and_rgb565_colors(self):
        display, calls = self.make_lcd(bulk=True)
        display._fill(0, 0, 160, 128, 0xf800)
        self.assertEqual(calls[0], ("window", 0, 0, 159, 127))
        self.assertEqual(calls[1], ("command", 0x2c))
        data = b"".join(call[1] for call in calls if call[0] == "data")
        self.assertEqual(data, b"\xf8\x00" * (160 * 128))
        self.assertEqual(len(display._clear_strip), 3840)
        previous = display._clear_strip
        calls.clear()
        display._fill(0, 38, 160, 12, 0xf800)
        self.assertIs(display._clear_strip, previous)
        self.assertEqual(calls[0], ("window", 0, 38, 159, 49))
        self.assertEqual(calls[1], ("command", 0x2c))

    def test_bulk_author_title_enters_pixel_write_mode(self):
        display, calls = self.make_lcd(bulk=True)
        display.page = 1
        self.render(display)
        index = calls.index(("window", 64, 12, 95, 27))
        self.assertEqual(calls[index + 1], ("command", 0x2c))
        kind, pixels = calls[index + 2]
        self.assertEqual(kind, "data")
        self.assertEqual(len(pixels), 1024)
        self.assertTrue(any(pixels))

    def test_author_page_preserves_addresses_and_fits_screen(self):
        calls = []
        points = []
        lcd = types.SimpleNamespace(WIDTH=160, HEIGHT=128, BLACK=0, WHITE=2, CYAN=3)
        lcd.fill_screen = lambda color: None
        lcd.flush = lambda: None
        lcd.show_string = lambda *args: calls.append(args)
        lcd.draw_point = lambda *args: points.append(args)
        display = self.ui.Display.__new__(self.ui.Display)
        display.lcd = lcd
        display.page = 1
        display.render({}, {}, [], "DISABLED", 0, 0, 0, 0)
        self.assertEqual("".join(call[2] for call in calls[:2]), "huangshengping2025@163.com")
        self.assertEqual("".join(call[2] for call in calls[2:]), "https://github.com/HSPLYMZ")
        last_bottom = 28  # Chinese title ends here.
        for x, y, text, fg, bg, size in calls:
            self.assertTrue(text.isascii())
            self.assertEqual(size, 12)
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x + len(text) * 6, lcd.WIDTH)
            self.assertGreaterEqual(y, last_bottom)
            self.assertLessEqual(y + size, lcd.HEIGHT)
            last_bottom = y + size
        self.assertTrue(points)
        self.assertTrue(all(0 <= x < 160 and 0 <= y < 128 for x, y, color in points))

    def test_main_refresh_recovers_and_page_change_is_immediate(self):
        self.run_main_fixture(False)

    def test_light_screen_precedes_slow_audio_and_sd(self):
        self.run_main_fixture(True)

    def run_main_fixture(self, slow_io):
        clock = types.SimpleNamespace(now=0)
        clock.ticks_ms = lambda: clock.now
        clock.ticks_diff = lambda a, b: a - b
        clock.sleep = lambda seconds: None

        def sleep_ms(ms):
            clock.now += ms
            if clock.now >= 2200:
                raise KeyboardInterrupt

        clock.sleep_ms = sleep_ms
        cfg = types.SimpleNamespace(**{key: value for key, value in vars(config_template).items()
                                     if key.isupper()})
        cfg.ENABLE_BLE = False
        rendered = []
        collections = []
        operations = []

        class Screen:
            def __init__(self, cfg):
                self.page = 2
                self.button_error = None

            def poll_button(self, now, diff):
                return "next" if now == 200 else None

            def render(self, sample, location, active, network, queue, dropped, uptime, *args):
                if clock.now == 0 and not slow_io:
                    raise OSError("SPI busy")
                operations.append(("screen", bool(active)))
                rendered.append((clock.now, sample["light_adc_u16"], uptime))
                return True

        class Sensor:
            def read_light(self):
                return (13795 if clock.now >= 40 else 38000) if slow_io else clock.now
            def read(self):
                return {"light_adc_u16": self.read_light(), "valid": True}

        class Engine:
            ready = True
            def __init__(self, cfg): pass
            def update(self, sample, now): return []
            def update_light(self, value, now): return []
            def active(self): return []

        class Position:
            def __init__(self, cfg): pass
            def start(self): pass
            def stop(self): pass
            def snapshot(self, *args): return {}
            def poll_gnss(self, *args): pass

        class Network:
            state = "DISABLED"
            def __init__(self, cfg): pass
            def connect_if_due(self, *args): pass
            def send_one(self, *args): return False
            def submit(self, *args): pass
            def status(self, *args): return {"network":"DISABLED"}
            def close(self): pass

        class Storage:
            state = "READY"
            recording = False
            def __init__(self, *args): pass
            def append(self, *args):
                if slow_io:
                    operations.append(("sd", None))
                    clock.now += 300
            def sync(self, active):
                if slow_io:
                    operations.append(("audio", bool(active)))
                    clock.now += 150
            def close(self): pass

        from queue_store import Outbox
        from events import EventEngine
        dependencies = {"config": cfg, "time": clock,
                        "gc": types.SimpleNamespace(collect=lambda: collections.append(clock.now),
                                                    mem_free=lambda: 100000)}
        for name, symbol, value in (("display", "Display", Screen), ("sensors", "Sensors", Sensor),
                                    ("events", "EventEngine", EventEngine if slow_io else Engine), ("location", "Location", Position),
                                    ("transport", "Transport", Network), ("sd_store", "SdStore", Storage),
                                    ("audio_recorder", "AudioRecorder", Storage),
                                    ("queue_store", "Outbox", Outbox)):
            dependencies[name] = types.SimpleNamespace(**{symbol: value})
        app = load("ui_test_main", "main.py", dependencies)
        with contextlib.redirect_stdout(io.StringIO()):
            app.run()
        if slow_io:
            screen_on = operations.index(("screen", True))
            audio_on = operations.index(("audio", True))
            self.assertLess(screen_on, audio_on)
            # Storage is now deferred: a screen refresh may run between native
            # audio and SD operations instead of batching them in the edge path.
            self.assertTrue(any(op[0] == "sd" for op in operations))
            self.assertEqual(rendered[-1][1], 13795)
            return
        self.assertEqual(rendered[0][0], 100)
        self.assertTrue(any(frame[0] == 200 for frame in rendered))
        self.assertGreater(rendered[-1][1], rendered[0][1])
        self.assertGreater(rendered[-1][2], rendered[0][2])
        self.assertEqual(collections, [0, 1000, 2000])


if __name__ == "__main__":
    unittest.main()
